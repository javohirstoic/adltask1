"""Vazifa berilayotgan paytdagi nazorat: yuklama ogohlantirishi va vazifa taklifi.

Yuklama: yangi vazifa ishi ko'p xodimga yozilsa, bot o'sha xabarga javob beradi. Xodimning holatini
aytadi va shu bo'limdan bo'shroq odamni tavsiya qiladi. Tanlovni vazifa bergan kishi yoki rahbar
qiladi, natija rahbarning qarorlar jurnaliga tushadi.

Taklif: "Faqat rahbarlar" sozlamasida oddiy xodim boshqaga yozgan vazifa o'sha xodim (yoki rahbar)
"Qabul qilaman" bosgandan keyin hisobga kiradi.

Ishi ko'p degan baho paneldagi bilan bir xil qoidadan olinadi (analytics.people_view).
"""
from datetime import timedelta
from html import escape

from django.conf import settings

from analytics import services as analytics
from core import appsettings, conf
from core.models import DataVersion
from people.models import Person
from people.services import is_lead
from projects.models import Task

from .models import Alert, Decision

# Bo'shroq xodim qaysi bo'limlardan qidiriladi: backend va frontend ishini fullstack ham qila oladi
FITS = {"Backend": {"Backend", "Fullstack"}, "Frontend": {"Frontend", "Fullstack"}}


def _first(name: str) -> str:
    return name.split()[0] if name else name


def _tasks(ids: list[int]) -> list[dict]:
    return [{"id": t.id, "title": t.title, "assignee": t.assignee.name if t.assignee else None, "status": t.status,
             "project_id": t.project_id, "project": t.project.name}
            for t in Task.objects.filter(id__in=ids).select_related("assignee", "project")]


def _candidates(people: dict, person: dict, project_id: int) -> list[dict]:
    """Ochiq vazifasi sezilarli kam, jim bo'lmagan xodimlar: avval aynan shu bo'limdan, keyin shu ishni qila oladigan
    bo'limdan (backend/frontend uchun fullstack). Teng bo'lsa shu loyihada ishlaganlar oldinda."""
    dept = person["department"]
    if dept == "Belgilanmagan":
        return []
    fits = FITS.get(dept, {dept})
    in_project = set(Task.objects.filter(project_id=project_id).values_list("assignee__name", flat=True))
    pool = [p for p in people.values() if p["name"] != person["name"] and p["department"] in fits
            and p["state"] in ("idle", "ok", "stuck") and p["open"] <= person["open"] - 3]
    # Bo'limi belgilangan, so'nggi 2 haftada guruhga yozgan, lekin hali vazifa olmagan xodim ham bo'sh
    since = conf.now() - timedelta(days=14)
    recent = Person.objects.filter(department__name__in=fits, messages__date__gte=since).select_related("department").distinct()
    for r in recent:
        if r.name not in people and r.name != person["name"] and not (r.telegram_id and r.telegram_id == settings.OWNER_ID):
            pool.append({"name": r.name, "open": 0, "assigned14": 0, "department": r.department.name, "state": "idle"})
    pool.sort(key=lambda p: (p["department"] != dept, p["open"], p["state"] == "stuck", p["name"] not in in_project,
                             p["assigned14"], p["name"]))
    return pool[:2]


def _load_line(p: dict) -> str:
    return "ochiq vazifasi yo'q" if not p["open"] else "%d ta ochiq" % p["open"]


