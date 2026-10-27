"""Xabarni qabul qilish: tushunish -> bazaga yozish -> vazifalarni ochish yoki yopish.

Bot ham, tarixni import qilish ham, namuna ma'lumot ham shu bitta yo'ldan o'tadi.
"""
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import ai, appeals, config, db, memory, settings
from .parser import (MENTION_RE, Parsed, detect_project, looks_like_work, match_score, norm_key, parse_format, parse_free,
                     parse_report, stems, title_department, words)

FMT = "%Y-%m-%d %H:%M:%S"
NAME_JUNK_RE = re.compile(r"[^\w\s'ʻ’‘`.-]", re.U)


def clean_name(name: str | None) -> str:
    """Telegram nomidagi bezaklarsiz ism: 'Javohir ⚜️' -> 'Javohir'."""
    s = re.sub(r"\s+", " ", NAME_JUNK_RE.sub("", name or "")).strip(" .-")
    return s or (name or "").strip()


@dataclass
class Incoming:
    chat_id: int
    chat_title: str
    msg_id: int
    user_id: int
    user_name: str
    username: str | None
    date: datetime          # Toshkent vaqti, tzinfo'siz
    text: str
    reply_to: int | None = None
    edited: bool = False
    demo: bool = False
    lead: bool = True       # yozgan kishi boshqalarga vazifa bera oladimi ("Faqat rahbarlar" sozlamasida tekshiriladi)
    admin: bool = False     # Telegram guruh admini: hali hech kim deb belgilanmagan bo'lsa rahbar deb olinadi
    forwarded_at: datetime | None = None  # forward qilingan xabarning asl yuborilgan vaqti (Toshkent)
    media: bytes | None = None  # ovozli xabar, video-xabar yoki rasm: AI avval matnga aylantiradi
    mime: str | None = None


@dataclass
class Result:
    kind: str
    source: str
    project: str | None = None
    created: int = 0
    closed: int = 0
    duplicate: bool = False
    missing_project: bool = False
    task_ids: list = field(default_factory=list)   # yangi ochilgan vazifalar
    proposed: list = field(default_factory=list)   # xodim qabul qilishini kutayotgan vazifalar
    changed: int = 0                               # muddati yoki egasi o'zgargan vazifalar
    repeats: list = field(default_factory=list)    # aynan shu ishlar oldin ham yozilgan: [(ish, qachon)]
    skipped: bool = False                          # yozgan kishi botga ulanmagan: xabar saqlandi, hisobot qabul qilinmadi


