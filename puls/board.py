"""Menejer doskasi: vazifa yozish, xodimga berish, ustunlar bo'yicha kuzatish.

Doskadagi kartochka = oddiy vazifa (tasks jadvali). Guruhdan yozilgan vazifalar ham shu yerda ko'rinadi.
Menejer vazifa bersa, bot ijrochiga guruhda tugmali xabar yuboradi. Xodim tugma bosadi yoki
o'sha xabarga javob yozadi ("tushundim", "50%", "bajardim", "API tayyor emas") va kartochka o'zi yangilanadi.
Har o'zgarish kartochka tarixiga (task_events) yoziladi; menejer izohi guruhga ham boradi.
"""
import re
import sqlite3
from datetime import date, datetime, timedelta

from . import analytics, config, db
from .parser import BLOCKER_RE, DONE_RE

FMT = "%Y-%m-%d %H:%M:%S"
STAGES = [("yangi", "Yangi"), ("qabul", "Qabul qilindi"), ("jarayon", "Jarayonda"), ("tekshiruv", "Tekshiruvda"),
          ("bajarildi", "Bajarildi")]
STAGE_KEYS = [k for k, _ in STAGES]
STAGE_NAME = dict(STAGES)
DONE_DAYS = 7          # "Bajarildi" ustunida oxirgi necha kunlik ishlar turadi
WAIT_HOURS = 4         # shuncha vaqtda "Tushundim" kelmasa, kartochkada "Javob yo'q" belgisi va bot eslatmasi
WORK_FROM, WORK_TO = 9, 18  # eslatmalar faqat ish vaqtida

ACCEPT_RE = re.compile(r"tushundim|tushunarli|qabul qildim|qabul|xo'p|xop|bo'ldi|ok\b|okey|hop\b|понял|принял", re.I)
QUESTION_RE = re.compile(r"tushunmadim|savol|qanday qilib|aniqlashtir|\?|не понял|вопрос", re.I)
PCT_RE = re.compile(r"(\d{1,3})\s*(?:%|foiz|процент)", re.I)


def now() -> datetime:
    return config.now()


def stage_of(t) -> str:
    if t["status"] == "done":
        return "bajarildi"
    return t["stage"] if t["stage"] in STAGE_KEYS[:-1] else "yangi"


def _person(conn: sqlite3.Connection, name: str | None):
    return conn.execute("SELECT * FROM people WHERE name = ?", (name,)).fetchone() if name else None


def _task(conn: sqlite3.Connection, task_id: int):
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if t is None:
        raise ValueError("Vazifa topilmadi")
    return t


def mention(conn: sqlite3.Connection, name: str | None) -> str:
    p = _person(conn, name)
    return "@" + p["username"] if p and p["username"] else (name or "—")


def log(conn: sqlite3.Connection, task_id: int, who: str | None, kind: str, text: str = "", msg: int | None = None) -> None:
    conn.execute("INSERT INTO task_events(task_id, at, who, kind, text, msg) VALUES(?, ?, ?, ?, ?, ?)",
                 (task_id, now().strftime(FMT), who, kind, (text or "")[:1000], msg))


def who_name(conn: sqlite3.Connection, user_id: int | None, fallback: str | None) -> str | None:
    """Tarixda xodim panelda yozilgan ism-familiyasi bilan ko'rinsin."""
    r = conn.execute("SELECT name FROM people WHERE id = ?", (user_id,)).fetchone() if user_id else None
    return r["name"] if r else fallback


def manager(conn: sqlite3.Connection) -> str:
    r = conn.execute("SELECT name FROM people WHERE id = ?", (config.OWNER_ID,)).fetchone() if config.OWNER_ID else None
    return r["name"] if r else "Rahbar"


