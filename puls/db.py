"""Baza: PostgreSQL + pgvector (asosiy) yoki SQLite (faqat mahalliy sinov). Jadvallar va kichik yordamchilar."""
import re
import sqlite3
from contextlib import contextmanager
from decimal import Decimal

from . import config, sqlro

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
CREATE TABLE IF NOT EXISTS task_events (   -- doska kartochkasi tarixi: kim, qachon, nima qildi (izohlar ham)
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    at      TEXT NOT NULL,
    who     TEXT,
    kind    TEXT NOT NULL,                 -- create | stage | assign | edit | comment | telegram | check | remind
    text    TEXT,
    msg     INTEGER                        -- bot guruhga yuborgan izoh yoki eslatma xabari: unga javob ham shu vazifaga boradi
);
CREATE INDEX IF NOT EXISTS ix_task_events ON task_events(task_id, at);
CREATE TABLE IF NOT EXISTS task_checks (   -- kartochka ichidagi ro'yxat (checklist)
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    text    TEXT NOT NULL,
    done    INTEGER NOT NULL DEFAULT 0,
    pos     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_task_checks ON task_checks(task_id, pos);
CREATE TABLE IF NOT EXISTS work_eval (     -- til modeli bahosi: bir xil ish nomi (bo'lim bilan) bir marta baholanadi
    key      TEXT PRIMARY KEY,
    weight   INTEGER NOT NULL,             -- 1 mayda .. 5 juda katta
    hours    REAL,                         -- taxminiy mehnat, soat
    category TEXT,
    reason   TEXT,
    model    TEXT,
    at       TEXT
);
CREATE TABLE IF NOT EXISTS judge_cache (   -- "eski ish qayta yozilganmi" degan savolga model javobi (juftlik bo'yicha)
    key     TEXT PRIMARY KEY,
    verdict TEXT NOT NULL,                 -- takror | davomi | muntazam | boshqa
    reason  TEXT,
    at      TEXT
);
CREATE TABLE IF NOT EXISTS message_edits ( -- xabarning eski variantlari: tahrirlansa yoki o'chirilsa ham tarix qoladi
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    at         TEXT NOT NULL,
    kind       TEXT NOT NULL,              -- edit | delete
    old_text   TEXT,
    new_text   TEXT
);
CREATE INDEX IF NOT EXISTS ix_message_edits ON message_edits(message_id, at);
CREATE TABLE IF NOT EXISTS accounts (      -- panelga kirish: login, parol va rol (auth.py)
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    login      TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,              -- ko'rinadigan ism-familiya
    pass_hash  TEXT NOT NULL,              -- pbkdf2_sha256$takror$tuz$xesh (Django bilan bir xil)
    role       TEXT NOT NULL,              -- admin | rahbar | menejer
    person     TEXT,                       -- people.name: Telegramdagi xodim (ixtiyoriy)
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_by TEXT,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS account_projects (  -- loyiha menejeri qaysi loyihalarni ko'radi
    account_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    PRIMARY KEY (account_id, project_id)
);
CREATE TABLE IF NOT EXISTS members (       -- guruh a'zolari: qo'shilib hali yozmagan odam ham "yozmadi" bo'lib ko'rinadi
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    joined_at TEXT,                        -- qo'shilgan yoki birinchi marta ko'ringan vaqt
    left_at   TEXT,                        -- guruhdan chiqqan yoki chiqarilgan (qaytsa NULL bo'ladi)
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS clients (       -- murojaat yozgan tizim foydalanuvchilari (xodim emas): fuqaro, notarius, FHDY xodimi
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT NOT NULL,              -- tg | src:<appeal_sources.id> (chatbot)
    ext        TEXT NOT NULL,              -- Telegram user id yoki chatbot ichidagi foydalanuvchi kaliti
    name       TEXT,
    username   TEXT,
    first_seen TEXT,
    staff      INTEGER,                    -- NULL noma'lum; 0 foydalanuvchi; 1 operator, 2 mutaxassis, 3 dasturchi (yordam xodimi)
    UNIQUE (source, ext)
);
CREATE TABLE IF NOT EXISTS appeal_sources ( -- chatbotlar: murojaatlarni kalit bilan API orqali yuboradi
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,              -- "@AdliyaHelpBot"
    project_id INTEGER,                    -- murojaatda tizim ko'rsatilmasa shu loyihaga yoziladi
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT,
    last_at    TEXT,
    active     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS chat_projects (  -- yordam guruhi qaysi tizim(lar)ga xizmat qiladi (odatda bitta)
    chat_id    INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    PRIMARY KEY (chat_id, project_id)
);
CREATE TABLE IF NOT EXISTS appeals (        -- murojaat: foydalanuvchining bitta muammosi, javoblari bilan
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,             -- tg | bot
    source_id   INTEGER,                   -- appeal_sources.id (chatbot)
    chat_id     INTEGER,                   -- yordam guruhi
    ext_id      TEXT,                      -- chatbotdagi murojaat raqami: qayta yuborilsa shu murojaat yangilanadi
    project_id  INTEGER,
    client_id   INTEGER,
    msg         INTEGER,                   -- messages.id: birinchi xabar
    text        TEXT,
    summary     TEXT,                      -- muammo bir gapda (AI)
    type        TEXT,                      -- appeals.TYPES
    created_at  TEXT NOT NULL,
    first_answer_at TEXT,
    first_grade TEXT,
    answered_by TEXT,
    line        INTEGER,                   -- 0 chatbot, 1 operator, 2 mutaxassis, 3 dasturchi: oxirgi javob bergan liniya
    grade       TEXT,                      -- good | part | tpl | none: oxirgi javob bahosi
    grade_note  TEXT,
    status      TEXT NOT NULL DEFAULT 'ochiq',  -- ochiq | javob | hal | qayta
    resolved_at TEXT,
    resolved_by TEXT,
    resolution  TEXT,                      -- javob (yechim berildi) | tasdiq (foydalanuvchi tasdiqladi) | jim (qaytib yozmadi) | qolda
    chain       INTEGER,                   -- takroriy zanjirning birinchi murojaati
    rep         INTEGER NOT NULL DEFAULT 0,
    last_at     TEXT,
    ai          TEXT,                      -- ai | qoida | qolda | NULL (chatbot murojaati hali o'qilmagan)
    fixed_by    TEXT
);
CREATE INDEX IF NOT EXISTS ix_appeals_created ON appeals(created_at);
CREATE INDEX IF NOT EXISTS ix_appeals_project ON appeals(project_id, created_at);
CREATE INDEX IF NOT EXISTS ix_appeals_chat ON appeals(chat_id, status);
CREATE INDEX IF NOT EXISTS ix_appeals_client ON appeals(client_id, project_id, type);
CREATE TABLE IF NOT EXISTS appeal_events (  -- murojaat yozishmasi: savol, qo'shimcha, javob (bahosi bilan), tasdiq, qayta ochish
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    appeal_id INTEGER NOT NULL,
    at        TEXT NOT NULL,
    kind      TEXT NOT NULL,               -- murojaat | qoshimcha | javob | tasdiq | qayta | tuzatish
    who       TEXT,
    staff     INTEGER NOT NULL DEFAULT 0,
    line      INTEGER,
    grade     TEXT,
    note      TEXT,
    text      TEXT,
    msg       INTEGER                      -- messages.id (Telegram havolasi uchun)
);
CREATE INDEX IF NOT EXISTS ix_appeal_events ON appeal_events(appeal_id, at);
CREATE INDEX IF NOT EXISTS ix_appeal_events_msg ON appeal_events(msg);
CREATE TABLE IF NOT EXISTS appeal_insights ( -- takroriy murojaatlar sababi va tavsiya (AI, kuniga bir marta)
    key   TEXT PRIMARY KEY,
    cause TEXT,
    act   TEXT,
    at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_project ON tasks(project_id, status);
CREATE INDEX IF NOT EXISTS ix_tasks_created ON tasks(created_at);
CREATE INDEX IF NOT EXISTS ix_tasks_done ON tasks(done_at);
CREATE INDEX IF NOT EXISTS ix_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS ix_messages_project ON messages(project_id, date);
"""


# ---------- ulanish: PostgreSQL (asosiy, DATABASE_URL) yoki SQLite (faqat mahalliy sinov) ----------
# Kod bir xil SQL yozadi ("?" belgisi bilan). PostgreSQL uchun bu qatlam uni moslaydi: "?" -> "%s", yangi qatorning id si
# (RETURNING id), qator ustuniga ham nomi, ham tartib raqami bilan murojaat, Decimal -> int/float.
PG = bool(config.DATABASE_URL)
VEC_DIM = 256
_SERIAL = {"projects", "messages", "tasks", "blockers", "decisions", "alerts", "corrections", "demo_queue", "task_events",
           "task_checks", "message_edits", "accounts", "clients", "appeal_sources", "appeals", "appeal_events"}
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.I)
_pool = None


class Row(tuple):
    """sqlite3.Row kabi: row["name"], row[0], dict(row), keys()."""

    def __new__(cls, values, index):
        r = super().__new__(cls, values)
        r._i = index
        return r

    def __getitem__(self, k):
        return tuple.__getitem__(self, self._i[k] if isinstance(k, str) else k)

    def keys(self):
        return self._i.keys()

    def get(self, k, default=None):
        return self[k] if k in self._i else default


def _plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _row_factory(cursor):
    index = {c.name: i for i, c in enumerate(cursor.description or [])}
    return lambda values: Row(tuple(_plain(v) for v in values), index)


class _Cur:
    def __init__(self, cur, lastrowid=None):
        self._c, self.lastrowid = cur, lastrowid

    def __iter__(self):
        return iter(self._c)

    def __getattr__(self, name):
        return getattr(self._c, name)


class PgConn:
    """psycopg ulanishi ustida sqlite3.Connection bilan bir xil ishlatiladigan qobiq."""

    def __init__(self, conn, pool=None):
        self._c, self._pool = conn, pool

    def execute(self, sql: str, args=()) -> _Cur:
        m = _INSERT_RE.match(sql)
        returning = bool(m and m.group(1).lower() in _SERIAL and "returning" not in sql.lower())
        if returning:
            sql += " RETURNING id"
        cur = self._c.execute(sql.replace("%", "%%").replace("?", "%s"), tuple(args) if args else None)
        rid = None
        if returning:
            r = cur.fetchone()
            rid = r[0] if r else None
        return _Cur(cur, rid)

    def executemany(self, sql: str, seq) -> None:
        with self._c.cursor() as cur:
            cur.executemany(sql.replace("%", "%%").replace("?", "%s"), list(seq))

    def executescript(self, script: str) -> None:
        self._c.execute(script)

    def commit(self) -> None:
        self._c.commit()

    def rollback(self) -> None:
        self._c.rollback()

    def close(self) -> None:
        if self._c is None:
            return
        try:
            self._c.rollback()
        finally:
            if self._pool is not None:
                self._pool.putconn(self._c)
            else:
                self._c.close()
            self._c = None


def _configure(conn) -> None:
    from pgvector.psycopg import register_vector
    try:
        register_vector(conn)
    except Exception:  # noqa: BLE001 — kengaytma hali yaratilmagan (init oldidan): vektorsiz ulanish ham ishlaydi
        conn.rollback()


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(config.DATABASE_URL, min_size=2, max_size=20, open=True, configure=_configure,
                               kwargs={"row_factory": _row_factory, "autocommit": False})
    return _pool


def reset_pool() -> None:
    """Sxema qayta yaratilganda (testlar, ko'chirish) eski ulanishlar yopiladi."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def connect():
    if PG:
        pool = _get_pool()
        return PgConn(pool.getconn(), pool)
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
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


DEPARTMENTS = ["AI", "Backend", "Frontend", "Fullstack", "DevOps", "Dizayn", "Test (QA)"]

# Keyin qo'shilgan ustunlar: eski bazada bo'lmasa qo'shiladi
LATE_COLUMNS = {
    "people": [("department", "TEXT"), ("invite_token", "TEXT"), ("dm_chat_id", "INTEGER"), ("dm_linked_at", "TEXT"),
               ("role", "TEXT"), ("name_locked", "INTEGER"),
               ("status", "TEXT"), ("tg_name", "TEXT"),  # tg_name: Telegramdagi asl ismi (panelda boshqa ism berilsa ham)  # status: xodim — admin tasdiqlagan (havolasiz ham qabul), begona — hisobga olinmaydi
               ("line", "INTEGER")],  # murojaatlarga javob berganda qaysi liniya: 1 operator, 2 mutaxassis, 3 dasturchi (NULL — avtomatik)
    "chats": [("kind", "TEXT")],  # ish (standart) | yordam — tizim foydalanuvchilari murojaat yozadigan guruh
    "projects": [("yordam", "INTEGER")],  # 1 = yordam guruhidan ochilgan tizim: ish guruhi yo'q, ish tahlilida ko'rinmaydi
    "decisions": [("origin", "TEXT NOT NULL DEFAULT 'panel'")],
    # deadline: vazifaning o'z muddati; stage..flag_text menejer doskasi uchun (board.py);
    # weight..dup_at hisobot sifati (quality.py) — til modeli bahosi va takror tekshiruvi
    "tasks": [("deadline", "TEXT"), ("stage", "TEXT"), ("progress", "INTEGER"), ("priority", "TEXT"), ("note", "TEXT"),
              ("created_by", "TEXT"), ("accepted_at", "TEXT"), ("tg_chat", "INTEGER"), ("tg_msg", "INTEGER"), ("flag", "TEXT"),
              ("flag_text", "TEXT"), ("weight", "INTEGER"), ("hours", "REAL"), ("wcat", "TEXT"), ("wnote", "TEXT"),
              ("dup_of", "INTEGER"), ("dup_score", "REAL"), ("dup_kind", "TEXT"), ("dup_note", "TEXT"), ("dup_at", "TEXT"),
              ("grp", "INTEGER"), ("plan_day", "TEXT")],  # grp: bir vazifa bir nechta xodimga berilganda har biriga alohida qator, grp bir xil; plan_day: "Ertangi reja" bandi qaysi kun uchun
    # holat: hisobotdagi "Holat: Sariq"; report_day: hisobot qaysi kun haqida (kechagi hisobot bugun yozilishi mumkin)
    "messages": [("edited_at", "TEXT"), ("deleted_at", "TEXT"), ("holat", "TEXT"), ("report_day", "TEXT")],
    "blockers": [("kind", "TEXT")],  # muammo — jamoaning o'z ishini to'xtatgan narsa; murojaat — guruhga tushgan xato yoki so'rov
    "task_events": [("msg", "INTEGER")],
}
LATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_tasks_dup ON tasks(dup_at, status)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_assignee ON tasks(assignee, done_at)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_tg ON tasks(tg_chat, tg_msg)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_people_token ON people(invite_token)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_appeals_ext ON appeals(source_id, ext_id)",
]


def _pg_type(t: str) -> str:
    """SQLite turlari -> PostgreSQL: Telegram id lari 32 bitga sig'maydi, shuning uchun hamma butun son BIGINT."""
    t = re.sub(r"\bINTEGER PRIMARY KEY AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", t)
    t = re.sub(r"\bINTEGER\b", "BIGINT", t)
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", t)


def pg_schema() -> str:
    s = _pg_type(SCHEMA).replace("vec  BLOB NOT NULL", "vec  vector(%d) NOT NULL" % VEC_DIM)
    return "CREATE EXTENSION IF NOT EXISTS vector;\n" + s + (
        "\nCREATE INDEX IF NOT EXISTS ix_vec_cache_hnsw ON vec_cache USING hnsw (vec vector_cosine_ops);\n")


def init() -> None:
    if PG:
        with session() as conn:
            conn.executescript(pg_schema())
            for table, cols in LATE_COLUMNS.items():
                for col, typ in cols:
                    conn.execute("ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s %s" % (table, col, _pg_type(typ)))
            for sql in LATE_INDEXES:
                conn.execute(sql)
            sqlro.ensure(conn)  # yordamchi agent uchun faqat o'qiladigan ko'rinishlar va rol
        reset_pool()  # endi vector turi bor: yangi ulanishlar uni taniydi
        return
    with session() as conn:
        conn.executescript(SCHEMA)
        for table, cols in LATE_COLUMNS.items():
            have = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
            for col, typ in cols:
                if col not in have:  # eski bazani yangilash
                    conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
        for sql in LATE_INDEXES:
            conn.execute(sql)
        sqlro.ensure(conn)


# Namuna (demo) xodimlar ID oralig'i: haqiqiy Telegram ID'lari (hozir 10 xonagacha) bu yerga hech qachon tushmaydi.
# Oldin 900000000-900999999 edi — haqiqiy xodim (A_D, 900686339) shu oraliqqa tushib, ro'yxatdan yo'qolgan edi.
DEMO_LO, DEMO_HI = 990_000_000_000, 990_999_999_999


def is_demo_person(pid) -> bool:
    return pid is not None and DEMO_LO <= int(pid) <= DEMO_HI


def rename_person(conn, old: str, new: str) -> None:
    """Ism hamma joyda birga almashadi: vazifalar, muammolar va bot savollari xodimni ismi bilan bog'laydi."""
    if not old or old == new:
        return
    conn.execute("UPDATE people SET name = ? WHERE name = ?", (new, old))
    conn.execute("UPDATE tasks SET assignee = ? WHERE assignee = ?", (new, old))
    conn.execute("UPDATE blockers SET author = ? WHERE author = ?", (new, old))
    conn.execute("UPDATE alerts SET assignee = ? WHERE assignee = ?", (new, old))
    conn.execute("UPDATE accounts SET person = ? WHERE person = ?", (new, old))


def bump_version(conn) -> None:
    """Har o'zgarishda raqam oshadi: panel shu raqamga qarab o'zini yangilaydi."""
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('version', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(meta.value AS INTEGER) + 1 AS TEXT)"
    )


def version(conn) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    return int(row["value"]) if row else 0