def humanize(tag: str) -> str:
    """'HujjatAylanishi' -> 'Hujjat Aylanishi', 'yangi_portal' -> 'Yangi portal'"""
    text = tag.replace("_", " ").replace("-", " ")
    text = re.sub(r"(?<=[a-zа-яё0-9])(?=[A-ZА-ЯЁ])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1].upper() + text[1:]


def load_projects(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT id, key, name, aliases, chat_id, deadline FROM projects")]


def _relevant(conn: sqlite3.Connection, inc: Incoming, reply_ids: list[int], limit: int = 70) -> list[dict]:
    """Xabar haqida bo'lishi mumkin bo'lgan ochiq vazifalar, yoshidan qat'i nazar:
    javob berilgan xabarniki -> ma'nosi yaqin (embedding) -> ismi tilga olingan xodimniki -> shu guruhdagi oxirgilari."""
    rows = [dict(r) for r in conn.execute(
        "SELECT t.id, t.title, t.assignee, t.deadline, substr(t.created_at, 1, 10) AS created, p.key AS project, "
        "p.chat_id FROM tasks t JOIN projects p ON p.id = t.project_id WHERE t.status = 'open'")]
    by_id = {t["id"]: t for t in rows}
    picked: list[int] = [i for i in reply_ids if i in by_id]
    text = inc.text or ""
    # Eng yaqin 20 tasi nomzod bo'ladi; qaysi biri haqiqatan gap ketayotgani AI hal qiladi (chegara qo'yilmaydi)
    picked += [t["id"] for _, t in memory.nearest(conn, text, rows, 20)]
    tokens = words(text)
    usernames = {u.lower() for u in MENTION_RE.findall(text)}
    named = set()
    for r in conn.execute("SELECT name, username FROM people"):
        first = (words(r["name"] or "") or [""])[0]
        if (r["username"] or "").lower() in usernames or (len(first) >= 4 and any(w.startswith(first[:5]) for w in tokens)):
            named.add(r["name"])
    picked += [t["id"] for t in sorted(rows, key=lambda t: -t["id"]) if t["assignee"] in named][:20]
    picked += [t["id"] for t in sorted(rows, key=lambda t: -t["id"]) if t["chat_id"] == inc.chat_id][:25]
    seen, out = set(), []
    for i in picked:
        if i not in seen:
            seen.add(i)
            out.append({k: v for k, v in by_id[i].items() if k != "chat_id"})
    return out[:limit]


def context(conn: sqlite3.Connection, inc: Incoming) -> dict:
    """AI odamdek tushunishi uchun: kim kim, guruhda qanday ochiq ishlar bor, xabar nimaga javob."""
    reply = None
    extra = []
    if inc.reply_to:
        parent = conn.execute(
            "SELECT m.id, m.text, pe.name FROM messages m LEFT JOIN people pe ON pe.id = m.user_id "
            "WHERE m.chat_id = ? AND m.msg_id = ?", (inc.chat_id, inc.reply_to)).fetchone()
        if parent is not None:
            extra = [r["id"] for r in conn.execute(
                "SELECT id FROM tasks WHERE created_msg = ? AND status = 'open'", (parent["id"],))]
            reply = {"author": parent["name"], "text": parent["text"] or "", "task_ids": extra}
    tasks = _relevant(conn, inc, extra)
    # Hamma ma'lum xodim (guruhda hali yozmagani ham ism bilan tilga olinishi mumkin), shu guruhdagilar birinchi
    team = [(r["name"], r["username"]) for r in conn.execute(
        "SELECT pe.name, pe.username, max(CASE WHEN m.chat_id = ? THEN 1 ELSE 0 END) AS here FROM people pe "
        "LEFT JOIN messages m ON m.user_id = pe.id WHERE pe.username IS NOT NULL GROUP BY pe.id, pe.name, pe.username "
        "ORDER BY here DESC, pe.name LIMIT 150", (inc.chat_id,))]
    problems = [{"id": r["id"], "text": r["text"], "author": r["author"], "at": r["created_at"][:16], "kind": r["kind"]} for r in conn.execute(
        "SELECT b.id, b.text, b.author, b.created_at, b.kind FROM blockers b JOIN projects p ON p.id = b.project_id "
        "WHERE p.chat_id = ? AND b.resolved_at IS NULL ORDER BY b.id DESC LIMIT 20", (inc.chat_id,))]
    # Guruhni kuzatib turgan hamkasbdek: bugungi suhbat ("api ni qaradizmi?" -> "api ni to'g'riladim" -> kechki hisobot)
    chat = [{"time": r["date"][11:16], "who": r["name"] or "-", "text": " ".join((r["text"] or "").split())[:220]}
            for r in reversed(conn.execute(
                "SELECT m.date, m.text, pe.name FROM messages m LEFT JOIN people pe ON pe.id = m.user_id "
                "WHERE m.chat_id = ? AND m.date >= ? AND m.date <= ? AND m.msg_id != ? ORDER BY m.date DESC, m.id DESC LIMIT 30",
                (inc.chat_id, inc.date.strftime("%Y-%m-%d 00:00:00"), inc.date.strftime(FMT), inc.msg_id)).fetchall())]
    return {"team": team, "tasks": tasks, "reply": reply, "today": _done_today(conn, inc), "problems": problems, "chat": chat}


def _done_today(conn: sqlite3.Connection, inc: Incoming) -> list[dict]:
    """Bugun shu guruhda bajarildi deb yozilgan ishlar: kechki hisobot kun ichida yozilganni qayta sanamasligi va
    hamkasb qilgan ishni o'ziniki qilib yozish ko'rinishi uchun. Tahrirlanayotgan xabarning o'z ishlari kirmaydi."""
    own = conn.execute("SELECT id FROM messages WHERE chat_id = ? AND msg_id = ?", (inc.chat_id, inc.msg_id)).fetchone()
    out = []
    for r in conn.execute(
            "SELECT t.id, t.title, t.assignee, t.done_at, t.done_msg, m.text FROM tasks t JOIN projects p ON p.id = t.project_id "
            "LEFT JOIN messages m ON m.id = t.done_msg "
            "WHERE t.status = 'done' AND p.chat_id = ? AND t.done_at >= ? AND t.done_at <= ? AND coalesce(t.done_msg, 0) != ? "
            "ORDER BY t.done_at DESC LIMIT 30",
            (inc.chat_id, inc.date.strftime("%Y-%m-%d 00:00:00"), inc.date.strftime(FMT), own["id"] if own else 0)):
        # Dalil: qaysi xabar bilan yozilgan va qaysi muammoni yopgan ("api ni to'g'riladim" -> "arizalar bo'sh chiqishi")
        solved = [b["text"] for b in conn.execute("SELECT text FROM blockers WHERE resolved_msg = ?", (r["done_msg"],))] if r["done_msg"] else []
        out.append({"id": r["id"], "title": r["title"], "assignee": r["assignee"], "time": r["done_at"][11:16],
                    "said": " ".join((r["text"] or "").split())[:160], "solved": solved})
    return out


# "Bajarildi" ostiga yozilgan, lekin hali tugamagan ish: "o'rganib chiqilmoqda", "yechim qilish jarayonida", "test qilinyapti"
ONGOING_RE = re.compile(r"(?:jarayon(?:i)?da|[a-z\u02bb\u02bc'\u2018\u2019]+moqda|[a-z\u02bb\u02bc'\u2018\u2019]+yapti|"
                        r"[a-z\u02bb\u02bc'\u2018\u2019]+yapmiz|[a-z\u02bb\u02bc'\u2018\u2019]+yapman)\W*$", re.I)


def group_project(conn: sqlite3.Connection, chat_id: int, title: str, tag: str | None = None, when: str | None = None):
    """Bitta guruh — bitta loyiha: hisobotdagi teg qanday bo'lishidan qat'i nazar guruhning o'z loyihasi; hali yo'q bo'lsa
    guruh nomi bilan ochiladi. Boshqa guruhning loyihasi hech qachon olinmaydi (nomi o'xshasa ham). `tag` eski
    chaqiruvlar bilan moslik uchun qoldi: guruh ichida teg yangi yoki boshqa loyiha tanlamaydi."""
    rows = conn.execute("SELECT * FROM projects WHERE chat_id = ? ORDER BY id", (chat_id,)).fetchall()
    if rows:
        return rows[0]
    name = clean_name(title)[:80] or "Guruh %d" % abs(chat_id)
    key = norm_key(name) or "guruh-%d" % abs(chat_id)
    if conn.execute("SELECT 1 FROM projects WHERE key = ?", (key,)).fetchone():
        key = "%s-%d" % (key, abs(chat_id))  # boshqa guruhda shu nomli loyiha bor
    conn.execute("INSERT INTO projects(key, name, chat_id, created_at) VALUES(?, ?, ?, ?)",
                 (key, name, chat_id, when or config.now().strftime(FMT)))
    return conn.execute("SELECT * FROM projects WHERE key = ?", (key,)).fetchone()


def merge_group_projects(conn: sqlite3.Connection) -> int:
    """Bitta guruh — bitta loyiha. Teg rejimidan qolgan ortiqcha loyihalar (bir guruhda "Sinov" va "#shajara" kabi) guruhning
    birinchi loyihasiga qo'shiladi: vazifalar, xabarlar, muammolar va menejer ruxsatlari ko'chadi, ortiqchasi o'chadi.
    Ortiqcha loyiha nomi asosiysining boshqa nomlariga (aliases) yoziladi. Qaytaradi: nechta loyiha qo'shildi."""
    if settings.load(conn)["project_mode"] != "guruh":
        return 0
    n = 0
    for c in conn.execute("SELECT p.chat_id FROM projects p JOIN chats c ON c.id = p.chat_id WHERE coalesce(c.demo, 0) = 0 "
                          "GROUP BY p.chat_id HAVING count(*) > 1").fetchall():  # namuna ma'lumotga tegilmaydi
        rows = conn.execute("SELECT * FROM projects WHERE chat_id = ? ORDER BY id", (c["chat_id"],)).fetchall()
        keep = rows[0]
        aliases = [a.strip() for a in (keep["aliases"] or "").split(",") if a.strip()]
        for x in rows[1:]:
            for table in ("tasks", "messages", "blockers"):
                conn.execute("UPDATE %s SET project_id = ? WHERE project_id = ?" % table, (keep["id"], x["id"]))
            conn.execute("INSERT INTO account_projects(account_id, project_id) SELECT account_id, ? FROM account_projects "
                         "WHERE project_id = ? ON CONFLICT DO NOTHING", (keep["id"], x["id"]))
            conn.execute("DELETE FROM account_projects WHERE project_id = ?", (x["id"],))
            if x["deadline"] and not keep["deadline"]:
                conn.execute("UPDATE projects SET deadline = ? WHERE id = ?", (x["deadline"], keep["id"]))
            aliases += [a for a in (x["name"], x["key"]) if a and a not in aliases]
            conn.execute("DELETE FROM projects WHERE id = ?", (x["id"],))
            n += 1
        conn.execute("UPDATE projects SET aliases = ? WHERE id = ?", (", ".join(aliases)[:500], keep["id"]))
    if n:
        db.bump_version(conn)
    return n


def backfill_report_days(conn: sqlite3.Connection) -> int:
    """Bir martalik: "hisobot kuni" va "holat" ustunlari qo'shilishidan oldin kelgan bo'limli hisobotlar matni qayta o'qilib
    to'ldiriladi (AI chaqirilmaydi). Kechikkan hisobot, hisobot vaqti va holat eski kunlar uchun ham to'g'ri chiqadi."""
    key = "backfill:report_day:1"
    if conn.execute("SELECT 1 FROM meta WHERE key = ?", (key,)).fetchone():
        return 0
    n = 0
    for m in conn.execute("SELECT id, date, text FROM messages WHERE report_day IS NULL AND kind != 'none' AND text IS NOT NULL").fetchall():
        day = datetime.strptime(m["date"][:10], "%Y-%m-%d").date()
        p = parse_report(m["text"], day)
        if p and p.sections:
            conn.execute("UPDATE messages SET report_day = ?, holat = coalesce(holat, ?) WHERE id = ?",
                         ((p.day or day).isoformat(), p.holat, m["id"]))
            n += 1
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(n)))
    if n:
        db.bump_version(conn)
    return n