def card(t, today: date, people: dict, extra: dict | None = None) -> dict:
    t = dict(t)
    st = stage_of(t)
    who = people.get(t["assignee"]) or {}
    created = datetime.strptime(t["created_at"], FMT)
    waiting = (st == "yangi" and t.get("tg_msg") and not t.get("accepted_at")
               and (now() - created).total_seconds() > WAIT_HOURS * 3600)
    ex = extra or {}
    return {
        "id": t["id"], "title": t["title"], "stage": st, "progress": 100 if st == "bajarildi" else (t.get("progress") or 0),
        "project": t["project"], "project_id": t["project_id"], "assignee": t["assignee"],
        "department": who.get("department"), "username": who.get("username"),
        "priority": t.get("priority"), "note": t.get("note"), "flag": t.get("flag"), "flag_text": t.get("flag_text"),
        "created_at": t["created_at"], "done_at": t.get("done_at"), "accepted_at": t.get("accepted_at"),
        "age": (today - created.date()).days, "giver": t.get("created_by") or t.get("giver"),
        "sent": bool(t.get("tg_msg")), "waiting": bool(waiting), "manual": t.get("created_msg") is None,
        "checks": ex.get("checks", [0, 0]), "comments": ex.get("comments", 0), **analytics._due(t, today),
        "grp": t.get("grp"), "grp_size": ex.get("grp", [0, 0])[1], "grp_done": ex.get("grp", [0, 0])[0],
    }