def check(task_ids: list[int], giver_telegram_id: int, chat_id: int, msg_id: int) -> list[dict]:
    """Yangi vazifalar ichida ishi ko'p xodimga berilganlari bo'lsa — har biri uchun bitta savol."""
    S = appsettings.load()
    if S["assign_check"] == "off" or not task_ids:
        return []
    giver = Person.objects.filter(telegram_id=giver_telegram_id).first()
    by_person: dict[str, list[dict]] = {}
    for t in _tasks(task_ids):
        if t["status"] == "open" and t["assignee"] and (giver is None or t["assignee"] != giver.name):
            by_person.setdefault(t["assignee"], []).append(t)
    if not by_person:
        return []
    data = analytics.compute("week")
    people = {p["name"]: p for p in data["people"]}
    out = []
    for name, tasks in by_person.items():
        p = people.get(name)
        if p is None or p["state"] != "overloaded":
            continue
        # Shu kishi bugun shu odamga "baribir bersin" degan bo'lsa, qayta so'ralmaydi
        today = conf.now().replace(hour=0, minute=0, second=0)
        if giver and Alert.objects.filter(kind="yuklama", assignee__name=name, giver=giver, resolution="keep",
                                          resolved_at__gte=today).exists():
            continue
        cands = _candidates(people, p, tasks[0]["project_id"])
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
        alert = Alert.objects.create(kind="yuklama", created_at=conf.now(), chat_id=chat_id, msg_id=msg_id, giver=giver,
                                     assignee=Person.objects.filter(name=name).first(), task_ids=[t["id"] for t in tasks],
                                     options=[c["name"] for c in cands], text=text)
        buttons = [[("%sga berish" % _first(c["name"]), "yk:%d:%d" % (alert.id, i)) for i, c in enumerate(cands)]] if cands else []
        buttons.append([("%sda qolsin" % _first(name), "yk:%d:k" % alert.id)])
        out.append({"id": alert.id, "text": text, "buttons": buttons, "mode": S["assign_check"]})
    return out


def propose(task_ids: list[int], giver_telegram_id: int, giver_name: str, chat_id: int, msg_id: int) -> list[dict]:
    """Taklif: har bir xodimga bitta savol — "Qabul qilaman / Rad etaman"."""
    giver = Person.objects.filter(telegram_id=giver_telegram_id).first()
    by_person: dict[str, list[dict]] = {}
    for t in _tasks(task_ids):
        if t["status"] == "taklif":
            by_person.setdefault(t["assignee"], []).append(t)
    out = []
    for name, tasks in by_person.items():
        person = Person.objects.filter(name=name).first()
        who = "@" + person.username if person and person.username else escape(name)
        text = "%s, %s sizga vazifa bermoqchi: %s (%s).\nQabul qilsangiz, vazifa sizning hisobingizga yoziladi." % (
            who, escape(giver_name), ", ".join("«%s»" % escape(t["title"]) for t in tasks), escape(tasks[0]["project"]))
        alert = Alert.objects.create(kind="taklif", created_at=conf.now(), chat_id=chat_id, msg_id=msg_id, giver=giver,
                                     assignee=person, task_ids=[t["id"] for t in tasks], text=text)
        out.append({"id": alert.id, "text": text, "buttons": [[("Qabul qilaman", "tk:%d:ha" % alert.id), ("Rad etaman", "tk:%d:yoq" % alert.id)]]})
    return out


def sent(alert_id: int, bot_chat_id: int, bot_msg_id: int) -> None:
    Alert.objects.filter(id=alert_id).update(bot_chat_id=bot_chat_id, bot_msg_id=bot_msg_id)


def get(alert_id: int) -> Alert | None:
    return Alert.objects.select_related("assignee", "giver").filter(id=alert_id).first()


def may_decide(alert: Alert, user_id: int, username: str | None, admin: bool) -> bool:
    """Yuklama savolini vazifa bergan kishi yoki rahbar, taklifni esa vazifa yozilgan xodim yoki rahbar hal qiladi."""
    if admin or is_lead(user_id):
        return True
    if alert.kind == "yuklama":
        return alert.giver is not None and alert.giver.telegram_id == user_id
    target = alert.assignee
    if target is None:
        return False
    return target.telegram_id == user_id or bool(username and target.username and username.lower() == target.username.lower())


def _decide(alert: Alert, resolution: str, by: str) -> None:
    Alert.objects.filter(id=alert.id).update(resolved_at=conf.now(), resolution=resolution, resolved_by=by)