def ensure_group_projects(conn: sqlite3.Connection) -> int:
    """"guruh" rejimida bot qo'shilgan har guruhning loyihasi bor: hisobot kelmasidan oldin ham Loyihalarda ko'rinadi.
    Bir guruhda ortiqcha loyiha qolgan bo'lsa avval birlashtiriladi (bitta guruh — bitta loyiha)."""
    if settings.load(conn)["project_mode"] != "guruh":
        return 0
    merge_group_projects(conn)
    n = 0
    for c in conn.execute("SELECT c.id, c.title FROM chats c WHERE c.id < 0 AND coalesce(c.demo, 0) = 0 AND coalesce(c.kind, 'ish') != 'yordam' "
                          "AND c.title NOT LIKE '%(oldingi)' AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.chat_id = c.id)").fetchall():
        group_project(conn, c["id"], c["title"] or "")
        n += 1
    if n:
        db.bump_version(conn)
    return n


def _sure_refs(conn: sqlite3.Connection, parsed: Parsed, parent, inc: Incoming) -> list[int]:
    """AI ko'rsatgan vazifa faqat aloqasi ko'rinib turganda yopiladi: javob berilgan xabarniki, yozganning o'z ishi va
    kamida bir so'zi umumiy, yoki boshqaning ishi bo'lsa nomi xabarda deyarli to'liq bor. Aks holda AI adashgan:
    "pdf ham bo'ldi" ham, "sms modulini oldim, kodini ko'rib chiqdim" ham hamkasbning "SMS xabarnoma" vazifasini yopmaydi."""
    said = " ".join([inc.text or ""] + [i.title for i in parsed.items])
    out = []
    for tid in parsed.refs:
        t = conn.execute("SELECT id, title, assignee, created_msg FROM tasks WHERE id = ?", (tid,)).fetchone()
        if t is None:
            continue
        linked = parent is not None and t["created_msg"] == parent["id"]
        mine = t["assignee"] == inc.user_name
        if linked or (mine and stems(t["title"]) & stems(said)) or (not mine and match_score(t["title"], said) >= 0.75):
            out.append(tid)
    return out


def accepted(conn: sqlite3.Connection, inc: Incoming, S: dict | None = None) -> bool:
    """Hisobot faqat shaxsiy havola orqali botga ulangan xodimdan qabul qilinadi (sozlamada "hamma" bo'lmasa).
    Rahbar va namuna guruhlar bundan mustasno."""
    if inc.demo or (config.OWNER_ID and inc.user_id == config.OWNER_ID):
        return True
    row = conn.execute("SELECT dm_chat_id, status FROM people WHERE id = ?", (inc.user_id,)).fetchone()
    if row and row["status"] == "begona":  # rahbar "begona" degan: hech qachon hisobga olinmaydi
        return False
    if (S or settings.load(conn))["report_from"] == "hamma":
        return True
    return bool(row and (row["dm_chat_id"] or row["status"] == "xodim"))


def triage(conn: sqlite3.Connection, inc: Incoming, S: dict | None = None) -> Parsed | None:
    """Arzon saralash, AI'siz: tegli hisobot qoida bilan aniq o'qiladi; ishga o'xshamagan suhbat darhol "none".
    None qaytsa, xabarni AI o'qishi kerak (tegsiz, lekin ishga oid). "teg" rejimida AI umuman ishlatilmaydi."""
    today = inc.date.date()
    parsed = parse_report(inc.text, today) or parse_format(inc.text, today)
    if parsed is not None:
        return parsed
    reply_work = bool(inc.reply_to and conn.execute(
        "SELECT 1 FROM messages WHERE chat_id = ? AND msg_id = ? AND kind != 'none'", (inc.chat_id, inc.reply_to)).fetchone())
    if not reply_work and not looks_like_work(inc.text):
        return Parsed("none", source="filtr")
    if (S or settings.load(conn))["ai_read"] == "teg":
        return parse_free(inc.text, load_projects(conn), today) if reply_work else Parsed("none", source="filtr")
    return None


def boss(conn: sqlite3.Connection, inc: Incoming) -> bool:
    """Yozgan kishi rahbarmi: egasi, panelda "Rahbar" deb belgilangan yoki hali hech kim deb belgilanmagan guruh admini.
    Rahbarning ismi aytilmagan topshirig'i jamoaga beriladi, uning o'z ishi bo'lib sanalmaydi."""
    if config.OWNER_ID and inc.user_id == config.OWNER_ID:
        return True
    row = conn.execute("SELECT role, status FROM people WHERE id = ?", (inc.user_id,)).fetchone()
    if row is not None and row["role"] == "rahbar":
        return True
    return inc.admin and (row is None or (row["role"] is None and row["status"] is None))


def understand(conn: sqlite3.Connection, inc: Incoming, use_ai: bool) -> Parsed:
    """Faqat o'qiydi, bazaga yozmaydi (AI javobini kutayotganda baza band bo'lmasin)."""
    today = inc.date.date()
    parsed = triage(conn, inc)
    if parsed is not None:
        return parsed
    projects = load_projects(conn)
    if use_ai:
        parsed = ai.extract(inc.text, inc.user_name, projects, today, context=context(conn, inc), lead=boss(conn, inc))
        if parsed is not None:
            return parsed
    return parse_free(inc.text, projects, today)


def _resolve_person(conn: sqlite3.Connection, mention: str | None, fallback: str) -> str:
    if not mention:
        return fallback
    row = conn.execute("SELECT name FROM people WHERE lower(username) = lower(?)", (mention.lstrip("@"),)).fetchone()
    return row["name"] if row else mention


def _revert(conn: sqlite3.Connection, mid: int) -> None:
    """Xabar tahrirlanganda uning oldingi ta'sirini bekor qiladi."""
    conn.execute("DELETE FROM tasks WHERE created_msg = ?", (mid,))
    conn.execute("UPDATE tasks SET status = 'open', done_at = NULL, done_msg = NULL WHERE done_msg = ?", (mid,))
    conn.execute("DELETE FROM blockers WHERE msg = ?", (mid,))
    conn.execute("UPDATE blockers SET resolved_at = NULL, resolved_msg = NULL WHERE resolved_msg = ?", (mid,))


def _close(conn: sqlite3.Connection, task_id: int, when: str, mid: int) -> None:
    conn.execute("UPDATE tasks SET status = 'done', done_at = ?, done_msg = ? WHERE id = ?", (when, mid, task_id))


