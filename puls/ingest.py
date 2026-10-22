"""Xabarni qabul qilish: tushunish -> bazaga yozish -> vazifalarni ochish yoki yopish.

Bot ham, tarixni import qilish ham, namuna ma'lumot ham shu bitta yo'ldan o'tadi.
"""
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from . import ai, db, memory, settings
from .parser import MENTION_RE, Parsed, detect_project, match_score, norm_key, parse_format, parse_free, words

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
        "SELECT pe.name, pe.username, max(m.chat_id = ?) AS here FROM people pe LEFT JOIN messages m ON m.user_id = pe.id "
        "WHERE pe.username IS NOT NULL GROUP BY pe.id ORDER BY here DESC, pe.name LIMIT 150", (inc.chat_id,))]
    return {"team": team, "tasks": tasks, "reply": reply}


def understand(conn: sqlite3.Connection, inc: Incoming, use_ai: bool) -> Parsed:
    """Faqat o'qiydi, bazaga yozmaydi (AI javobini kutayotganda baza band bo'lmasin)."""
    today = inc.date.date()
    parsed = parse_format(inc.text, today)
    if parsed is not None:
        return parsed
    projects = load_projects(conn)
    if use_ai:
        parsed = ai.extract(inc.text, inc.user_name, projects, today, context=context(conn, inc))
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


def ingest(conn: sqlite3.Connection, inc: Incoming, use_ai: bool = True, pre: Parsed | None = None) -> Result:
    """pre: oldindan tayyorlangan natija (masalan, namuna ma'lumotda AI parallel chaqirilganda)."""
    existing = conn.execute(
        "SELECT id FROM messages WHERE chat_id = ? AND msg_id = ?", (inc.chat_id, inc.msg_id)
    ).fetchone()
    if existing and not inc.edited:
        return Result("none", "format", duplicate=True)

    if inc.media and use_ai and pre is None:
        heard = ai.transcribe(inc.media, inc.mime or "application/octet-stream", inc.text)
        if heard:
            label = "Rasm" if (inc.mime or "").startswith("image/") else "Ovozli xabar"
            inc.text = "%s: %s%s" % (label, heard, "\n" + inc.text if inc.text and inc.text not in heard else "")
    parsed = pre or understand(conn, inc, use_ai)
    if parsed.source == "ai" and parsed.project is None and parsed.kind in ("task", "done", "blocker"):
        # AI loyihani aniqlamasa ("Bulutda ... yakunlandi"), nomi bo'yicha qidiruv yordam beradi
        parsed.project = detect_project(inc.text, load_projects(conn))
    when = inc.date.strftime(FMT)

    conn.execute(
        "INSERT INTO chats(id, title, demo, added_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET title = excluded.title",
        (inc.chat_id, inc.chat_title, int(inc.demo), when),
    )
    # Ism: rahbar panelda yozgan ism-familiya ustun; bo'lmasa Telegram nomi (bezaklarsiz). Nom o'zgarsa, eski vazifalar ham ergashadi
    row = conn.execute("SELECT name, name_locked FROM people WHERE id = ?", (inc.user_id,)).fetchone()
    name = row["name"] if row and row["name_locked"] else clean_name(inc.user_name)
    if row is None:
        conn.execute("INSERT INTO people(id, name, username) VALUES(?, ?, ?)", (inc.user_id, name, inc.username))
    else:
        db.rename_person(conn, row["name"], name)
        conn.execute("UPDATE people SET username = ? WHERE id = ?", (inc.username, inc.user_id))
    inc.user_name = name

    # Loyihani aniqlash: aniq teg -> javob berilgan xabarning loyihasi -> guruhda yagona loyiha
    project = None
    if parsed.project:
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
    pid = project["id"] if project else None

    if existing:
        mid = existing["id"]
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

    result = Result(parsed.kind, parsed.source, project["name"] if project else None)
    if parsed.kind in ("task", "done", "blocker") and pid is None:
        result.missing_project = True

    if parsed.kind == "task" and pid:
        # "Faqat rahbarlar" sozlamasida oddiy xodim boshqaga yozgan vazifa o'sha xodim qabul qilguncha taklif bo'lib turadi
        strict = not inc.lead and settings.load(conn)["assign_policy"] == "rahbar"
        for item in parsed.items:
            who = _resolve_person(conn, item.assignee, inc.user_name)
            status = "taklif" if strict and who != inc.user_name else "open"
            cur = conn.execute(
                "INSERT INTO tasks(project_id, title, assignee, status, created_at, created_msg, deadline) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (pid, item.title, who, status, when, mid, item.deadline.isoformat() if item.deadline else None),
            )
            (result.proposed if status == "taklif" else result.task_ids).append(cur.lastrowid)
            result.created += 1

    elif parsed.kind == "done" and parsed.refs:
        # AI aniq qaysi vazifalar bajarilganini kontekstdan topdi
        for tid in parsed.refs:
            cur = conn.execute("UPDATE tasks SET status = 'done', done_at = ?, done_msg = ? WHERE id = ? AND status = 'open'",
                               (when, mid, tid))
            result.closed += cur.rowcount

    elif parsed.kind == "done":
        remaining = list(parsed.items)
        if parent is not None and parent["kind"] == "blocker":
            cur = conn.execute(
                "UPDATE blockers SET resolved_at = ?, resolved_msg = ? WHERE msg = ? AND resolved_at IS NULL",
                (when, mid, parent["id"]),
            )
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
                        _close(conn, scored[0][1]["id"], when, mid)
                        open_tasks = [t for t in open_tasks if t["id"] != scored[0][1]["id"]]
                        remaining.remove(item)
                        result.closed += 1
            else:
                mine = [t for t in open_tasks if t["assignee"] == inc.user_name] or open_tasks
                for t in mine:
                    _close(conn, t["id"], when, mid)
                    result.closed += 1
        if pid:
            for item in remaining:
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
                    _close(conn, best["id"], when, mid)
                else:
                    # Oldin vazifa sifatida yozilmagan ish: darhol bajarilgan vazifa bo'lib qo'shiladi
                    conn.execute(
                        "INSERT INTO tasks(project_id, title, assignee, status, created_at, done_at, created_msg, done_msg) "
                        "VALUES(?, ?, ?, 'done', ?, ?, ?, ?)",
                        (pid, item.title, _resolve_person(conn, item.assignee, inc.user_name), when, when, mid, mid),
                    )
                result.closed += 1

    elif parsed.kind == "blocker" and pid:
        texts = [i.title for i in parsed.items] or [inc.text.strip()[:160]]
        for text in texts:
            conn.execute(
                "INSERT INTO blockers(project_id, text, author, created_at, msg) VALUES(?, ?, ?, ?, ?)",
                (pid, text, inc.user_name, when, mid),
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
        for tid in parsed.refs:
            result.changed += conn.execute("UPDATE tasks SET assignee = ? WHERE id = ? AND status = 'open'",
                                           (who, tid)).rowcount

    conn.execute("UPDATE messages SET items = ? WHERE id = ?", (result.created + result.closed + result.changed, mid))
    db.bump_version(conn)
    return result


def process(inc: Incoming, use_ai: bool = True) -> Result:
    """Bot uchun: o'z ulanishini ochadi va saqlaydi."""
    with db.session() as conn:
        return ingest(conn, inc, use_ai)
