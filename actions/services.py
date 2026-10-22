"""Qaror markazi: rahbar paneldan tavsiyani bajaradi.

Har harakat avval oldindan ko'rsatiladi (preview), tasdiqdan keyin bajariladi (execute) va jurnalga yoziladi.
Haqiqiy guruhda bot rasmiy xabar yozadi; namuna (demo) guruhlarga hech narsa yuborilmaydi.
"""
from datetime import date

from django.conf import settings
from django.db import transaction

from analytics import services as analytics
from core import conf
from core.models import DataVersion
from core.telegram_api import send_message
from ingest.models import Correction
from ingest.parser import Parsed, extract_items
from ingest.services import Incoming, ingest
from people.models import Person
from projects.models import Blocker, Chat, Message, Project, Task

from .models import Decision


def _mention(name: str) -> str:
    username = Person.objects.filter(name=name).values_list("username", flat=True).first()
    return "@" + username if username else name


def _chat(chat_id: int | None) -> dict | None:
    if not chat_id:
        return None
    c = Chat.objects.filter(id=chat_id).values("id", "title", "demo").first()
    return c


def _project(pid) -> Project:
    p = Project.objects.select_related("chat").filter(id=int(pid)).first()
    if p is None:
        raise ValueError("Loyiha topilmadi")
    return p


def _plan(action: dict) -> dict:
    """Harakat nimani o'zgartiradi va guruhga qanday xabar ketadi."""
    t = action.get("type")
    if t == "reassign":
        src, dst = action["from"], action["to"]
        ids = [int(i) for i in action.get("task_ids") or []]
        rows = list(Task.objects.filter(id__in=ids, status="open", assignee__name=src).select_related("project"))
        if not rows:
            raise ValueError("O'tkaziladigan ochiq vazifa topilmadi, ehtimol allaqachon yopilgan")
        if not Person.objects.filter(name=dst).exists():
            raise ValueError("Xodim topilmadi: %s" % dst)
        chat = _chat(rows[0].project.chat_id)
        text = "Rahbar qarori: quyidagi vazifalar %s ga o'tkazildi (avval %s da edi):\n%s" % (
            _mention(dst), src, "\n".join("— %s (%s)" % (r.title, r.project.name) for r in rows))
        title = ("«%s» %sga o'tkazildi" % (rows[0].title, dst.split()[0]) if len(rows) == 1
                 else "%d ta vazifa %sdan %sga o'tkazildi" % (len(rows), src.split()[0], dst.split()[0]))
        return {"title": title, "items": [r.title for r in rows], "chat": chat, "message": text, "task_ids": [r.id for r in rows]}
    if t == "deadline":
        p = _project(action["project_id"])
        new = date.fromisoformat(action["date"])
        old = analytics.uz_date(p.deadline) if p.deadline else "belgilanmagan"
        text = "#deadline #%s %s\nRahbar «%s» loyihasining yangi muddatini belgiladi: %s." % (
            p.key, new.strftime("%d.%m.%Y"), p.name, analytics.uz_date(new))
        title = ("%s: muddat %sdan %sga surildi" % (p.name, old, analytics.uz_date(new)) if p.deadline
                 else "%s: muddat %s" % (p.name, analytics.uz_date(new)))
        return {"title": title, "items": [], "chat": _chat(p.chat_id), "message": text}
    if t == "ping_project":
        p = _project(action["project_id"])
        text = "«%s» bo'yicha bugungi holatni yozib bering: nima bajarildi, nima qoldi va qayerda muammo bor." % p.name
        return {"title": "%s jamoasidan holat so'rash" % p.name, "items": [], "chat": _chat(p.chat_id), "message": text}
    if t == "ping_blocker":
        p = _project(action["project_id"])
        b = Blocker.objects.filter(project=p, resolved_at__isnull=True).order_by("created_at").first()
        if b is None:
            raise ValueError("Ochiq muammo topilmadi")
        age = (conf.now().date() - b.created_at.date()).days
        text = "«%s» muammosi %d kundan beri hal bo'lmagan (%s). Mas'ul, bugun holatini yozing." % (b.text, age, p.name)
        return {"title": "%s: muammo bo'yicha eslatma" % p.name, "items": [b.text], "chat": _chat(p.chat_id), "message": text}
    if t in ("ping_person", "dm_person"):
        name = action["name"]
        person = Person.objects.filter(name=name).first()
        first = name.split()[0]
        if person and person.dm_chat_id:
            text = (action.get("text") or "").strip() or (
                "Assalomu alaykum, %s! Vazifalaringiz bo'yicha qisqa holat yozib bering: nima bajarildi va nima qoldi." % first)
            return {"title": "%s ga shaxsiy xabar" % name, "items": [], "message": text,
                    "chat": {"id": person.dm_chat_id, "title": "%s (shaxsiy)" % name, "demo": False}, "private": True}
        if t == "dm_person":
            raise ValueError("%s hali botga ulanmagan. Unga shaxsiy havolani yuboring." % name)
        last = Message.objects.filter(user__name=name).order_by("-date").values_list("chat_id", flat=True).first()
        text = "%s, vazifalaringiz bo'yicha qisqa holat yozib bering: nima bajarildi va nima qoldi." % _mention(name)
        return {"title": "%s dan holat so'rash" % name, "items": [], "chat": _chat(last), "message": text}
    raise ValueError("Noma'lum harakat")