def _register(conn: sqlite3.Connection, inc: Incoming, when: str) -> None:
    """Guruh va yozgan kishini bazaga yozadi (yoki yangilaydi). inc.user_name panelda ko'rinadigan ismga almashadi."""
    conn.execute(  # bu yerga faqat ish guruhi xabari keladi (yordam guruhi ingest boshida ajratiladi)
        "INSERT INTO chats(id, title, demo, added_at, kind) VALUES(?, ?, ?, ?, 'ish') "
        "ON CONFLICT(id) DO UPDATE SET title = excluded.title",
        (inc.chat_id, inc.chat_title, int(inc.demo), when),
    )
    # Ism: rahbar panelda yozgan ism-familiya ustun; bo'lmasa Telegram nomi (bezaklarsiz). Nom o'zgarsa, eski vazifalar ham ergashadi
    row = conn.execute("SELECT name, name_locked FROM people WHERE id = ?", (inc.user_id,)).fetchone()
    name = row["name"] if row and row["name_locked"] else clean_name(inc.user_name)
    if row is None:
        conn.execute("INSERT INTO people(id, name, username, tg_name) VALUES(?, ?, ?, ?)", (inc.user_id, name, inc.username, inc.user_name))
    else:
        db.rename_person(conn, row["name"], name)
        conn.execute("UPDATE people SET username = ?, tg_name = ? WHERE id = ?", (inc.username, inc.user_name, inc.user_id))
    inc.user_name = name
    if inc.chat_id < 0 and not inc.demo:
        member_seen(conn, inc.chat_id, inc.user_id, when)


def member_seen(conn: sqlite3.Connection, chat_id: int, user_id: int, when: str) -> None:
    """Yozgan yoki qo'shilgan odam shu guruh a'zosi (chiqib ketib qaytgan bo'lsa ham)."""
    conn.execute("INSERT INTO members(chat_id, user_id, joined_at) VALUES(?, ?, ?) "
                 "ON CONFLICT(chat_id, user_id) DO UPDATE SET left_at = NULL", (chat_id, user_id, when))


def member_joined(conn: sqlite3.Connection, chat_id: int, chat_title: str, user_id: int, full_name: str,
                  username: str | None, when: str) -> None:
    """Guruhga yangi odam qo'shildi: u hali hech narsa yozmagan bo'lsa ham panelda ko'rinadi (tasdiqlash va "yozmadi" uchun).
    Yordam guruhiga qo'shilgan odam xodim emas: hech qayerga yozilmaydi (murojaat yozsa, foydalanuvchi bo'lib ko'rinadi)."""
    if appeals.is_support(conn, chat_id, chat_title):
        return
    conn.execute("INSERT INTO chats(id, title, demo, added_at) VALUES(?, ?, 0, ?) ON CONFLICT(id) DO UPDATE SET title = excluded.title",
                 (chat_id, chat_title, when))
    if conn.execute("SELECT 1 FROM people WHERE id = ?", (user_id,)).fetchone() is None:
        conn.execute("INSERT INTO people(id, name, username, tg_name) VALUES(?, ?, ?, ?)",
                     (user_id, clean_name(full_name) or (username or str(user_id)), username, full_name))
    member_seen(conn, chat_id, user_id, when)
    db.bump_version(conn)


def member_left(conn: sqlite3.Connection, chat_id: int, user_id: int, when: str) -> None:
    conn.execute("UPDATE members SET left_at = ? WHERE chat_id = ? AND user_id = ?", (when, chat_id, user_id))
    db.bump_version(conn)


