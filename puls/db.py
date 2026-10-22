"""Baza: SQLite, bitta fayl (data/puls.db). Jadvallar va kichik yordamchilar."""
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS chats (
    id       INTEGER PRIMARY KEY,          -- Telegram chat id
    title    TEXT,
    demo     INTEGER NOT NULL DEFAULT 0,   -- 1 = namuna (demo) ma'lumot
    added_at TEXT
);
CREATE TABLE IF NOT EXISTS people (
    id           INTEGER PRIMARY KEY,      -- Telegram user id (guruhdagi)
    name         TEXT,
    username     TEXT,
    department   TEXT,                     -- AI | Backend | Frontend | Fullstack | DevOps ...
    invite_token TEXT,                     -- shaxsiy havola: t.me/<bot>?start=<token>
    dm_chat_id   INTEGER,                  -- xodim botga Start bosgan chat (yangi akkauntdan bossa yangilanadi)
    dm_linked_at TEXT,
    role         TEXT,                     -- 'rahbar': boshqalarga vazifa bera oladi, guruhdagi savollarni hal qiladi
    name_locked  INTEGER                   -- 1 = ism-familiyani rahbar panelda yozgan, Telegram nomi uni almashtirmaydi
);
CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT UNIQUE,                -- #teg kichik harfda: "hujjataylanishi"
    name       TEXT,                       -- ko'rinadigan nom: "Hujjat aylanishi"
    aliases    TEXT NOT NULL DEFAULT '',   -- erkin matnda tanish uchun boshqa nomlar, vergul bilan
    chat_id    INTEGER,
    deadline   TEXT,                       -- YYYY-MM-DD
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    msg_id     INTEGER NOT NULL,
    user_id    INTEGER,
    date       TEXT NOT NULL,              -- Toshkent vaqti, "YYYY-MM-DD HH:MM:SS"
    text       TEXT,
    kind       TEXT,                       -- task | done | blocker | deadline | none
    project_id INTEGER,
    source     TEXT,                       -- format | ai | taxmin
    reply_to   INTEGER,
    items      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (chat_id, msg_id)
);
CREATE TABLE IF NOT EXISTS vec_cache (
    text TEXT PRIMARY KEY,                 -- vazifa nomi
    vec  BLOB NOT NULL                     -- uning ma'no vektori (embedding, 256 float)
);
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    title       TEXT NOT NULL,
    assignee    TEXT,
    status      TEXT NOT NULL DEFAULT 'open',  -- open | done | taklif (xodim hali qabul qilmagan)
    created_at  TEXT NOT NULL,
    done_at     TEXT,
    created_msg INTEGER,                   -- messages.id
    done_msg    INTEGER,                   -- messages.id
    deadline    TEXT                       -- vazifaning o'z muddati, YYYY-MM-DD
);
CREATE TABLE IF NOT EXISTS blockers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL,
    text         TEXT,
    author       TEXT,
    created_at   TEXT NOT NULL,
    resolved_at  TEXT,
    msg          INTEGER,
    resolved_msg INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT                             -- JSON
);
CREATE TABLE IF NOT EXISTS decisions (     -- rahbar paneldan bajargan qarorlar jurnali
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    type       TEXT NOT NULL,              -- reassign | deadline | ping_person | ping_project | ping_blocker
    title      TEXT,
    payload    TEXT,                       -- JSON
    chat_id    INTEGER,
    sent       INTEGER NOT NULL DEFAULT 0, -- Telegram guruhga yuborildimi
    note       TEXT,
    origin     TEXT NOT NULL DEFAULT 'panel'  -- panel | guruh (botning savoliga guruhda javob berilgan)
);
CREATE TABLE IF NOT EXISTS alerts (        -- botning guruhdagi savoli: yuklama ogohlantirishi yoki vazifa taklifi
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,             -- yuklama | taklif
    created_at  TEXT NOT NULL,
    chat_id     INTEGER,
    msg_id      INTEGER,                   -- vazifa yozilgan xabar (Telegram)
    bot_chat_id INTEGER,                   -- savol qayerga yuborildi (guruh yoki shaxsiy chat)
    bot_msg_id  INTEGER,
    giver_id    INTEGER,                   -- vazifani bergan (Telegram user id)
    assignee    TEXT,
    task_ids    TEXT NOT NULL,             -- JSON
    options     TEXT,                      -- JSON: tavsiya qilingan xodimlar
    text        TEXT,                      -- yuborilgan matn: qaror shunga qo'shib tahrirlanadi
    resolved_at TEXT,
    resolution  TEXT,
    resolved_by TEXT
);
CREATE TABLE IF NOT EXISTS corrections (   -- AI tushunishidagi xatoni rahbar tuzatgani (fine-tuning uchun to'plam)
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  INTEGER NOT NULL,
    text        TEXT,
    old_kind    TEXT,
    old_project TEXT,
    new_kind    TEXT,
    new_project TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_queue (    -- namuna guruhlarning bugungi, hali vaqti kelmagan xabarlari
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    chat_id   INTEGER NOT NULL,
    title     TEXT,
    msg_id    INTEGER NOT NULL,
    user_id   INTEGER,
    user_name TEXT,
    username  TEXT,
    text      TEXT,
    reply_to  INTEGER
);
CREATE INDEX IF NOT EXISTS ix_tasks_project ON tasks(project_id, status);
CREATE INDEX IF NOT EXISTS ix_tasks_created ON tasks(created_at);
CREATE INDEX IF NOT EXISTS ix_tasks_done ON tasks(done_at);
CREATE INDEX IF NOT EXISTS ix_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS ix_messages_project ON messages(project_id, date);
"""


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


DEPARTMENTS = ["AI", "Backend", "Frontend", "Fullstack", "DevOps", "Dizayn", "Test (QA)"]


def init() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(people)")}
        for col, typ in (("department", "TEXT"), ("invite_token", "TEXT"), ("dm_chat_id", "INTEGER"), ("dm_linked_at", "TEXT"),
                         ("role", "TEXT"), ("name_locked", "INTEGER")):
            if col not in cols:  # eski bazani yangilash
                conn.execute("ALTER TABLE people ADD COLUMN %s %s" % (col, typ))
        if "origin" not in {r["name"] for r in conn.execute("PRAGMA table_info(decisions)")}:
            conn.execute("ALTER TABLE decisions ADD COLUMN origin TEXT NOT NULL DEFAULT 'panel'")
        if "deadline" not in {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}:
            conn.execute("ALTER TABLE tasks ADD COLUMN deadline TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_people_token ON people(invite_token)")


def rename_person(conn: sqlite3.Connection, old: str, new: str) -> None:
    """Ism hamma joyda birga almashadi: vazifalar, muammolar va bot savollari xodimni ismi bilan bog'laydi."""
    if not old or old == new:
        return
    conn.execute("UPDATE people SET name = ? WHERE name = ?", (new, old))
    conn.execute("UPDATE tasks SET assignee = ? WHERE assignee = ?", (new, old))
    conn.execute("UPDATE blockers SET author = ? WHERE author = ?", (new, old))
    conn.execute("UPDATE alerts SET assignee = ? WHERE assignee = ?", (new, old))


def bump_version(conn: sqlite3.Connection) -> None:
    """Har o'zgarishda raqam oshadi: panel shu raqamga qarab o'zini yangilaydi."""
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('version', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1"
    )


def version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    return int(row["value"]) if row else 0