def _log(kind: str, title: str, payload: dict, chat_id: int | None, note: str) -> None:
    Decision.objects.create(created_at=conf.now(), type=kind, title=title, payload=payload, chat_id=chat_id, sent=True, note=note,
                            origin="guruh")


def resolve(alert_id: int, choice: str, by: str) -> dict:
    """Tugma bosildi. Natija: tahrirlangan matn, qisqa javob va kerak bo'lsa yangi mas'ulga xabar."""
    a = get(alert_id)
    if a is None:
        return {"answer": "Bu savol eskirgan"}
    if a.resolved_at:
        return {"answer": "Allaqachon hal qilingan: %s" % a.resolved_by}
    src = a.assignee.name if a.assignee else ""
    tasks = [t for t in _tasks(a.task_ids) if t["assignee"] == src and t["status"] in ("open", "taklif")]
    if not tasks:
        _decide(a, "eskirgan", by)
        return {"answer": "Vazifa allaqachon o'zgargan", "text": a.text + "\n\nVazifa allaqachon o'zgargan yoki yopilgan."}
    tids = [t["id"] for t in tasks]
    label = ", ".join("«%s»" % t["title"] for t in tasks[:2]) + (" va yana %d ta" % (len(tasks) - 2) if len(tasks) > 2 else "")
    notify = []

    if a.kind == "taklif":
        if choice == "ha":
            Task.objects.filter(id__in=tids, status="taklif").update(status="open", created_at=conf.now())
            _decide(a, "qabul", by)
            text, answer = a.text + "\n\nQabul qilindi (%s)." % escape(by), "Qabul qilindi"
        else:
            Task.objects.filter(id__in=tids, status="taklif").delete()
            _decide(a, "rad", by)
            text, answer = a.text + "\n\nRad etildi (%s)." % escape(by), "Rad etildi"
        DataVersion.bump()
        return {"answer": answer, "text": text}

    if choice == "k":
        _decide(a, "keep", by)
        _log("keep", "%sga ishi ko'p bo'lsa ham berildi" % _first(src), {"name": src, "task_ids": tids}, a.chat_id,
             "%s. Qaror: %s" % (label, by))
        DataVersion.bump()
        return {"answer": "%sda qoldi" % _first(src), "text": a.text + "\n\n<b>Qaror:</b> %sda qoldi (%s)." % (escape(_first(src)), escape(by))}

    try:
        dst = a.options[int(choice)]
    except (ValueError, IndexError):
        return {"answer": "Noto'g'ri tanlov"}
    new_owner = Person.objects.filter(name=dst).first()
    if new_owner is None:
        return {"answer": "Xodim topilmadi"}
    Task.objects.filter(id__in=tids).update(assignee=new_owner)
    _decide(a, dst, by)
    title = ("«%s» %sga o'tkazildi" % (tasks[0]["title"], _first(dst)) if len(tasks) == 1
             else "%d ta vazifa %sdan %sga o'tkazildi" % (len(tasks), _first(src), _first(dst)))
    _log("reassign", title, {"from": src, "to": dst, "task_ids": tids}, a.chat_id, "Ishi ko'p ogohlantirishi. Qaror: %s" % by)
    DataVersion.bump()
    mention = "@" + new_owner.username if new_owner.username else escape(dst)
    note = "Sizga vazifa berildi: %s (%s). %s ishi ko'p bo'lgani uchun o'tkazildi, qaror: %s." % (
        escape(label), escape(tasks[0]["project"]), escape(_first(src)), escape(by))
    if new_owner.dm_chat_id:
        notify.append((new_owner.dm_chat_id, note))
    elif a.chat_id:
        notify.append((a.chat_id, "%s, sizga vazifa berildi: %s. Qaror: %s." % (mention, escape(label), escape(by))))
    return {"answer": "%sga berildi" % _first(dst), "notify": notify,
            "text": a.text + "\n\n<b>Qaror:</b> %s %sga berildi (%s)." % (escape(label), escape(dst), escape(by))}