def ingest(conn: sqlite3.Connection, inc: Incoming, use_ai: bool = True, pre: Parsed | None = None) -> Result:
    """pre: oldindan tayyorlangan natija (masalan, namuna ma'lumotda AI parallel chaqirilganda)."""
    if not inc.demo and appeals.is_support(conn, inc.chat_id, inc.chat_title):
        # yordam guruhi: tizim foydalanuvchilarining murojaatlari — hisobot, vazifa va xodimlar ro'yxatiga aralashmaydi
        return appeals.handle(conn, inc, use_ai and pre is None)
    existing = conn.execute(
        "SELECT id FROM messages WHERE chat_id = ? AND msg_id = ?", (inc.chat_id, inc.msg_id)
    ).fetchone()
    if existing and not inc.edited:
        return Result("none", "format", duplicate=True)
    if not accepted(conn, inc):
        # Botga ulanmagan: xodim ro'yxatda paydo bo'ladi (rahbar unga havola yubora oladi), xabar saqlanadi,
        # lekin hisobot sifatida o'qilmaydi va AI'ga ham yuborilmaydi
        when = inc.date.strftime(FMT)
        _register(conn, inc, when)
        if existing:
            conn.execute("UPDATE messages SET text = ? WHERE id = ?", (inc.text, existing["id"]))
        else:
            conn.execute("INSERT INTO messages(chat_id, msg_id, user_id, date, text, kind, project_id, source, reply_to) "
                         "VALUES(?, ?, ?, ?, ?, 'none', NULL, 'ulanmagan', ?)",
                         (inc.chat_id, inc.msg_id, inc.user_id, when, inc.text, inc.reply_to))
        db.bump_version(conn)
        return Result("none", "ulanmagan", skipped=True)

    if inc.media and use_ai and pre is None:
        heard = ai.transcribe(inc.media, inc.mime or "application/octet-stream", inc.text)
        if heard:
            label = "Rasm" if (inc.mime or "").startswith("image/") else "Ovozli xabar"
            inc.text = "%s: %s%s" % (label, heard, "\n" + inc.text if inc.text and inc.text not in heard else "")
    parsed = pre or understand(conn, inc, use_ai)
    if inc.forwarded_at and parsed.day is None and inc.forwarded_at.date() < inc.date.date():
        parsed.day = inc.forwarded_at.date()  # kechagi hisobotini bugun forward qildi: ish kechaga yoziladi
    if (parsed.source == "ai" or parsed.sections) and parsed.project is None and parsed.kind in ("task", "done", "blocker"):
        # AI loyihani aniqlamasa ("Bulutda ... yakunlandi"), nomi bo'yicha qidiruv yordam beradi
        parsed.project = detect_project(inc.text, load_projects(conn))
    when = inc.date.strftime(FMT)
    lead = boss(conn, inc) and not inc.demo  # namuna jamoada loyiha rahbarlari o'zlari ham ishlaydi (eski yozuvlar shunga mos)
    _register(conn, inc, when)
    if inc.admin:  # guruh admini birinchi marta yozdi: rahbar deb belgilanadi (panelda o'zgartirsa, qayta belgilanmaydi)
        conn.execute("UPDATE people SET role = 'rahbar' WHERE id = ? AND role IS NULL AND status IS NULL", (inc.user_id,))
    # bo'lim: hisobotdagi teg (#backend), bo'lmasa guruh nomi ("Backend jamoasi") — faqat bo'limi hali belgilanmagan xodimga
    dept = parsed.department or title_department(inc.chat_title)
    if dept:
        conn.execute("UPDATE people SET department = ? WHERE id = ? AND (department IS NULL OR department = '' "
                     "OR department = 'Belgilanmagan')", (dept, inc.user_id))

    # Loyihani aniqlash. "guruh" rejimi (standart): har guruh — bitta loyiha ("o'nta guruh — o'nta loyiha").
    # "teg" rejimi: aniq teg -> javob berilgan xabarning loyihasi -> guruhda yagona loyiha
    project = None
    if inc.chat_id < 0 and not inc.demo and settings.load(conn)["project_mode"] == "guruh":
        if parsed.kind != "none":
            project = group_project(conn, inc.chat_id, inc.chat_title, parsed.project, when)
    elif parsed.project:
        key = norm_key(parsed.project)
        project = conn.execute("SELECT * FROM projects WHERE key = ?", (key,)).fetchone()
        if project is None and parsed.source == "format" and key:
            conn.execute(
                "INSERT INTO projects(key, name, chat_id, created_at) VALUES(?, ?, ?, ?)",
                (key, humanize(parsed.project), inc.chat_id, when),
            )
            project = conn.execute("SELECT * FROM projects WHERE key = ?", (key,)).fetchone()
    parent = None
    if inc.reply_to:
        parent = conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? AND msg_id = ?", (inc.chat_id, inc.reply_to)
        ).fetchone()
    if project is None and parent is not None and parent["project_id"] and parsed.kind != "none":
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (parent["project_id"],)).fetchone()
    if project is None and parsed.kind != "none":
        only = conn.execute("SELECT * FROM projects WHERE chat_id = ?", (inc.chat_id,)).fetchall()
        if len(only) == 1:
            project = only[0]
        elif not only and parsed.kind in ("task", "done", "blocker") and inc.chat_id < 0:
            # guruhda hali loyiha yo'q va hisobotda loyiha tegi yo'q: loyiha guruh nomi bilan ochiladi (savol bermasdan)
            name = clean_name(inc.chat_title)[:80]
            key = norm_key(name)
            if key:
                project = conn.execute("SELECT * FROM projects WHERE key = ?", (key,)).fetchone()
                # "Shajara - Ishlar" guruhi: nomidagi so'z bor loyihaga ("Shajara") mos kelsa, yangi loyiha ochilmaydi
                for w in words(name):
                    if project is None and len(w) >= 4:
                        project = conn.execute("SELECT * FROM projects WHERE key = ?", (norm_key(w),)).fetchone()
                if project is None:
                    conn.execute("INSERT INTO projects(key, name, chat_id, created_at) VALUES(?, ?, ?, ?)", (key, name, inc.chat_id, when))
                    project = conn.execute("SELECT * FROM projects WHERE key = ?", (key,)).fetchone()
    pid = project["id"] if project else None

    if existing:
        mid = existing["id"]
        old = conn.execute("SELECT text FROM messages WHERE id = ?", (mid,)).fetchone()["text"]
        if (old or "") != (inc.text or ""):
            # Eski variant saqlanadi: rahbar hisobot keyin nima deb o'zgartirilganini ko'radi
            stamp = config.now().strftime(FMT)
            conn.execute("INSERT INTO message_edits(message_id, at, kind, old_text, new_text) VALUES(?, ?, 'edit', ?, ?)",
                         (mid, stamp, old, inc.text))
            conn.execute("UPDATE messages SET edited_at = ? WHERE id = ?", (stamp, mid))
        _revert(conn, mid)
        conn.execute(
            "UPDATE messages SET text = ?, kind = ?, project_id = ?, source = ? WHERE id = ?",
            (inc.text, parsed.kind, pid, parsed.source, mid),
        )
    else:
        cur = conn.execute(
            "INSERT INTO messages(chat_id, msg_id, user_id, date, text, kind, project_id, source, reply_to) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (inc.chat_id, inc.msg_id, inc.user_id, when, inc.text, parsed.kind, pid, parsed.source, inc.reply_to),
        )
        mid = cur.lastrowid

    # hisobot qaysi kun haqida va xodim o'zi bergan holat (panelda: kechikkan hisobot, "Sariq" holat).
    # Faqat hisobot (bo'limli yoki bajarilgan ish): vazifa berish, savol va murojaat "hisobot yozdi" hisoblanmaydi
    report = parsed.kind != "none" and (bool(parsed.sections) or parsed.kind == "done")
    conn.execute("UPDATE messages SET holat = ?, report_day = ? WHERE id = ?",
                 (parsed.holat, (parsed.day or inc.date.date()).isoformat() if report else None, mid))
    result = Result(parsed.kind, parsed.source, project["name"] if project else None)
    if parsed.kind in ("task", "done", "blocker", "request") and pid is None:
        result.missing_project = True
    for bid in parsed.solves:
        # AI kontekstdan topdi: shu xabar qaysi ochiq muammoni hal qildi (hamkasb aytgan va reply'siz bo'lsa ham)
        n = conn.execute("UPDATE blockers SET resolved_at = ?, resolved_msg = ? WHERE id = ? AND resolved_at IS NULL",
                         (when, mid, bid)).rowcount
        result.closed += n + (_close_related(conn, bid, inc.user_name, when, mid) if n else 0)

    if parsed.sections and pid:
        _report(conn, parsed, pid, inc, when, mid, result)
    elif parsed.kind == "task" and pid:
        # "Faqat rahbarlar" sozlamasida oddiy xodim boshqaga yozgan vazifa o'sha xodim qabul qilguncha taklif bo'lib turadi
        strict = not inc.lead and settings.load(conn)["assign_policy"] == "rahbar"
        asked = conn.execute("SELECT id, title FROM tasks WHERE created_msg = ? AND status IN ('open', 'taklif')",
                             (parent["id"],)).fetchall() if parent is not None and parent["kind"] == "task" else []
        for item in parsed.items:
            # rahbar ismini aytmagan topshiriq jamoaniki (kim olishi ochiq), oddiy xodimniki esa o'z rejasi
            who = _resolve_person(conn, item.assignee, None if lead else inc.user_name)
            same = max(asked, key=lambda t: match_score(t["title"], item.title), default=None)
            if same is not None and match_score(same["title"], item.title) >= 0.6:
                # Vazifa xabariga "mayli olaman, seshanbagacha bitkazaman": o'sha ishni qabul qilish, yangi vazifa emas
                result.changed += conn.execute(
                    "UPDATE tasks SET assignee = ?, deadline = COALESCE(?, deadline), "
                    "status = CASE WHEN status = 'taklif' AND ? = ? THEN 'open' ELSE status END WHERE id = ?",
                    (who, item.deadline.isoformat() if item.deadline else None, who, inc.user_name, same["id"])).rowcount
                continue
            status = "taklif" if strict and who != inc.user_name else "open"
            cur = conn.execute(
                "INSERT INTO tasks(project_id, title, assignee, status, created_at, created_msg, deadline) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (pid, item.title, who, status, when, mid, item.deadline.isoformat() if item.deadline else None),
            )
            (result.proposed if status == "taklif" else result.task_ids).append(cur.lastrowid)
            result.created += 1

    elif parsed.kind == "done":
        remaining = list(parsed.items)
        # eski hisobot forward qilingan bo'lsa ish o'sha kunga yoziladi (bugungi ish bo'lib sanalmaydi)
        done_at = "%s 18:00:00" % parsed.day.isoformat() if parsed.day and parsed.day < inc.date.date() else when
        refs = _sure_refs(conn, parsed, parent, inc)
        if parent is not None and parent["kind"] == "blocker":
            bids = [r["id"] for r in conn.execute("SELECT id FROM blockers WHERE msg = ? AND resolved_at IS NULL", (parent["id"],))]
            for bid in bids:
                conn.execute("UPDATE blockers SET resolved_at = ?, resolved_msg = ? WHERE id = ?", (when, mid, bid))
                result.closed += 1 + _close_related(conn, bid, inc.user_name, when, mid)
            if parent["user_id"] == inc.user_id:
                remaining = []  # o'z muammosi hal bo'ldi ("ruxsat berishdi"): bu ish emas; boshqaning muammosini hal qilish esa ish
        if refs:
            # AI aniq qaysi vazifalar bajarilganini kontekstdan topdi
            for tid in refs:
                cur = conn.execute("UPDATE tasks SET status = 'done', done_at = ?, done_msg = ? WHERE id = ? AND status = 'open'",
                                   (done_at, mid, tid))
                result.closed += cur.rowcount
            remaining = []
        elif parent is not None and parent["kind"] == "task":
            open_tasks = conn.execute(
                "SELECT id, title, assignee FROM tasks WHERE created_msg = ? AND status = 'open'", (parent["id"],)
            ).fetchall()
            if remaining:
                for item in list(remaining):
                    scored = sorted(((match_score(t["title"], item.title), t) for t in open_tasks), key=lambda x: -x[0])
                    if scored and scored[0][0] >= 0.5:
                        _close(conn, scored[0][1]["id"], done_at, mid)
                        open_tasks = [t for t in open_tasks if t["id"] != scored[0][1]["id"]]
                        remaining.remove(item)
                        result.closed += 1
            else:
                mine = [t for t in open_tasks if t["assignee"] == inc.user_name] or open_tasks
                for t in mine:
                    _close(conn, t["id"], done_at, mid)
                    result.closed += 1
        if pid:
            for item in remaining:
                same = conn.execute("SELECT id, assignee FROM tasks WHERE id = ? AND status = 'done'",
                                    (item.same_as,)).fetchone() if item.same_as else None
                if same is not None and same["assignee"] == _resolve_person(conn, item.assignee, inc.user_name):
                    continue  # kun ichida yozilgan ish kechki hisobotda yana aytildi: bir marta sanaladi
                candidates = conn.execute(
                    "SELECT id, title, assignee FROM tasks WHERE project_id = ? AND status = 'open' AND created_at <= ?",
                    (pid, when),
                ).fetchall()
                best, best_score = None, 0.0
                for t in candidates:
                    score = match_score(t["title"], item.title) + (0.1 if t["assignee"] == inc.user_name else 0)
                    if score > best_score:
                        best, best_score = t, score
                if best is not None and best_score >= 0.6:
                    _close(conn, best["id"], done_at, mid)
                else:
                    # Oldin vazifa sifatida yozilmagan ish: darhol bajarilgan vazifa bo'lib qo'shiladi.
                    # Hamkasb bugun yozgan ishga o'xshasa, dup_of — hakam uchun ishora (o'ziniki qilib yozdimi, fon tekshiradi)
                    conn.execute(
                        "INSERT INTO tasks(project_id, title, assignee, status, created_at, done_at, created_msg, done_msg, dup_of) "
                        "VALUES(?, ?, ?, 'done', ?, ?, ?, ?, ?)",
                        (pid, item.title, _resolve_person(conn, item.assignee, inc.user_name), done_at, done_at, mid, mid,
                         same["id"] if same is not None else None),
                    )
                result.closed += 1

    elif parsed.kind in ("blocker", "request") and pid:
        # muammo — muallifning o'z ishini to'xtatgan narsa; murojaat — guruhga tushgan xato yoki "to'g'rilab bering" so'rovi
        texts = [i.title for i in parsed.items] or [inc.text.strip()[:160]]
        for text in texts:
            conn.execute(
                "INSERT INTO blockers(project_id, text, author, created_at, msg, kind) VALUES(?, ?, ?, ?, ?, ?)",
                (pid, text, inc.user_name, when, mid, "murojaat" if parsed.kind == "request" else "muammo"),
            )
            result.created += 1

    elif parsed.kind == "deadline" and parsed.deadline:
        # Muddat kimga: AI topgan vazifalar -> javob berilgan vazifa xabari -> butun loyiha
        targets = list(parsed.refs)
        if not targets and parent is not None and parent["kind"] == "task":
            targets = [r["id"] for r in conn.execute(
                "SELECT id FROM tasks WHERE created_msg = ? AND status IN ('open', 'taklif')", (parent["id"],))]
        if targets:
            for tid in targets:
                result.changed += conn.execute("UPDATE tasks SET deadline = ? WHERE id = ? AND status != 'done'",
                                               (parsed.deadline.isoformat(), tid)).rowcount
        elif pid:
            conn.execute("UPDATE projects SET deadline = ? WHERE id = ?", (parsed.deadline.isoformat(), pid))
            result.changed += 1

    elif parsed.kind == "reassign" and parsed.refs and parsed.items:
        who = _resolve_person(conn, parsed.items[0].assignee, inc.user_name)
        due = parsed.items[0].deadline or parsed.deadline  # "mayli olaman, seshanbagacha bitkazaman": ish ham, muddat ham
        for tid in parsed.refs:
            result.changed += conn.execute("UPDATE tasks SET assignee = ?, deadline = COALESCE(?, deadline) WHERE id = ? AND status = 'open'",
                                           (who, due.isoformat() if due else None, tid)).rowcount

    if parsed.kind == "done" or parsed.sections.get("done"):
        result.repeats = mark_repeats(conn, mid, inc.user_name)
    conn.execute("UPDATE messages SET items = ? WHERE id = ?", (result.created + result.closed + result.changed, mid))
    db.bump_version(conn)
    return result


