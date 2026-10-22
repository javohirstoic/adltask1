"""Vazifa berilayotgan paytdagi nazorat: yuklama ogohlantirishi va vazifa taklifi.

Yuklama: yangi vazifa ishi ko'p xodimga yozilsa, bot o'sha xabarga javob beradi. Xodimning holatini
aytadi va shu bo'limdan bo'shroq odamni tavsiya qiladi. Tanlovni vazifa bergan kishi yoki rahbar
qiladi, natija rahbarning qarorlar jurnaliga tushadi.

Taklif: "Faqat rahbarlar" sozlamasida oddiy xodim boshqaga yozgan vazifa o'sha xodim (yoki rahbar)
"Qabul qilaman" bosgandan keyin hisobga kiradi.

Ishi ko'p degan baho paneldagi bilan bir xil qoidadan olinadi (analytics.people_view).
"""
import json
import sqlite3
from html import escape

from . import analytics, config, db, settings

# Bo'shroq xodim qaysi bo'limlardan qidiriladi: backend va frontend ishini fullstack ham qila oladi
FITS = {"Backend": {"Backend", "Fullstack"}, "Frontend": {"Frontend", "Fullstack"}}


def _first(name: str) -> str:
    return name.split()[0] if name else name


def is_lead(conn: sqlite3.Connection, user_id: int) -> bool:
    if config.OWNER_ID and user_id == config.OWNER_ID:
        return True
    row = conn.execute("SELECT role FROM people WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["role"] == "rahbar")


def _tasks(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    marks = ",".join("?" * len(ids)) or "NULL"
    return [dict(r) for r in conn.execute(
        f"SELECT t.id, t.title, t.assignee, t.status, t.project_id, p.name AS project FROM tasks t "
        f"JOIN projects p ON p.id = t.project_id WHERE t.id IN ({marks})", ids)]


def _candidates(conn: sqlite3.Connection, people: dict, person: dict, project_id: int) -> list[dict]:
    """Ochiq vazifasi sezilarli kam, jim bo'lmagan xodimlar: avval aynan shu bo'limdan, keyin shu ishni qila oladigan
    bo'limdan (backend/frontend uchun fullstack). Teng bo'lsa shu loyihada ishlaganlar oldinda."""
    dept = person["department"]
    if dept == "Belgilanmagan":
        return []
    fits = FITS.get(dept, {dept})
    in_project = {r["assignee"] for r in conn.execute("SELECT DISTINCT assignee FROM tasks WHERE project_id = ?", (project_id,))}
    pool = [p for p in people.values() if p["name"] != person["name"] and p["department"] in fits
            and p["state"] in ("idle", "ok", "stuck") and p["open"] <= person["open"] - 3]
    # Bo'limi belgilangan, so'nggi 2 haftada guruhga yozgan, lekin hali vazifa olmagan xodim ham bo'sh
    marks = ",".join("?" * len(fits))
    for r in conn.execute(f"SELECT DISTINCT pe.id, pe.name, pe.department FROM people pe JOIN messages m ON m.user_id = pe.id "
                          f"WHERE pe.department IN ({marks}) AND m.date >= datetime(?, '-14 days')",
                          list(fits) + [config.now().strftime(analytics.FMT)]):
        if r["name"] not in people and r["name"] != person["name"] and r["id"] != config.OWNER_ID:
            pool.append({"name": r["name"], "open": 0, "assigned14": 0, "department": r["department"], "state": "idle"})
    pool.sort(key=lambda p: (p["department"] != dept, p["open"], p["state"] == "stuck", p["name"] not in in_project,
                             p["assigned14"], p["name"]))
    return pool[:2]


def _load_line(p: dict) -> str:
    return "ochiq vazifasi yo'q" if not p["open"] else "%d ta ochiq" % p["open"]


def check(conn: sqlite3.Connection, task_ids: list[int], giver_id: int, chat_id: int, msg_id: int) -> list[dict]:
    """Yangi vazifalar ichida ishi ko'p xodimga berilganlari bo'lsa — har biri uchun bitta savol."""
    S = settings.load(conn)
    if S["assign_check"] == "off" or not task_ids:
        return []
    giver = conn.execute("SELECT name FROM people WHERE id = ?", (giver_id,)).fetchone()
    by_person: dict[str, list[dict]] = {}
    for t in _tasks(conn, task_ids):
        if t["status"] == "open" and t["assignee"] and (giver is None or t["assignee"] != giver["name"]):
            by_person.setdefault(t["assignee"], []).append(t)
    if not by_person:
        return []
    data = analytics.compute(conn, "week")
    people = {p["name"]: p for p in data["people"]}
    out = []
    for name, tasks in by_person.items():
        p = people.get(name)
        if p is None or p["state"] != "overloaded":
            continue
        # Shu kishi bugun shu odamga "baribir bersin" degan bo'lsa, qayta so'ralmaydi
        if conn.execute("SELECT 1 FROM alerts WHERE kind = 'yuklama' AND assignee = ? AND giver_id = ? AND resolution = 'keep' "
                        "AND resolved_at >= date(?)", (name, giver_id, config.now().strftime(analytics.FMT))).fetchone():
            continue
        cands = _candidates(conn, people, p, tasks[0]["project_id"])
        titles = ", ".join("«%s»" % escape(t["title"]) for t in tasks[:3]) + (" va yana %d ta" % (len(tasks) - 3) if len(tasks) > 3 else "")
        lines = ["<b>%s: ishi ko'p</b>" % escape(name),
                 "%d ta ochiq vazifa, 2 haftada %d ta berilgan. Jamoada o'rtacha %s ta." % (
                     p["open"], p["assigned14"], analytics._num(p["team_median"])),
                 "Yangi: %s." % titles]
        if cands:
            lines.append("%s bo'limida bo'shroq: %s." % (p["department"], "; ".join(
                "%s%s, %s" % (escape(c["name"]), "" if c["department"] == p["department"] else " (%s)" % c["department"], _load_line(c))
                for c in cands)))
        else:
            lines.append("%s bo'limida hozir bo'shroq xodim yo'q." % p["department"])
        text = "\n".join(lines)
        cur = conn.execute(
            "INSERT INTO alerts(kind, created_at, chat_id, msg_id, giver_id, assignee, task_ids, options, text) "
            "VALUES('yuklama', ?, ?, ?, ?, ?, ?, ?, ?)",
            (config.now().strftime(analytics.FMT), chat_id, msg_id, giver_id, name, json.dumps([t["id"] for t in tasks]),
             json.dumps([c["name"] for c in cands], ensure_ascii=False), text))
        aid = cur.lastrowid
        buttons = [[("%sga berish" % _first(c["name"]), "yk:%d:%d" % (aid, i)) for i, c in enumerate(cands)]] if cands else []
        buttons.append([("%sda qolsin" % _first(name), "yk:%d:k" % aid)])
        out.append({"id": aid, "text": text, "buttons": buttons, "mode": S["assign_check"]})
    return out


def propose(conn: sqlite3.Connection, task_ids: list[int], giver_id: int, giver_name: str, chat_id: int, msg_id: int) -> list[dict]:
    """Taklif: har bir xodimga bitta savol — "Qabul qilaman / Rad etaman"."""
    by_person: dict[str, list[dict]] = {}
    for t in _tasks(conn, task_ids):
        if t["status"] == "taklif":
            by_person.setdefault(t["assignee"], []).append(t)
    out = []
    for name, tasks in by_person.items():
        row = conn.execute("SELECT username FROM people WHERE name = ?", (name,)).fetchone()
        who = "@" + row["username"] if row and row["username"] else escape(name)
        text = "%s, %s sizga vazifa bermoqchi: %s (%s).\nQabul qilsangiz, vazifa sizning hisobingizga yoziladi." % (
            who, escape(giver_name), ", ".join("«%s»" % escape(t["title"]) for t in tasks), escape(tasks[0]["project"]))
        cur = conn.execute(
            "INSERT INTO alerts(kind, created_at, chat_id, msg_id, giver_id, assignee, task_ids, text) "
            "VALUES('taklif', ?, ?, ?, ?, ?, ?, ?)",
            (config.now().strftime(analytics.FMT), chat_id, msg_id, giver_id, name, json.dumps([t["id"] for t in tasks]), text))
        aid = cur.lastrowid
        out.append({"id": aid, "text": text, "buttons": [[("Qabul qilaman", "tk:%d:ha" % aid), ("Rad etaman", "tk:%d:yoq" % aid)]]})
    return out


def sent(conn: sqlite3.Connection, alert_id: int, bot_chat_id: int, bot_msg_id: int) -> None:
    conn.execute("UPDATE alerts SET bot_chat_id = ?, bot_msg_id = ? WHERE id = ?", (bot_chat_id, bot_msg_id, alert_id))


def get(conn: sqlite3.Connection, alert_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return dict(row) if row else None


def may_decide(conn: sqlite3.Connection, alert: dict, user_id: int, username: str | None, admin: bool) -> bool:
    """Yuklama savolini vazifa bergan kishi yoki rahbar, taklifni esa vazifa yozilgan xodim yoki rahbar hal qiladi."""
    if admin or is_lead(conn, user_id):
        return True
    if alert["kind"] == "yuklama":
        return user_id == alert["giver_id"]
    me = conn.execute("SELECT name, username FROM people WHERE id = ?", (user_id,)).fetchone()
    target = (alert["assignee"] or "").lstrip("@").lower()
    return bool(me and me["name"] == alert["assignee"]) or bool(username and username.lower() == target)


def _decide(conn, alert: dict, resolution: str, by: str) -> None:
    conn.execute("UPDATE alerts SET resolved_at = ?, resolution = ?, resolved_by = ? WHERE id = ?",
                 (config.now().strftime(analytics.FMT), resolution, by, alert["id"]))


def _log(conn, kind: str, title: str, payload: dict, chat_id: int | None, note: str) -> None:
    conn.execute("INSERT INTO decisions(created_at, type, title, payload, chat_id, sent, note, origin) VALUES(?, ?, ?, ?, ?, 1, ?, 'guruh')",
                 (config.now().strftime(analytics.FMT), kind, title, json.dumps(payload, ensure_ascii=False), chat_id, note))


def resolve(conn: sqlite3.Connection, alert_id: int, choice: str, by: str) -> dict:
    """Tugma bosildi. Natija: tahrirlangan matn, qisqa javob va kerak bo'lsa yangi mas'ulga xabar."""
    a = get(conn, alert_id)
    if a is None:
        return {"answer": "Bu savol eskirgan"}
    if a["resolved_at"]:
        return {"answer": "Allaqachon hal qilingan: %s" % a["resolved_by"]}
    ids = json.loads(a["task_ids"])
    tasks = [t for t in _tasks(conn, ids) if t["assignee"] == a["assignee"] and t["status"] in ("open", "taklif")]
    if not tasks:
        _decide(conn, a, "eskirgan", by)
        return {"answer": "Vazifa allaqachon o'zgargan", "text": a["text"] + "\n\nVazifa allaqachon o'zgargan yoki yopilgan."}
    tids = [t["id"] for t in tasks]
    marks = ",".join("?" * len(tids))
    label = ", ".join("«%s»" % t["title"] for t in tasks[:2]) + (" va yana %d ta" % (len(tasks) - 2) if len(tasks) > 2 else "")
    now = config.now().strftime(analytics.FMT)
    notify = []

    if a["kind"] == "taklif":
        if choice == "ha":
            conn.execute(f"UPDATE tasks SET status = 'open', created_at = ? WHERE id IN ({marks}) AND status = 'taklif'", [now] + tids)
            _decide(conn, a, "qabul", by)
            text, answer = a["text"] + "\n\nQabul qilindi (%s)." % escape(by), "Qabul qilindi"
        else:
            conn.execute(f"DELETE FROM tasks WHERE id IN ({marks}) AND status = 'taklif'", tids)
            _decide(conn, a, "rad", by)
            text, answer = a["text"] + "\n\nRad etildi (%s)." % escape(by), "Rad etildi"
        db.bump_version(conn)
        return {"answer": answer, "text": text}

    src = a["assignee"]
    if choice == "k":
        _decide(conn, a, "keep", by)
        _log(conn, "keep", "%sga ishi ko'p bo'lsa ham berildi" % _first(src),
             {"name": src, "task_ids": tids}, a["chat_id"], "%s. Qaror: %s" % (label, by))
        db.bump_version(conn)
        return {"answer": "%sda qoldi" % _first(src), "text": a["text"] + "\n\n<b>Qaror:</b> %sda qoldi (%s)." % (escape(_first(src)), escape(by))}

    options = json.loads(a["options"] or "[]")
    try:
        dst = options[int(choice)]
    except (ValueError, IndexError):
        return {"answer": "Noto'g'ri tanlov"}
    conn.execute(f"UPDATE tasks SET assignee = ? WHERE id IN ({marks})", [dst] + tids)
    _decide(conn, a, dst, by)
    title = ("«%s» %sga o'tkazildi" % (tasks[0]["title"], _first(dst)) if len(tasks) == 1
             else "%d ta vazifa %sdan %sga o'tkazildi" % (len(tasks), _first(src), _first(dst)))
    _log(conn, "reassign", title, {"from": src, "to": dst, "task_ids": tids}, a["chat_id"], "Ishi ko'p ogohlantirishi. Qaror: %s" % by)
    db.bump_version(conn)
    person = conn.execute("SELECT username, dm_chat_id FROM people WHERE name = ?", (dst,)).fetchone()
    mention = "@" + person["username"] if person and person["username"] else escape(dst)
    note = "Sizga vazifa berildi: %s (%s). %s ishi ko'p bo'lgani uchun o'tkazildi, qaror: %s." % (
        escape(label), escape(tasks[0]["project"]), escape(_first(src)), escape(by))
    if person and person["dm_chat_id"]:
        notify.append((person["dm_chat_id"], note))
    elif a["chat_id"]:
        notify.append((a["chat_id"], "%s, sizga vazifa berildi: %s. Qaror: %s." % (mention, escape(label), escape(by))))
    return {"answer": "%sga berildi" % _first(dst), "notify": notify,
            "text": a["text"] + "\n\n<b>Qaror:</b> %s %sga berildi (%s)." % (escape(label), escape(dst), escape(by))}