def preview(action: dict) -> dict:
    plan = _plan(action)
    chat = plan["chat"]
    plan["will_send"] = bool(chat and not chat["demo"] and settings.BOT_TOKEN)
    plan["chat_title"] = chat["title"] if chat else None
    if plan.get("private") and plan["will_send"]:
        plan["note"] = "Shaxsan yuboriladi, guruhdagilar ko'rmaydi"
    elif plan["will_send"]:
        plan["note"] = "Xabar «%s» guruhiga yuboriladi" % chat["title"]
    else:
        plan["note"] = "Namuna guruh: Telegramga yuborilmaydi, o'zgarish faqat panelda" if chat and chat["demo"] else "Telegramga yuborilmaydi"
    plan.pop("chat")
    return plan


def execute(action: dict, send: bool = True) -> dict:
    with transaction.atomic():
        plan = _plan(action)
        t = action["type"]
        if t == "reassign":
            Task.objects.filter(id__in=plan["task_ids"], status="open").update(assignee=Person.objects.get(name=action["to"]))
        elif t == "deadline":
            Project.objects.filter(id=int(action["project_id"])).update(deadline=date.fromisoformat(action["date"]))
        chat = plan["chat"]
        sent, note = False, "Panelda saqlandi"
        if send and chat and not chat["demo"]:
            sent, note = send_message(chat["id"], plan["message"])
            if sent and plan.get("private"):
                note = "Shaxsan yuborildi"
        elif chat and chat["demo"]:
            note = "Namuna guruh, faqat panelda o'zgardi"
        Decision.objects.create(created_at=conf.now(), type=t, title=plan["title"], payload=action,
                                chat_id=chat["id"] if chat and not plan.get("private") else None, sent=sent, note=note)
        DataVersion.bump()
    return {"ok": True, "sent": sent, "note": note, "title": plan["title"]}


def recent(limit: int = 8) -> list[dict]:
    return [{"id": d.id, "created_at": d.created_at.strftime(conf.FMT), "type": d.type, "title": d.title,
             "sent": int(d.sent), "note": d.note, "origin": d.origin} for d in Decision.objects.all()[:limit]]


@transaction.atomic
def correct(message_id: int, kind: str, project_id: int | None) -> dict:
    """Rahbar AI tushunishini tuzatadi: xabar qayta hisoblanadi, tuzatish fine-tuning to'plamiga yoziladi."""
    if kind not in ("task", "done", "blocker", "none"):
        raise ValueError("Tur: task | done | blocker | none")
    m = Message.objects.select_related("user", "chat", "project").filter(id=message_id).first()
    if m is None:
        raise ValueError("Xabar topilmadi")
    project = Project.objects.filter(id=project_id).first() if project_id else None
    if kind != "none" and project is None:
        raise ValueError("Loyihani tanlang")
    items = extract_items(m.text, kind, {"key": project.key, "name": project.name, "aliases": project.aliases} if project else None) \
        if kind != "none" else []
    pre = Parsed(kind, project.key if project else None, items, None, "tuzatildi")
    inc = Incoming(m.chat_id, m.chat.title, m.msg_id, m.user.telegram_id if m.user else 0, m.user.name if m.user else "Noma'lum",
                   m.user.username if m.user else None, m.date, m.text, m.reply_to, edited=True)
    old_kind, old_project = m.kind, m.project.key if m.project else None
    ingest(inc, pre=pre)
    Correction.objects.create(message=m, text=m.text, old_kind=old_kind, old_project=old_project, new_kind=kind,
                              new_project=project.key if project else None, created_at=conf.now())
    return {"ok": True, "corrections": Correction.objects.count()}