def _report(conn: sqlite3.Connection, parsed: Parsed, pid: int, inc: Incoming, when: str, mid: int, result: Result) -> None:
    """Bo'limli kunlik hisobot. Bajarilganlar: ochiq vazifa bo'lsa yopiladi, bo'lmasa bajarilgan ish bo'lib yoziladi.
    Jarayonda va reja: yozgan xodimning ochiq vazifalari (har kuni takrorlansa ham bitta bo'lib qoladi). Muammo: muammo."""
    done_at = when
    if parsed.day is not None and parsed.day < inc.date.date():
        done_at = "%s 18:00:00" % parsed.day.isoformat()  # kechagi hisobot ertalab yozilgan: ish o'sha kunga yoziladi
    done_items = parsed.sections.get("done", [])
    ongoing = [i for i in done_items if ONGOING_RE.search(i.title)]
    if ongoing:  # "o'rganib chiqilmoqda", "yechim qilish jarayonida": bajarilgan emas, jarayondagi ish
        parsed.sections = {**parsed.sections, "done": [i for i in done_items if i not in ongoing],
                           "doing": parsed.sections.get("doing", []) + ongoing}
    for item in parsed.sections.get("done", []):
        open_tasks = conn.execute("SELECT id, title, assignee FROM tasks WHERE project_id = ? AND status = 'open' AND created_at <= ?",
                                  (pid, when)).fetchall()
        best, best_score = None, 0.0
        for t in open_tasks:
            score = match_score(t["title"], item.title) + (0.1 if t["assignee"] == inc.user_name else 0)
            if score > best_score:
                best, best_score = t, score
        if best is not None and best_score >= 0.6:
            _close(conn, best["id"], done_at, mid)
        else:
            conn.execute("INSERT INTO tasks(project_id, title, assignee, status, created_at, done_at, created_msg, done_msg, note) "
                         "VALUES(?, ?, ?, 'done', ?, ?, ?, ?, ?)",
                         (pid, item.title, inc.user_name, done_at, done_at, mid, mid, item.note))
        result.closed += 1
    # "Ertangi reja" keyingi ish kuni uchun: o'sha kuni bajarildimi — panelda "reja bajarilishi"
    plan_day = next_workday(parsed.day or inc.date.date()).isoformat()
    for section, stage in (("doing", "jarayon"), ("plan", None)):
        for item in parsed.sections.get(section, []):
            who = _resolve_person(conn, item.assignee, inc.user_name)
            mine = conn.execute("SELECT id, title, created_msg FROM tasks WHERE project_id = ? AND assignee = ? AND status = 'open'",
                                (pid, who)).fetchall()
            same = max(mine, key=lambda t: match_score(t["title"], item.title) + (0.35 if t["created_msg"] == mid else 0), default=None)
            score = match_score(same["title"], item.title) if same is not None else 0
            # shu hisobotning o'zida "Jarayonda" bandi bilan bir xil ish "Ertangi reja"da ham yozilsa — bitta vazifa
            if same is not None and (score >= 0.8 or (section == "plan" and same["created_msg"] == mid and score >= 0.45)):
                if stage:
                    conn.execute("UPDATE tasks SET stage = ?, accepted_at = COALESCE(accepted_at, ?) WHERE id = ? AND "
                                 "(stage IS NULL OR stage IN ('yangi', 'qabul'))", (stage, when, same["id"]))
                if item.progress is not None:
                    conn.execute("UPDATE tasks SET progress = ? WHERE id = ?", (item.progress, same["id"]))
                if section == "plan":
                    conn.execute("UPDATE tasks SET plan_day = ? WHERE id = ?", (plan_day, same["id"]))
                continue
            cur = conn.execute("INSERT INTO tasks(project_id, title, assignee, status, created_at, created_msg, note, stage, accepted_at, "
                               "progress, plan_day) VALUES(?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)",
                               (pid, item.title, who, when, mid, item.note, stage, when if stage else None, item.progress,
                                plan_day if section == "plan" else None))
            result.task_ids.append(cur.lastrowid)
            result.created += 1
    for item in parsed.sections.get("blocker", []):
        conn.execute("INSERT INTO blockers(project_id, text, author, created_at, msg, kind) VALUES(?, ?, ?, ?, ?, 'muammo')",
                     (pid, item.title + (". " + item.note if item.note else ""), inc.user_name, when, mid))
        result.created += 1