def _extras(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {i: {} for i in ids}
    if not ids:
        return out
    for i in range(0, len(ids), 900):
        part = ids[i:i + 900]
        marks = ",".join("?" * len(part))
        for r in conn.execute(f"SELECT task_id, sum(done) d, count(*) n FROM task_checks WHERE task_id IN ({marks}) GROUP BY task_id", part):
            out[r["task_id"]]["checks"] = [r["d"], r["n"]]
        for r in conn.execute(f"SELECT task_id, count(*) n FROM task_events WHERE kind IN ('comment', 'telegram') AND task_id IN ({marks}) "
                              "GROUP BY task_id", part):
            out[r["task_id"]]["comments"] = r["n"]
        grps = {r["id"]: r["grp"] for r in conn.execute(f"SELECT id, grp FROM tasks WHERE grp IS NOT NULL AND id IN ({marks})", part)}
        if grps:
            gm = ",".join("?" * len(set(grps.values())))
            sizes = {r["grp"]: (r["d"], r["n"]) for r in conn.execute(
                f"SELECT grp, sum(CASE WHEN status = 'done' THEN 1 ELSE 0 END) d, count(*) n FROM tasks WHERE grp IN ({gm}) GROUP BY grp",
                list(set(grps.values())))}
            for tid, g in grps.items():
                out[tid]["grp"] = list(sizes.get(g, (0, 0)))
    return out


BASE_SQL = ("SELECT t.*, p.name AS project, pe.name AS giver FROM tasks t JOIN projects p ON p.id = t.project_id "
            "LEFT JOIN messages m ON m.id = t.created_msg LEFT JOIN people pe ON pe.id = m.user_id ")


def board(conn: sqlite3.Connection, project_id: int | None = None, department: str | None = None, q: str = "",
          scope: set[int] | None = None) -> dict:
    today = now().date()
    since = (today - timedelta(days=DONE_DAYS)).isoformat()
    people = {r["name"]: dict(r) for r in conn.execute("SELECT name, username, department FROM people")}
    sql = BASE_SQL + "WHERE t.status != 'taklif' AND (t.status = 'open' OR t.done_at >= ?)"
    args: list = [since]
    if project_id:
        sql += " AND t.project_id = ?"; args.append(project_id)
    if scope is not None:  # loyiha menejeri faqat o'z loyihalarini ko'radi
        sql += " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
    raw = conn.execute(sql + " ORDER BY t.id DESC", args).fetchall()
    ex = _extras(conn, [r["id"] for r in raw])
    rows = [card(r, today, people, ex.get(r["id"])) for r in raw]
    if department:
        rows = [c for c in rows if (c["department"] or "Belgilanmagan") == department]
    if q:
        ql = q.lower()
        rows = [c for c in rows if ql in c["title"].lower() or ql in (c["assignee"] or "").lower() or ql in (c["project"] or "").lower()]
    order = {"yuqori": 0}
    rows.sort(key=lambda c: (order.get(c["priority"], 1), c["due_in"] if c["due_in"] is not None else 999, -c["id"]))
    cols = [{"key": k, "title": t, "count": sum(1 for c in rows if c["stage"] == k)} for k, t in STAGES]
    projects = [dict(r) for r in conn.execute(
        "SELECT p.id, p.name, c.demo FROM projects p LEFT JOIN chats c ON c.id = p.chat_id ORDER BY p.name")
        if scope is None or r["id"] in scope]
    return {"columns": cols, "cards": rows, "projects": projects, "today": today.isoformat(),
            "waiting": sum(1 for c in rows if c["waiting"]), "flags": sum(1 for c in rows if c["flag"] and c["stage"] != "bajarildi")}


def allowed(conn: sqlite3.Connection, task_id: int | None, scope: set[int] | None, project_id: int | None = None) -> None:
    """Menejer boshqa loyihaning vazifasiga tegolmaydi."""
    if scope is None:
        return
    if task_id is not None:
        r = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        project_id = r["project_id"] if r else None
    if project_id not in scope:
        raise PermissionError("Bu loyiha sizga biriktirilmagan")


def detail(conn: sqlite3.Connection, task_id: int) -> dict:
    """Kartochka oynasi uchun: kartochka, ichki ro'yxat va to'liq tarix."""
    r = conn.execute(BASE_SQL + "WHERE t.id = ?", (task_id,)).fetchone()
    if r is None:
        raise ValueError("Vazifa topilmadi")
    people = {x["name"]: dict(x) for x in conn.execute("SELECT name, username, department FROM people")}
    c = card(r, now().date(), people, _extras(conn, [task_id]).get(task_id))
    c["checklist"] = [dict(x) for x in conn.execute("SELECT id, text, done FROM task_checks WHERE task_id = ? ORDER BY pos, id", (task_id,))]
    c["events"] = [dict(x) for x in conn.execute("SELECT at, who, kind, text FROM task_events WHERE task_id = ? ORDER BY at DESC, id DESC",
                                                 (task_id,))]
    c["siblings"] = [s for s in siblings(conn, task_id) if s["id"] != task_id]
    return c


def candidates(conn: sqlite3.Connection, project_id: int | None = None) -> list[dict]:
    """Kimga berish mumkin: yuklamasi bilan. Tavsiya: shu loyihada ishlaganlar va bo'shroqlar birinchi."""
    data = analytics.compute(conn, "week")
    in_project = set()
    if project_id:
        in_project = {r["assignee"] for r in conn.execute("SELECT DISTINCT assignee FROM tasks WHERE project_id = ?", (project_id,))}
    out = []
    for p in data["people"]:
        out.append({"name": p["name"], "department": p["department"], "state": p["state"], "state_label": p["state_label"],
                    "open": p["open"], "score": p["score"], "username": p["username"], "in_project": p["name"] in in_project})
    load_rank = {"idle": 0, "ok": 1, "stuck": 2, "silent": 3, "overloaded": 4}
    out.sort(key=lambda p: (not p["in_project"], load_rank.get(p["state"], 2), p["open"]))
    for p in out[:3]:
        if p["state"] != "overloaded":
            p["suggest"] = True
    return out


def create_many(conn: sqlite3.Connection, title: str, project_id: int, assignees: list[str], deadline: str | None = None,
                priority: str | None = None, note: str | None = None, created_by: str | None = None,
                checklist: list[str] | None = None) -> list[int]:
    """Bitta vazifa bir nechta xodimga: har biri o'z qismini o'zi belgilaydi, doskada birga ko'rinadi (grp)."""
    people = list(dict.fromkeys(a for a in assignees if a))
    if len(people) <= 1:
        return [create(conn, title, project_id, people[0] if people else None, deadline, priority, note, created_by, checklist)]
    ids = []
    for who in people:
        tid = create(conn, title, project_id, who, deadline, priority, note, created_by, checklist, grp=ids[0] if ids else None)
        if not ids:
            conn.execute("UPDATE tasks SET grp = ? WHERE id = ?", (tid, tid))
        ids.append(tid)
    log(conn, ids[0], created_by, "edit", "Birgalikda: " + ", ".join(people))
    return ids


def siblings(conn: sqlite3.Connection, task_id: int) -> list[dict]:
    t = _task(conn, task_id)
    if not t["grp"]:
        return []
    return [{"id": r["id"], "assignee": r["assignee"], "stage": stage_of(r), "progress": 100 if r["status"] == "done" else (r["progress"] or 0)}
            for r in conn.execute("SELECT * FROM tasks WHERE grp = ? ORDER BY id", (t["grp"],))]


def create(conn: sqlite3.Connection, title: str, project_id: int, assignee: str | None, deadline: str | None = None,
           priority: str | None = None, note: str | None = None, created_by: str | None = None,
           checklist: list[str] | None = None, grp: int | None = None) -> int:
    title = " ".join((title or "").split())[:200]
    if len(title) < 3:
        raise ValueError("Vazifa nomini yozing")
    if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
        raise ValueError("Loyiha topilmadi")
    if assignee and not _person(conn, assignee):
        raise ValueError("Xodim topilmadi")
    if deadline:
        date.fromisoformat(deadline)
    cur = conn.execute(
        "INSERT INTO tasks(project_id, title, assignee, status, created_at, deadline, stage, progress, priority, note, created_by, grp) "
        "VALUES(?, ?, ?, 'open', ?, ?, 'yangi', 0, ?, ?, ?, ?)",
        (project_id, title, assignee, now().strftime(FMT), deadline or None, priority if priority == "yuqori" else None,
         (note or "").strip()[:1000] or None, created_by, grp))
    tid = cur.lastrowid
    for i, text in enumerate(x.strip() for x in (checklist or []) if x and x.strip()):
        conn.execute("INSERT INTO task_checks(task_id, text, pos) VALUES(?, ?, ?)", (tid, text[:200], i))
    log(conn, tid, created_by, "create", "Ijrochi: %s" % assignee if assignee else "Ijrochi tanlanmagan")
    db.bump_version(conn)
    return tid


def move(conn: sqlite3.Connection, task_id: int, stage: str, progress: int | None = None, who: str | None = None) -> None:
    if stage not in STAGE_KEYS:
        raise ValueError("Noma'lum ustun")
    t = _task(conn, task_id)
    ts = now().strftime(FMT)
    before = stage_of(t)
    if stage == "bajarildi":
        conn.execute("UPDATE tasks SET status = 'done', done_at = COALESCE(done_at, ?), stage = 'bajarildi', progress = 100, "
                     "flag = NULL WHERE id = ?", (ts, task_id))
    else:
        pr = progress if progress is not None else (t["progress"] or 0)
        if t["status"] == "done":
            pr = min(pr, 90)
        conn.execute("UPDATE tasks SET status = 'open', done_at = NULL, done_msg = NULL, stage = ?, progress = ?, "
                     "accepted_at = CASE WHEN ? != 'yangi' THEN COALESCE(accepted_at, ?) ELSE accepted_at END WHERE id = ?",
                     (stage, max(0, min(99, pr)), stage, ts, task_id))
    if before != stage:
        log(conn, task_id, who, "stage", STAGE_NAME[stage])
    elif progress is not None and progress != (t["progress"] or 0):
        log(conn, task_id, who, "stage", "%s, %d%%" % (STAGE_NAME[stage], progress))
    db.bump_version(conn)


def update(conn: sqlite3.Connection, task_id: int, who: str | None = None, **fields) -> None:
    allowed = {"title", "deadline", "priority", "note", "assignee", "progress", "flag"}
    t = _task(conn, task_id)
    sets, args, changed = [], [], []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k == "flag":  # panelda faqat yopiladi: "savol yoki to'siq hal bo'ldi"
            if t["flag"] and not v:
                sets += ["flag = NULL", "flag_text = NULL"]
                log(conn, task_id, who, "edit", ("Savol" if t["flag"] == "savol" else "To'siq") + " hal bo'ldi")
            continue
        if k == "title":
            v = " ".join(v.split())[:200]
            if len(v) < 3:
                raise ValueError("Vazifa nomini yozing")
        if k == "deadline":
            v = v or None
            if v:
                date.fromisoformat(v)
        if k == "priority":
            v = "yuqori" if v == "yuqori" else None
        if k == "note":
            v = v.strip()[:1000] or None
        if k == "assignee" and not _person(conn, v):
            raise ValueError("Xodim topilmadi")
        if k == "progress":
            continue  # alohida: ustun bilan birga o'zgaradi
        if t[k] != v:
            sets.append("%s = ?" % k)
            args.append(v)
            changed.append(k)
    if "assignee" in changed:  # yangi ijrochi qaytadan "Tushundim" deyishi kerak
        sets += ["stage = 'yangi'", "accepted_at = NULL", "flag = NULL", "flag_text = NULL", "tg_msg = NULL"]
        if t["status"] == "done":
            sets += ["status = 'open'", "done_at = NULL"]
    if sets:
        conn.execute("UPDATE tasks SET %s WHERE id = ?" % ", ".join(sets), args + [task_id])
        names = {"title": "nomi", "deadline": "muddati", "priority": "muhimligi", "note": "izohi"}
        if "assignee" in changed:
            log(conn, task_id, who, "assign", fields["assignee"])
        rest = [names[k] for k in changed if k in names]
        if rest:
            log(conn, task_id, who, "edit", "O'zgardi: " + ", ".join(rest))
    if fields.get("progress") is not None:
        p = int(fields["progress"])
        move(conn, task_id, "bajarildi" if p >= 100 else "jarayon", p, who)
    db.bump_version(conn)


def comment(conn: sqlite3.Connection, task_id: int, who: str | None, text: str) -> str:
    text = (text or "").strip()[:1000]
    if not text:
        raise ValueError("Izoh bo'sh")
    _task(conn, task_id)
    log(conn, task_id, who, "comment", text)
    db.bump_version(conn)
    return text


def remove(conn: sqlite3.Connection, task_id: int) -> tuple[int | None, int | None, str]:
    """Faqat doskadan yozilgan vazifa o'chadi (guruhdagi xabardan kelgani tarixda qolishi kerak)."""
    t = _task(conn, task_id)
    if t["created_msg"] is not None:
        raise ValueError("Guruhdagi xabardan kelgan vazifani o'chirib bo'lmaydi, uni Bajarildi ga o'tkazing")
    conn.execute("DELETE FROM task_checks WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM task_events WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.bump_version(conn)
    return t["tg_chat"], t["tg_msg"], t["title"]


def copy(conn: sqlite3.Connection, task_id: int, who: str | None = None) -> int:
    t = _task(conn, task_id)
    items = [r["text"] for r in conn.execute("SELECT text FROM task_checks WHERE task_id = ? ORDER BY pos, id", (task_id,))]
    return create(conn, t["title"], t["project_id"], None, t["deadline"], t["priority"], t["note"], who, items)


# ---------- ichki ro'yxat (checklist) ----------

def _sync_checks(conn: sqlite3.Connection, task_id: int, who: str | None) -> None:
    """Bajarilish foizi ro'yxatdan hisoblanadi: ish boshlansa kartochka "Jarayonda" ga, hamma band tugasa
    "Tekshiruvda" ga o'tadi (yakuniy "Bajarildi" ni menejer yoki ijrochi tasdiqlaydi)."""
    d, n = conn.execute("SELECT coalesce(sum(done), 0), count(*) FROM task_checks WHERE task_id = ?", (task_id,)).fetchone()
    t = _task(conn, task_id)
    if not n or t["status"] == "done":
        return
    pct = round(100 * d / n)
    before = st = stage_of(t)
    if d == n and st != "tekshiruv":
        st = "tekshiruv"
    elif st in ("yangi", "qabul") and d:
        st = "jarayon"
    conn.execute("UPDATE tasks SET progress = ?, stage = ?, accepted_at = CASE WHEN ? != 'yangi' THEN COALESCE(accepted_at, ?) "
                 "ELSE accepted_at END WHERE id = ?", (pct, st, st, now().strftime(FMT), task_id))
    if st != before:
        log(conn, task_id, who, "stage", STAGE_NAME[st] + (": ro'yxat tugadi" if st == "tekshiruv" else ""))


def check_add(conn: sqlite3.Connection, task_id: int, text: str, who: str | None = None) -> None:
    text = " ".join((text or "").split())[:200]
    if not text:
        raise ValueError("Band matnini yozing")
    _task(conn, task_id)
    pos = conn.execute("SELECT coalesce(max(pos), -1) + 1 FROM task_checks WHERE task_id = ?", (task_id,)).fetchone()[0]
    conn.execute("INSERT INTO task_checks(task_id, text, pos) VALUES(?, ?, ?)", (task_id, text, pos))
    _sync_checks(conn, task_id, who)
    db.bump_version(conn)


def check_set(conn: sqlite3.Connection, check_id: int, done: bool, who: str | None = None) -> int:
    r = conn.execute("SELECT task_id, text FROM task_checks WHERE id = ?", (check_id,)).fetchone()
    if r is None:
        raise ValueError("Band topilmadi")
    conn.execute("UPDATE task_checks SET done = ? WHERE id = ?", (int(bool(done)), check_id))
    if done:
        log(conn, r["task_id"], who, "check", r["text"])
    _sync_checks(conn, r["task_id"], who)
    db.bump_version(conn)
    return r["task_id"]


def check_del(conn: sqlite3.Connection, check_id: int) -> int:
    r = conn.execute("SELECT task_id FROM task_checks WHERE id = ?", (check_id,)).fetchone()
    if r is None:
        raise ValueError("Band topilmadi")
    conn.execute("DELETE FROM task_checks WHERE id = ?", (check_id,))
    _sync_checks(conn, r["task_id"], None)
    db.bump_version(conn)
    return r["task_id"]


# ---------- Telegram: xabar matni, tugmalar, javoblar va eslatmalar ----------

def message(conn: sqlite3.Connection, task_id: int) -> tuple[str, list[list[tuple[str, str]]], int | None]:
    """(matn, tugmalar, chat_id). Tugmalar holatga qarab: avval qabul, keyin foiz."""
    t = conn.execute("SELECT t.*, p.name AS project, p.chat_id, c.demo FROM tasks t JOIN projects p ON p.id = t.project_id "
                     "LEFT JOIN chats c ON c.id = p.chat_id WHERE t.id = ?", (task_id,)).fetchone()
    e = analytics._esc
    st = stage_of(t)
    lines = ["<b>Vazifa</b>: «%s»" % e(t["title"]), "Ijrochi: %s" % e(mention(conn, t["assignee"])),
             "Loyiha: %s" % e(t["project"])]
    if t["deadline"]:
        lines.append("Muddat: %s" % analytics.uz_date(date.fromisoformat(t["deadline"])))
    if t["priority"] == "yuqori":
        lines.append("Muhim")
    if t["note"]:
        lines.append("\n%s" % e(t["note"]))
    checks = conn.execute("SELECT text, done FROM task_checks WHERE task_id = ? ORDER BY pos, id", (task_id,)).fetchall()
    if checks:
        lines.append("")
        lines += ["%s %s" % ("☑" if c["done"] else "☐", e(c["text"])) for c in checks]
    status = STAGE_NAME[st] + ("" if st in ("yangi", "bajarildi") else ", %d%%" % (t["progress"] or 0))
    lines.append("\nHolat: <b>%s</b>" % status)
    if t["flag"]:
        lines.append(("Savol" if t["flag"] == "savol" else "To'siq") + (": %s" % e(t["flag_text"]) if t["flag_text"] else ""))
    k = "bd:%d:" % task_id
    if st == "yangi":
        rows = [[("Tushundim", k + "ok"), ("Savolim bor", k + "q")]]
    elif st == "bajarildi":
        rows = []
    else:
        rows = [[("25%", k + "25"), ("50%", k + "50"), ("75%", k + "75"), ("Bajardim", k + "done")], [("To'siq bor", k + "blk")]]
    chat = t["chat_id"] if t["chat_id"] and not t["demo"] else None
    return "\n".join(lines), rows, chat


def may_act(conn: sqlite3.Connection, task_id: int, user_id: int, username: str | None, is_admin: bool) -> bool:
    t = conn.execute("SELECT assignee FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if t is None:
        return False
    p = _person(conn, t["assignee"])
    if p and (p["id"] == user_id or (username and (p["username"] or "").lower() == username.lower())):
        return True
    lead = conn.execute("SELECT role FROM people WHERE id = ?", (user_id,)).fetchone()
    return is_admin or bool(lead and lead["role"] == "rahbar") or bool(config.OWNER_ID and user_id == config.OWNER_ID)


def act(conn: sqlite3.Connection, task_id: int, action: str, who: str | None = None) -> str:
    """Tugma bosildi. Qaytaradi: foydalanuvchiga qisqa javob."""
    ts = now().strftime(FMT)
    if action == "ok":
        conn.execute("UPDATE tasks SET stage = 'qabul', accepted_at = ?, flag = NULL, flag_text = NULL WHERE id = ? AND status = 'open'",
                     (ts, task_id))
        log(conn, task_id, who, "stage", "Tushundim, qabul qildi")
        answer = "Qabul qilindi"
    elif action in ("25", "50", "75"):
        move(conn, task_id, "jarayon", int(action), who)
        conn.execute("UPDATE tasks SET flag = NULL, flag_text = NULL, accepted_at = COALESCE(accepted_at, ?) WHERE id = ?", (ts, task_id))
        answer = "%s%% belgilandi" % action
    elif action == "done":
        move(conn, task_id, "bajarildi", None, who)
        answer = "Bajarildi, rahmat"
    elif action in ("q", "blk"):
        conn.execute("UPDATE tasks SET flag = ?, flag_text = NULL WHERE id = ?", ("savol" if action == "q" else "toqiq", task_id))
        log(conn, task_id, who, "stage", "Savolim bor" if action == "q" else "To'siq bor")
        answer = "Shu xabarga javob qilib yozing: " + ("savolingiz" if action == "q" else "nima to'sib turibdi")
    else:
        raise ValueError(action)
    db.bump_version(conn)
    return answer


def find_by_message(conn: sqlite3.Connection, chat_id: int, msg_id: int) -> int | None:
    """Javob qaysi vazifaga: vazifa xabarining o'ziga yoki bot o'sha vazifa bo'yicha yozgan izoh/eslatmaga."""
    r = conn.execute("SELECT id FROM tasks WHERE tg_chat = ? AND tg_msg = ?", (chat_id, msg_id)).fetchone()
    if r is None:
        r = conn.execute("SELECT t.id FROM task_events e JOIN tasks t ON t.id = e.task_id "
                         "WHERE e.msg = ? AND t.tg_chat = ? ORDER BY e.id DESC LIMIT 1", (msg_id, chat_id)).fetchone()
    return r["id"] if r else None


def heard(conn: sqlite3.Connection, task_id: int, text: str, author: str | None) -> None:
    """Vazifa xabariga ijrochidan boshqa kishi javob yozdi: holat o'zgarmaydi, lekin tarixda ko'rinadi."""
    if (text or "").strip():
        log(conn, task_id, author, "telegram", text.strip())
        db.bump_version(conn)


def reply(conn: sqlite3.Connection, task_id: int, text: str, author: str) -> str:
    """Bot xabariga erkin javob: foiz, tushundim, bajardim, savol yoki to'siq. Har javob tarixga yoziladi.
    Qaytaradi: reaksiya emojisi (holat o'zgarmagan oddiy izohda bo'sh)."""
    t = _task(conn, task_id)
    low = (text or "").lower()
    m = PCT_RE.search(low)
    ts = now().strftime(FMT)
    log(conn, task_id, author, "telegram", text.strip())
    if t["flag"] in ("savol", "toqiq") and not m and not DONE_RE.search(low):
        conn.execute("UPDATE tasks SET flag_text = ? WHERE id = ?", (text.strip()[:300], task_id))
        if t["flag"] == "toqiq":
            conn.execute("INSERT INTO blockers(project_id, text, author, created_at) VALUES(?, ?, ?, ?)",
                         (t["project_id"], "%s: %s" % (t["title"][:60], text.strip()[:160]), author, ts))
        emoji = "👀"
    elif m or "yarm" in low:
        p = int(m.group(1)) if m else 50
        if p >= 100:
            move(conn, task_id, "bajarildi", None, author)
            emoji = "👍"
        else:
            move(conn, task_id, "jarayon", p, author)
            emoji = "✍"
    elif DONE_RE.search(low):
        move(conn, task_id, "bajarildi", None, author)
        emoji = "👍"
    elif BLOCKER_RE.search(low):
        conn.execute("UPDATE tasks SET flag = 'toqiq', flag_text = ? WHERE id = ?", (text.strip()[:300], task_id))
        conn.execute("INSERT INTO blockers(project_id, text, author, created_at) VALUES(?, ?, ?, ?)",
                     (t["project_id"], "%s: %s" % (t["title"][:60], text.strip()[:160]), author, ts))
        emoji = "👀"
    elif QUESTION_RE.search(low):
        conn.execute("UPDATE tasks SET flag = 'savol', flag_text = ? WHERE id = ?", (text.strip()[:300], task_id))
        emoji = "🤔"
    elif ACCEPT_RE.search(low):
        conn.execute("UPDATE tasks SET stage = CASE WHEN stage IS NULL OR stage = 'yangi' THEN 'qabul' ELSE stage END, "
                     "accepted_at = COALESCE(accepted_at, ?) WHERE id = ? AND status = 'open'", (ts, task_id))
        emoji = "👌"
    else:
        emoji = ""
    db.bump_version(conn)
    return emoji


def reminders(conn: sqlite3.Connection) -> list[tuple[int, int, int, str, str]]:
    """Avtomatik eslatmalar (task_id, chat, xabar, tur, matn): "Tushundim" kelmagan va muddati ertaga bo'lgan vazifalar.
    "javob" eslatmasi vazifaga bir marta, "muddat" eslatmasi kuniga bir marta. Yuborilgach bot reminded() ni chaqiradi."""
    n = now()
    if n.weekday() >= 5 or not WORK_FROM <= n.hour < WORK_TO:
        return []
    out = []
    old = (n - timedelta(hours=WAIT_HOURS)).strftime(FMT)
    for t in conn.execute("SELECT * FROM tasks WHERE status = 'open' AND tg_msg IS NOT NULL AND accepted_at IS NULL "
                          "AND (stage IS NULL OR stage = 'yangi') AND created_at <= ?", (old,)):
        if conn.execute("SELECT 1 FROM task_events WHERE task_id = ? AND kind = 'remind' AND text LIKE 'javob%'", (t["id"],)).fetchone():
            continue
        out.append((t["id"], t["tg_chat"], t["tg_msg"], "javob",
                    "%s, «%s» vazifasini ko'rdingizmi? «Tushundim» tugmasini bosing yoki savolingizni shu xabarga yozing."
                    % (mention(conn, t["assignee"]), t["title"])))
    tomorrow = (n.date() + timedelta(days=1)).isoformat()
    for t in conn.execute("SELECT * FROM tasks WHERE status = 'open' AND tg_msg IS NOT NULL AND deadline = ?", (tomorrow,)):
        if conn.execute("SELECT 1 FROM task_events WHERE task_id = ? AND kind = 'remind' AND text LIKE 'muddat%' AND at >= ?",
                        (t["id"], n.date().isoformat())).fetchone():
            continue
        out.append((t["id"], t["tg_chat"], t["tg_msg"], "muddat",
                    "%s, «%s» muddati ertaga. Holatini shu xabarga yozib qo'ying yoki foizni belgilang."
                    % (mention(conn, t["assignee"]), t["title"])))
    return out


def reminded(conn: sqlite3.Connection, task_id: int, kind: str, msg: int | None) -> None:
    """Eslatma yuborildi (yoki yuborib bo'lmadi): qayta-qayta yozmaslik uchun tarixga belgi."""
    log(conn, task_id, "Bot", "remind", kind + (": eslatma yuborildi" if msg else ": eslatma yuborilmadi"), msg)
    db.bump_version(conn)


def demo_stages(conn: sqlite3.Connection) -> None:
    """Namuna ma'lumotda doska jonli ko'rinsin: ochiq vazifalarga yoshiga qarab ustun va foiz."""
    today = now().date()
    for r in conn.execute("SELECT t.id, t.created_at FROM tasks t JOIN projects p ON p.id = t.project_id "
                          "JOIN chats c ON c.id = p.chat_id WHERE c.demo = 1 AND t.status = 'open' AND t.stage IS NULL").fetchall():
        age = (today - date.fromisoformat(r["created_at"][:10])).days
        h = (r["id"] * 2654435761) % 100
        if age == 0:
            stage, pr = ("yangi", 0) if h < 55 else ("qabul", 0)
        elif age <= 2:
            stage, pr = ("qabul", 0) if h < 30 else ("jarayon", 25 + (h % 3) * 25)
        else:
            stage, pr = ("tekshiruv", 90) if h < 15 else ("jarayon", min(75, 25 + (h % 3) * 25))
        conn.execute("UPDATE tasks SET stage = ?, progress = ?, accepted_at = CASE WHEN ? != 'yangi' THEN created_at END, "
                     "priority = CASE WHEN ? < 6 THEN 'yuqori' END WHERE id = ?", (stage, pr, stage, h, r["id"]))
    conn.execute("UPDATE tasks SET stage = 'bajarildi', progress = 100 WHERE status = 'done' AND stage IS NULL")
    # har to'rtinchi ochiq vazifaga o'z muddati: kalendar va "kechikkan" filtri bo'sh turmasin (tanlov id ga bog'liq, qayta ishlasa o'zgarmaydi)
    for r in conn.execute("SELECT t.id, t.created_at FROM tasks t JOIN projects p ON p.id = t.project_id JOIN chats c ON c.id = p.chat_id "
                          "WHERE c.demo = 1 AND t.status = 'open' AND t.deadline IS NULL").fetchall():
        h = (r["id"] * 40503) % 100
        if h < 27:
            due = date.fromisoformat(r["created_at"][:10]) + timedelta(days=2 + h % 9)
            conn.execute("UPDATE tasks SET deadline = ? WHERE id = ?", (due.isoformat(), r["id"]))
