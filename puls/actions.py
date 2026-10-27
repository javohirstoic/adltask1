"""Qaror markazi: rahbar paneldan tavsiyani bajaradi.

Har harakat avval oldindan ko'rsatiladi (preview), tasdiqdan keyin bajariladi (execute) va jurnalga yoziladi.
Haqiqiy guruhda bot rasmiy xabar yozadi; namuna (demo) guruhlarga hech narsa yuborilmaydi.
"""
import asyncio
import json
import logging
from datetime import date

from . import analytics, config, db
from .ingest import Incoming, ingest
from .parser import Parsed, extract_items

log = logging.getLogger("puls.actions")
BOT = None   # bot.py ishga tushganda o'rnatadi
LOOP = None


def _mention(conn, name: str) -> str:
    row = conn.execute("SELECT username FROM people WHERE name = ?", (name,)).fetchone()
    return "@" + row["username"] if row and row["username"] else name


def _chat(conn, chat_id: int | None) -> dict | None:
    if not chat_id:
        return None
    row = conn.execute("SELECT id, title, demo FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return dict(row) if row else None


def _plan(conn, action: dict) -> dict:
    """Harakat nimani o'zgartiradi va guruhga qanday xabar ketadi."""
    t = action.get("type")
    if t == "reassign":
        src, dst = action["from"], action["to"]
        ids = [int(i) for i in action.get("task_ids") or []]
        marks = ",".join("?" * len(ids)) or "NULL"
        rows = [dict(r) for r in conn.execute(
            f"SELECT t.id, t.title, p.name AS project, p.chat_id FROM tasks t JOIN projects p ON p.id = t.project_id "
            f"WHERE t.id IN ({marks}) AND t.status = 'open' AND t.assignee = ?", ids + [src])]
        if not rows:
            raise ValueError("O'tkaziladigan ochiq vazifa topilmadi, ehtimol allaqachon yopilgan")
        chat = _chat(conn, rows[0]["chat_id"])
        text = "Rahbar qarori: quyidagi vazifalar %s ga o'tkazildi (avval %s da edi):\n%s" % (
            _mention(conn, dst), src, "\n".join("— %s (%s)" % (r["title"], r["project"]) for r in rows))
        title = ("«%s» %sga o'tkazildi" % (rows[0]["title"], dst.split()[0]) if len(rows) == 1
                 else "%d ta vazifa %sdan %sga o'tkazildi" % (len(rows), src.split()[0], dst.split()[0]))
        return {"title": title, "items": [r["title"] for r in rows],
                "chat": chat, "message": text, "task_ids": [r["id"] for r in rows]}
    if t == "deadline":
        p = conn.execute("SELECT id, key, name, deadline, chat_id FROM projects WHERE id = ?", (int(action["project_id"]),)).fetchone()
        if p is None:
            raise ValueError("Loyiha topilmadi")
        new = date.fromisoformat(action["date"])
        old = analytics.uz_date(date.fromisoformat(p["deadline"])) if p["deadline"] else "belgilanmagan"
        text = "#deadline #%s %s\nRahbar «%s» loyihasining yangi muddatini belgiladi: %s." % (
            p["key"], new.strftime("%d.%m.%Y"), p["name"], analytics.uz_date(new))
        title = ("%s: muddat %sdan %sga surildi" % (p["name"], old, analytics.uz_date(new)) if p["deadline"]
                 else "%s: muddat %s" % (p["name"], analytics.uz_date(new)))
        return {"title": title, "items": [],
                "chat": _chat(conn, p["chat_id"]), "message": text}
    if t == "ping_project":
        p = conn.execute("SELECT name, chat_id FROM projects WHERE id = ?", (int(action["project_id"]),)).fetchone()
        if p is None:
            raise ValueError("Loyiha topilmadi")
        text = "«%s» bo'yicha bugungi holatni yozib bering: nima bajarildi, nima qoldi va qayerda muammo bor." % p["name"]
        return {"title": "%s jamoasidan holat so'rash" % p["name"], "items": [], "chat": _chat(conn, p["chat_id"]), "message": text}
    if t == "ping_blocker":
        p = conn.execute("SELECT id, name, chat_id FROM projects WHERE id = ?", (int(action["project_id"]),)).fetchone()
        b = conn.execute("SELECT text, created_at FROM blockers WHERE project_id = ? AND resolved_at IS NULL ORDER BY created_at",
                         (int(action["project_id"]),)).fetchone()
        if p is None or b is None:
            raise ValueError("Ochiq muammo topilmadi")
        age = (config.now().date() - analytics._d(b["created_at"])).days
        text = "«%s» muammosi %d kundan beri hal bo'lmagan (%s). Mas'ul, bugun holatini yozing." % (b["text"], age, p["name"])
        return {"title": "%s: muammo bo'yicha eslatma" % p["name"], "items": [b["text"]], "chat": _chat(conn, p["chat_id"]), "message": text}
    if t == "thank_person":
        # Rahbarning minnatdorchiligi: botga ulangan bo'lsa shaxsan, bo'lmasa ish guruhida (hamma ko'radi — bu ham rag'bat)
        name = action["name"]
        first = name.split()[0]
        person = conn.execute("SELECT dm_chat_id FROM people WHERE name = ?", (name,)).fetchone()
        why = (action.get("why") or "").strip()
        text = (action.get("text") or "").strip() or "%s, oxirgi paytdagi ishingiz uchun rahmat%s. Shunday davom eting!" % (
            first, ": " + why if why else "")
        if person and person["dm_chat_id"]:
            return {"title": "%sga rahmat aytish" % first, "items": [], "message": text,
                    "chat": {"id": person["dm_chat_id"], "title": "%s (shaxsiy)" % name, "demo": 0}, "private": True}
        row = conn.execute("SELECT m.chat_id FROM messages m JOIN people pe ON pe.id = m.user_id WHERE pe.name = ? "
                           "ORDER BY m.date DESC LIMIT 1", (name,)).fetchone()
        return {"title": "%sga rahmat aytish" % first, "items": [], "message": text.replace(first, _mention(conn, name), 1),
                "chat": _chat(conn, row["chat_id"] if row else None)}
    if t in ("ping_person", "dm_person"):
        name = action["name"]
        person = conn.execute("SELECT dm_chat_id FROM people WHERE name = ?", (name,)).fetchone()
        first = name.split()[0]
        if person and person["dm_chat_id"]:
            text = (action.get("text") or "").strip() or (
                "Assalomu alaykum, %s! Vazifalaringiz bo'yicha qisqa holat yozib bering: nima bajarildi va nima qoldi." % first)
            return {"title": "%s ga shaxsiy xabar" % name, "items": [], "message": text,
                    "chat": {"id": person["dm_chat_id"], "title": "%s (shaxsiy)" % name, "demo": 0}, "private": True}
        if t == "dm_person":
            raise ValueError("%s hali botga ulanmagan. Unga shaxsiy havolani yuboring." % name)
        row = conn.execute("SELECT m.chat_id FROM messages m JOIN people pe ON pe.id = m.user_id WHERE pe.name = ? "
                           "ORDER BY m.date DESC LIMIT 1", (name,)).fetchone()
        text = "%s, vazifalaringiz bo'yicha qisqa holat yozib bering: nima bajarildi va nima qoldi." % _mention(conn, name)
        return {"title": "%s dan holat so'rash" % name, "items": [], "chat": _chat(conn, row["chat_id"] if row else None), "message": text}
    raise ValueError("Noma'lum harakat")


def preview(action: dict) -> dict:
    with db.session() as conn:
        plan = _plan(conn, action)
    chat = plan["chat"]
    plan["will_send"] = bool(chat and not chat["demo"] and BOT is not None)
    plan["chat_title"] = chat["title"] if chat else None
    if plan.get("private") and plan["will_send"]:
        plan["note"] = "Shaxsan yuboriladi, guruhdagilar ko'rmaydi"
    elif plan["will_send"]:
        plan["note"] = "Xabar «%s» guruhiga yuboriladi" % chat["title"]
    else:
        plan["note"] = "Namuna guruh: Telegramga yuborilmaydi, o'zgarish faqat panelda" if chat and chat["demo"] else "Telegramga yuborilmaydi"
    plan.pop("chat")
    return plan


def _send(chat_id: int, text: str) -> tuple[bool, str]:
    if BOT is None or LOOP is None:
        return False, "Bot ishlamayapti"
    try:
        asyncio.run_coroutine_threadsafe(BOT.send_message(chat_id, text), LOOP).result(timeout=15)
        return True, "Guruhga yuborildi"
    except Exception as e:  # noqa: BLE001 — sabab foydalanuvchiga ko'rsatiladi
        log.warning("guruhga yuborilmadi: %s", e)
        return False, "Telegramga yuborilmadi"


def execute(action: dict, send: bool = True) -> dict:
    with db.session() as conn:
        plan = _plan(conn, action)
        t = action["type"]
        if t == "reassign":
            ids = plan["task_ids"]
            conn.execute("UPDATE tasks SET assignee = ? WHERE id IN (%s) AND status = 'open'" % ",".join("?" * len(ids)),
                         [action["to"]] + ids)
        elif t == "deadline":
            conn.execute("UPDATE projects SET deadline = ? WHERE id = ?", (action["date"], int(action["project_id"])))
        chat = plan["chat"]
        sent, note = False, "Panelda saqlandi"
        if send and chat and not chat["demo"]:
            sent, note = _send(chat["id"], plan["message"])
            if sent and plan.get("private"):
                note = "Shaxsan yuborildi"
        elif chat and chat["demo"]:
            note = "Namuna guruh, faqat panelda o'zgardi"
        conn.execute("INSERT INTO decisions(created_at, type, title, payload, chat_id, sent, note) VALUES(?, ?, ?, ?, ?, ?, ?)",
                     (config.now().strftime(analytics.FMT), t, plan["title"], json.dumps(action, ensure_ascii=False),
                      chat["id"] if chat else None, int(sent), note))
        db.bump_version(conn)
    return {"ok": True, "sent": sent, "note": note, "title": plan["title"]}


def recent(limit: int = 8) -> list[dict]:
    with db.session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, created_at, type, title, sent, note, origin FROM decisions ORDER BY id DESC LIMIT ?", (limit,))]


def correct(message_id: int, kind: str, project_id: int | None) -> dict:
    """Rahbar AI tushunishini tuzatadi: xabar qayta hisoblanadi, tuzatish fine-tuning to'plamiga yoziladi."""
    if kind not in ("task", "done", "blocker", "none"):
        raise ValueError("Tur: task | done | blocker | none")
    with db.session() as conn:
        m = conn.execute("SELECT m.*, COALESCE(pe.tg_name, pe.name) AS author, pe.username, c.title AS chat_title, p.key AS pkey FROM messages m "
                         "LEFT JOIN people pe ON pe.id = m.user_id LEFT JOIN chats c ON c.id = m.chat_id "
                         "LEFT JOIN projects p ON p.id = m.project_id WHERE m.id = ?", (message_id,)).fetchone()
        if m is None:
            raise ValueError("Xabar topilmadi")
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone() if project_id else None
        if kind != "none" and project is None:
            raise ValueError("Loyihani tanlang")
        items = extract_items(m["text"], kind, dict(project) if project else None) if kind != "none" else []
        pre = Parsed(kind, project["key"] if project else None, items, None, "tuzatildi")
        inc = Incoming(m["chat_id"], m["chat_title"] or "", m["msg_id"], m["user_id"], m["author"] or "Noma'lum", m["username"],
                       analytics.datetime.strptime(m["date"], analytics.FMT), m["text"], m["reply_to"], edited=True)
        ingest(conn, inc, pre=pre)
        conn.execute("INSERT INTO corrections(message_id, text, old_kind, old_project, new_kind, new_project, created_at) "
                     "VALUES(?, ?, ?, ?, ?, ?, ?)", (message_id, m["text"], m["kind"], m["pkey"], kind,
                                                    project["key"] if project else None, config.now().strftime(analytics.FMT)))
        total = conn.execute("SELECT count(*) FROM corrections").fetchone()[0]
    return {"ok": True, "corrections": total}


def invite(name: str, reset: bool = False) -> dict:
    """Xodimning shaxsiy havolasi. Bir marta yaratiladi; reset=True eskisini bekor qiladi."""
    import secrets
    with db.session() as conn:
        row = conn.execute("SELECT id, invite_token, dm_chat_id, dm_linked_at, username, tg_name FROM people WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ValueError("Bu xodim hali guruhga yozmagan")
        token = row["invite_token"]
        if reset or not token:
            token = secrets.token_urlsafe(9).replace("-", "a").replace("_", "b")
            conn.execute("UPDATE people SET invite_token = ? WHERE id = ?", (token, row["id"]))
            if reset:
                conn.execute("UPDATE people SET dm_chat_id = NULL, dm_linked_at = NULL WHERE id = ?", (row["id"],))
            db.bump_version(conn)
        linked = bool(row["dm_chat_id"]) and not reset
        return {"name": name, "id": row["id"], "username": row["username"], "tg_name": row["tg_name"],
                "link": "https://t.me/%s?start=%s" % (config.BOT_USERNAME, token),
                "linked": linked, "linked_at": row["dm_linked_at"] if linked else None}


def add_person(name: str, department: str | None = None) -> dict:
    """Panelda qo'lda qo'shilgan xodim. Telegram akkaunti hali noma'lum: vaqtinchalik manfiy id bilan yoziladi va shaxsiy
    havola beriladi. Xodim havolani bosganda bot uni haqiqiy akkauntiga bog'laydi (claim_person): guruhga avval yozgan
    bo'lsa, o'sha yozuvlari shu xodimga o'tadi."""
    name = " ".join((name or "").split())[:60]
    if len(name) < 2:
        raise ValueError("Ism-familiyani yozing")
    if department and department not in db.DEPARTMENTS:
        raise ValueError("Bo'lim noto'g'ri")
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM people WHERE name = ?", (name,)).fetchone():
            raise ValueError("Bu ismli xodim allaqachon bor")
        low = conn.execute("SELECT min(id) FROM people").fetchone()[0] or 0
        conn.execute("INSERT INTO people(id, name, department, status, name_locked) VALUES(?, ?, ?, 'xodim', 1)",
                     (min(0, low) - 1, name, department or None))
        db.bump_version(conn)
    return invite(name)


def claim_person(conn, row, tg_id: int) -> int:
    """Panelda qo'shilgan xodim (manfiy id) havolani bosdi: endi haqiqiy Telegram id ma'lum. Shu akkaunt guruhga avval
    yozgan bo'lsa ikki yozuv bittaga birlashadi (ism va bo'lim — rahbar panelda yozgani), bo'lmasa id almashtiriladi."""
    if row["id"] >= 0:
        return row["id"]
    ph = dict(conn.execute("SELECT * FROM people WHERE id = ?", (row["id"],)).fetchone())
    real = conn.execute("SELECT id, name FROM people WHERE id = ?", (tg_id,)).fetchone()
    if real is None:
        conn.execute("UPDATE people SET id = ? WHERE id = ?", (tg_id, ph["id"]))
        return tg_id
    conn.execute("DELETE FROM people WHERE id = ?", (ph["id"],))
    db.rename_person(conn, real["name"], ph["name"])
    conn.execute("UPDATE people SET department = coalesce(?, department), status = 'xodim', name_locked = 1, invite_token = ? "
                 "WHERE id = ?", (ph["department"], ph["invite_token"], tg_id))
    return tg_id


def invites() -> list[dict]:
    """Hammaning havolasi; ulanmaganlar birinchi, ulardan guruhga yozib, hisoboti qabul qilinmaganlar eng tepada."""
    with db.session() as conn:
        rows = conn.execute("SELECT pe.name, pe.status, pe.role, pe.line, (SELECT count(*) FROM messages m WHERE m.user_id = pe.id "
                            "AND m.source = 'ulanmagan') AS skipped, (SELECT count(*) FROM messages m WHERE m.user_id = pe.id) AS msgs FROM people pe WHERE pe.id < %d OR pe.id > %d "
                            "ORDER BY pe.name" % (db.DEMO_LO, db.DEMO_HI)).fetchall()
    out = [{**invite(r["name"]), "skipped": r["skipped"], "status": r["status"], "lead": r["role"] == "rahbar", "msgs": r["msgs"],
            "line": r["line"]} for r in rows]
    for x in out:  # panel egasi har doim rahbar
        x["owner"] = bool(config.OWNER_ID and x.get("id") == config.OWNER_ID)
        x["lead"] = x["lead"] or x["owner"]
    # tepada: hal qilinmagan yangilar (ko'p yozganlar oldin), keyin tasdiqlangan, ulangan, rahbarlar, eng pastda "begona"
    rank = lambda x: 4 if x["status"] == "begona" else 3 if x["lead"] else 2 if x["linked"] else 1 if x["status"] == "xodim" else 0
    return sorted(out, key=lambda x: (rank(x), -x["skipped"], x["name"]))