def next_workday(d):
    """Keyingi ish kuni (dushanba-juma): juma kungi "ertangi reja" dushanba uchun."""
    d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def mark_repeats(conn: sqlite3.Connection, mid: int, author: str, recheck: bool = False) -> list[tuple[str, str]]:
    """Xabar kelishi bilan: shu xabarda bajarildi deb yozilgan ish aynan shu xodimda oldin ham (boshqa xabarda,
    bugun yoki bir yil oldin) yozilgan bo'lsa, u takror deb belgilanadi va reytingda hisobga olinmaydi.
    Aynan shu uzun band oxirgi 30 kunda BOSHQA xodimning hisobotida bo'lsa — nusxa (ko'chirilgan yoki forward qilingan
    hisobot): ish ikki marta sanalmaydi. So'zlari o'zgartirilgan takrorni fon ishchisi ma'no bo'yicha topadi (quality.check_repeats).
    recheck=True: hakam "davomi"/"boshqa" degan ishlar ham qayta tekshiriladi (bir martalik tuzatish uchun)."""
    from .quality import norm
    free = "(t.dup_kind IS NULL OR t.dup_kind IN ('davomi', 'boshqa'))" if recheck else "t.dup_kind IS NULL"
    new = conn.execute("SELECT t.id, t.title, coalesce(m.date, t.done_at) AS at FROM tasks t LEFT JOIN messages m ON m.id = t.done_msg "
                       "WHERE t.done_msg = ? AND t.status = 'done' AND t.assignee = ? AND " + free, (mid, author)).fetchall()
    if not new:
        return []
    copies = _mark_copies(conn, mid, author, new, norm)
    taken = {x[2] for x in copies}
    out = [x[:2] for x in copies]
    new = [t for t in new if t["id"] not in taken]
    if not new:
        return out
    since = (config.now() - timedelta(days=400)).strftime(FMT)
    seen: dict[str, dict] = {}
    for r in conn.execute("SELECT t.id, t.title, t.done_at, m.date AS msg_date FROM tasks t LEFT JOIN messages m ON m.id = t.done_msg "
                          "WHERE t.assignee = ? AND t.status = 'done' AND t.done_at >= ? AND (t.done_msg IS NULL OR t.done_msg != ?) "
                          "AND t.dup_kind IS NULL ORDER BY t.id", (author, since, mid)):
        seen.setdefault(norm(r["title"]), dict(r))
    stamp = config.now().strftime(FMT)
    for t in new:
        old = seen.get(norm(t["title"]))
        if old is None or (old["msg_date"] or old["done_at"]) > t["at"]:
            continue  # faqat oldin yozilgani bilan solishtiriladi
        when = old["msg_date"] or old["done_at"]
        note = "Aynan shu ish %s dagi hisobotda ham yozilgan" % when[:16]
        conn.execute("UPDATE tasks SET dup_of = ?, dup_score = 1.0, dup_kind = 'takror', dup_note = ?, dup_at = ? WHERE id = ?",
                     (old["id"], note, stamp, t["id"]))
        out.append((t["title"], when))
    return out


def _mark_copies(conn: sqlite3.Connection, mid: int, author: str, new, norm) -> list[tuple[str, str, int]]:
    """Boshqa xodimning oxirgi 30 kundagi hisobotida aynan shu uzun band (kamida 3 so'z, 20 harf) bor: nusxa.
    Qisqa umumiy bandlar ("push qilish", "review") tasodifan bir xil bo'lishi mumkin — ular solishtirilmaydi."""
    keys = {t["id"]: norm(t["title"]) for t in new}
    keys = {k: v for k, v in keys.items() if len(v) >= 20 and len(v.split()) >= 3}
    if not keys:
        return []
    since = (config.now() - timedelta(days=30)).strftime(FMT)
    first_by: dict[str, dict] = {}
    for r in conn.execute("SELECT t.id, t.title, t.assignee, t.done_at, coalesce(m.date, t.done_at) AS at, c.title AS chat FROM tasks t "
                          "LEFT JOIN messages m ON m.id = t.done_msg LEFT JOIN chats c ON c.id = m.chat_id "
                          "WHERE t.status = 'done' AND t.assignee IS NOT NULL AND t.assignee != ? AND t.done_at >= ? "
                          "AND (t.done_msg IS NULL OR t.done_msg != ?) AND (t.dup_kind IS NULL OR t.dup_kind NOT IN ('takror', 'nusxa')) "
                          "ORDER BY coalesce(m.date, t.done_at), t.id", (author, since, mid)):
        first_by.setdefault(norm(r["title"]), dict(r))
    out, stamp = [], config.now().strftime(FMT)
    for t in new:
        old = first_by.get(keys.get(t["id"], ""))
        if old is None or old["at"] > t["at"]:
            continue
        note = "Aynan shu ish %sning %s dagi hisobotida yozilgan%s" % (old["assignee"], old["at"][:16], ", " + old["chat"] if old["chat"] else "")
        conn.execute("UPDATE tasks SET dup_of = ?, dup_score = 1.0, dup_kind = 'nusxa', dup_note = ?, dup_at = ? WHERE id = ?",
                     (old["id"], note, stamp, t["id"]))
        out.append((t["title"], old["at"], t["id"]))
    return out


def _close_related(conn: sqlite3.Connection, bid: int, who: str, done_at: str, mid: int) -> int:
    """Muammo hal bo'ldi: hal qilgan xodimning shu muammoga oid ochiq vazifasi ("arizalarni tekshirib beraman") ham yopiladi,
    aks holda u ochiq vazifalar ro'yxatida osilib qoladi."""
    b = conn.execute("SELECT text, project_id FROM blockers WHERE id = ?", (bid,)).fetchone()
    if b is None or not who:
        return 0
    n = 0
    for t in conn.execute("SELECT id, title FROM tasks WHERE assignee = ? AND project_id = ? AND status = 'open' AND created_at <= ?",
                          (who, b["project_id"], done_at)).fetchall():
        if len(stems(t["title"]) & stems(b["text"] or "")) >= 2 or match_score(t["title"], b["text"] or "") >= 0.6:
            _close(conn, t["id"], done_at, mid)
            n += 1
    return n


def backfill_audit(conn: sqlite3.Connection) -> dict:
    """Bir martalik tuzatish (25.10 tekshiruvi): eski kod bilan kirgan xabarlarda —
    1) forward qilingan kechagi hisobotning "hisobot kuni" ishlar yozilgan kunga to'g'rilanadi;
    2) "Bajarildi" ostiga yozilgan, lekin davom etayotgan ishlar jarayonga qaytariladi;
    3) hal bo'lgan muammo bo'yicha hal qilgan xodimning ochiq vazifasi yopiladi;
    4) boshqa xodim hisobotidan aynan ko'chirilgan bandlar "nusxa" deb belgilanadi (ikki marta sanalmaydi)."""
    key = "backfill:audit:1"
    if conn.execute("SELECT 1 FROM meta WHERE key = ?", (key,)).fetchone():
        return {}
    st = {"kun": 0, "jarayon": 0, "yopildi": 0, "nusxa": 0}
    for m in conn.execute("SELECT m.id, m.report_day, (SELECT min(substr(t.done_at, 1, 10)) FROM tasks t WHERE t.done_msg = m.id) AS d "
                          "FROM messages m WHERE m.report_day IS NOT NULL").fetchall():
        if m["d"] and m["d"] < m["report_day"]:
            conn.execute("UPDATE messages SET report_day = ? WHERE id = ?", (m["d"], m["id"]))
            st["kun"] += 1
    for t in conn.execute("SELECT id, title, created_at FROM tasks WHERE status = 'done' AND created_msg = done_msg").fetchall():
        if ONGOING_RE.search(t["title"]):
            conn.execute("UPDATE tasks SET status = 'open', stage = 'jarayon', accepted_at = created_at, done_at = NULL, done_msg = NULL "
                         "WHERE id = ?", (t["id"],))
            st["jarayon"] += 1
    for b in conn.execute("SELECT b.id, b.resolved_at, b.resolved_msg, pe.name FROM blockers b JOIN messages m ON m.id = b.resolved_msg "
                          "JOIN people pe ON pe.id = m.user_id WHERE b.resolved_at IS NOT NULL").fetchall():
        st["yopildi"] += _close_related(conn, b["id"], b["name"], b["resolved_at"], b["resolved_msg"])
    for r in conn.execute("SELECT DISTINCT t.done_msg AS mid, t.assignee FROM tasks t WHERE t.status = 'done' AND t.done_msg IS NOT NULL "
                          "AND t.assignee IS NOT NULL ORDER BY t.done_msg").fetchall():
        st["nusxa"] += len(mark_repeats(conn, r["mid"], r["assignee"], recheck=True))
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(st)))
    db.bump_version(conn)
    return st


def welcome_back(person_id: int, days: int = 30) -> int:
    """Xodim ulangach (havola orqali yoki admin "Xodim qilish" degach) uning oldin saqlangan, lekin qabul qilinmagan xabarlari
    qayta o'qiladi: ulanishdan oldin yozgan hisobotlari ham hisobga kiradi. Qayta o'qilgan xabarlar soni qaytadi."""
    since = (config.now() - timedelta(days=days)).strftime(FMT)
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT m.chat_id, m.msg_id, m.user_id, m.date, m.text, m.reply_to, c.title, c.demo, COALESCE(pe.tg_name, pe.name) AS name, "
            "pe.username FROM messages m "
            "JOIN people pe ON pe.id = m.user_id LEFT JOIN chats c ON c.id = m.chat_id "
            "WHERE m.user_id = ? AND m.source = 'ulanmagan' AND m.date >= ? ORDER BY m.date", (person_id, since))]
    n = 0
    for r in rows:
        inc = Incoming(r["chat_id"], r["title"] or "", r["msg_id"], r["user_id"], r["name"] or "", r["username"],
                       datetime.strptime(r["date"], FMT), r["text"] or "", r["reply_to"], edited=True, demo=bool(r["demo"]))
        n += 0 if process(inc).skipped else 1
    return n


def deleted(conn: sqlite3.Connection, chat_id: int | None, msg_ids: list[int]) -> int:
    """Telegramda xabar o'chirildi (faqat akkaunt orqali ulanganda ma'lum bo'ladi). Vazifalar o'chmaydi, lekin
    rahbar hisobot o'chirilganini ko'radi va u reytingda hisobga olinmaydi. chat_id yo'q bo'lsa (oddiy guruh) msg_id bo'yicha."""
    stamp = config.now().strftime(FMT)
    n = 0
    for msg_id in msg_ids:
        sql, args = "SELECT id, text FROM messages WHERE msg_id = ? AND deleted_at IS NULL", [msg_id]
        if chat_id is not None:
            sql += " AND chat_id = ?"; args.append(chat_id)
        for m in conn.execute(sql, args).fetchall():
            conn.execute("INSERT INTO message_edits(message_id, at, kind, old_text) VALUES(?, ?, 'delete', ?)", (m["id"], stamp, m["text"]))
            conn.execute("UPDATE messages SET deleted_at = ? WHERE id = ?", (stamp, m["id"]))
            n += 1
    if n:
        db.bump_version(conn)
    return n


def process(inc: Incoming, use_ai: bool = True) -> Result:
    """Bot uchun: o'z ulanishini ochadi va saqlaydi."""
    with db.session() as conn:
        return ingest(conn, inc, use_ai)
