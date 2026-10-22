"""Xabarni qabul qilish: tushunish -> bazaga yozish -> vazifalarni ochish yoki yopish.

Bot ham, tarixni import qilish ham, namuna ma'lumot ham shu bitta yo'ldan o'tadi.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction

from core import appsettings
from core.models import DataVersion
from people.models import Person
from people.services import clean_name, unique_name
from projects.models import Blocker, Chat, Message, Project, Task

from . import ai, memory
from .parser import MENTION_RE, Parsed, detect_project, match_score, norm_key, parse_format, parse_free, words


@dataclass
class Incoming:
    chat_id: int
    chat_title: str
    msg_id: int
    user_id: int            # Telegram user id
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
    return text[:1].upper() + text[1:]


def load_projects() -> list[dict]:
    return [dict(r) for r in Project.objects.values("id", "key", "name", "aliases", "chat_id", "deadline")]


def _relevant(inc: Incoming, reply_ids: list[int], limit: int = 70) -> list[dict]:
    """Xabar haqida bo'lishi mumkin bo'lgan ochiq vazifalar, yoshidan qat'i nazar:
    javob berilganniki -> ma'nosi yaqin (embedding) -> ismi tilga olingan xodimniki -> shu guruhdagi oxirgilari."""
    rows = [{"id": t["id"], "title": t["title"], "assignee": t["assignee__name"],
             "deadline": t["deadline"].isoformat() if t["deadline"] else None,
             "created": t["created_at"].strftime("%Y-%m-%d"), "project": t["project__key"], "chat_id": t["project__chat_id"]}
            for t in Task.objects.filter(status="open").values("id", "title", "assignee__name", "deadline", "created_at",
                                                              "project__key", "project__chat_id")]
    by_id = {t["id"]: t for t in rows}
    picked: list[int] = [i for i in reply_ids if i in by_id]
    text = inc.text or ""
    # Eng yaqin 20 tasi nomzod bo'ladi; qaysi biri haqiqatan gap ketayotgani AI hal qiladi (chegara qo'yilmaydi)
    picked += [t["id"] for _, t in memory.nearest(text, rows, 20)]
    tokens = words(text)
    usernames = {u.lower() for u in MENTION_RE.findall(text)}
    named = set()
    for name, username in Person.objects.values_list("name", "username"):
        first = (words(name or "") or [""])[0]
        if (username or "").lower() in usernames or (len(first) >= 4 and any(w.startswith(first[:5]) for w in tokens)):
            named.add(name)
    picked += [t["id"] for t in sorted(rows, key=lambda t: -t["id"]) if t["assignee"] in named][:20]
    picked += [t["id"] for t in sorted(rows, key=lambda t: -t["id"]) if t["chat_id"] == inc.chat_id][:25]
    seen, out = set(), []
    for i in picked:
        if i not in seen:
            seen.add(i)
            out.append({k: v for k, v in by_id[i].items() if k != "chat_id"})
    return out[:limit]


def context(inc: Incoming) -> dict:
    """AI odamdek tushunishi uchun: kim kim, guruhda qanday ochiq ishlar bor, xabar nimaga javob."""
    reply = None
    extra: list[int] = []
    if inc.reply_to:
        parent = Message.objects.filter(chat_id=inc.chat_id, msg_id=inc.reply_to).select_related("user").first()
        if parent is not None:
            extra = list(Task.objects.filter(created_msg=parent, status="open").values_list("id", flat=True))
            reply = {"author": parent.user.name if parent.user else None, "text": parent.text or "", "task_ids": extra}
    tasks = _relevant(inc, extra)
    # Hamma ma'lum xodim (guruhda hali yozmagani ham ism bilan tilga olinishi mumkin), shu guruhdagilar birinchi
    here = set(Message.objects.filter(chat_id=inc.chat_id).values_list("user_id", flat=True).distinct())
    people = Person.objects.exclude(username__isnull=True).exclude(username="").values_list("id", "name", "username")
    team = [(n, u) for _, n, u in sorted(people, key=lambda p: (p[0] not in here, p[1]))[:150]]
    return {"team": team, "tasks": tasks, "reply": reply}


def understand(inc: Incoming, use_ai: bool) -> Parsed:
    """Faqat o'qiydi, bazaga yozmaydi."""
    today = inc.date.date()
    parsed = parse_format(inc.text, today)
    if parsed is not None:
        return parsed
    projects = load_projects()
    if use_ai:
        parsed = ai.extract(inc.text, inc.user_name, projects, today, context=context(inc))
        if parsed is not None:
            return parsed
    return parse_free(inc.text, projects, today)


def _sender(inc: Incoming) -> Person:
    """Yozgan kishini topadi yoki yaratadi. Rahbar yozgan ism Telegram nomidan ustun."""
    person = Person.objects.filter(telegram_id=inc.user_id).first()
    if person is None and inc.username:
        # oldin @username bilan tilga olingan, endi o'zi yozdi
        person = Person.objects.filter(telegram_id__isnull=True, username__iexact=inc.username).first()
        if person:
            person.telegram_id = inc.user_id
    if person is None:
        return Person.objects.create(telegram_id=inc.user_id, username=inc.username,
                                     name=unique_name(clean_name(inc.user_name), username=inc.username))
    if not person.name_locked:
        new = clean_name(inc.user_name)
        if new != person.name:
            person.name = unique_name(new, exclude_id=person.id, username=inc.username)
    person.username = inc.username
    person.save()
    return person


def resolve_person(mention: str | None, fallback: Person) -> Person:
    """'@username' -> xodim. Noma'lum bo'lsa, o'zi yozguncha nomi bilan vaqtincha xodim yaratiladi."""
    if not mention:
        return fallback
    username = mention.lstrip("@")
    person = Person.objects.filter(username__iexact=username).first()
    return person or Person.objects.create(username=username, name=unique_name("@" + username))


def _revert(mid: int) -> None:
    """Xabar tahrirlanganda uning oldingi ta'sirini bekor qiladi."""
    Task.objects.filter(created_msg_id=mid).delete()
    Task.objects.filter(done_msg_id=mid).update(status="open", done_at=None, done_msg=None)
    Blocker.objects.filter(msg_id=mid).delete()
    Blocker.objects.filter(resolved_msg_id=mid).update(resolved_at=None, resolved_msg=None)


def _close(task_id: int, when: datetime, mid: int) -> None:
    Task.objects.filter(id=task_id).update(status="done", done_at=when, done_msg_id=mid)


@transaction.atomic
def ingest(inc: Incoming, use_ai: bool = True, pre: Parsed | None = None) -> Result:
    """pre: oldindan tayyorlangan natija (masalan, namuna ma'lumotda AI parallel chaqirilganda)."""
    existing = Message.objects.filter(chat_id=inc.chat_id, msg_id=inc.msg_id).first()
    if existing and not inc.edited:
        return Result("none", "format", duplicate=True)

    if inc.media and use_ai and pre is None:
        heard = ai.transcribe(inc.media, inc.mime or "application/octet-stream", inc.text)
        if heard:
            label = "Rasm" if (inc.mime or "").startswith("image/") else "Ovozli xabar"
            inc.text = "%s: %s%s" % (label, heard, "\n" + inc.text if inc.text and inc.text not in heard else "")
    parsed = pre or understand(inc, use_ai)
    if parsed.source == "ai" and parsed.project is None and parsed.kind in ("task", "done", "blocker"):
        # AI loyihani aniqlamasa ("Bulutda ... yakunlandi"), nomi bo'yicha qidiruv yordam beradi
        parsed.project = detect_project(inc.text, load_projects())
    when = inc.date

    chat, created = Chat.objects.get_or_create(id=inc.chat_id, defaults={"title": inc.chat_title, "demo": inc.demo, "added_at": when})
    if not created and chat.title != inc.chat_title:
        Chat.objects.filter(id=chat.id).update(title=inc.chat_title)
    sender = _sender(inc)
    inc.user_name = sender.name

    # Loyihani aniqlash: aniq teg -> javob berilgan xabarning loyihasi -> guruhda yagona loyiha
    project = None
    if parsed.project:
        key = norm_key(parsed.project)
        project = Project.objects.filter(key=key).first()
        if project is None and parsed.source == "format" and key:
            project = Project.objects.create(key=key, name=humanize(parsed.project), chat=chat, created_at=when)
    parent = None
    if inc.reply_to:
        parent = Message.objects.filter(chat_id=inc.chat_id, msg_id=inc.reply_to).first()
    if project is None and parent is not None and parent.project_id and parsed.kind != "none":
        project = parent.project
    if project is None and parsed.kind != "none":
        only = list(Project.objects.filter(chat_id=inc.chat_id)[:2])
        if len(only) == 1:
            project = only[0]

    if existing:
        msg = existing
        _revert(msg.id)
        msg.text, msg.kind, msg.project, msg.source = inc.text, parsed.kind, project, parsed.source
        msg.save()
    else:
        msg = Message.objects.create(chat=chat, msg_id=inc.msg_id, user=sender, date=when, text=inc.text, kind=parsed.kind,
                                     project=project, source=parsed.source, reply_to=inc.reply_to)

    result = Result(parsed.kind, parsed.source, project.name if project else None)
    if parsed.kind in ("task", "done", "blocker") and project is None:
        result.missing_project = True

    if parsed.kind == "task" and project:
        # "Faqat rahbarlar" sozlamasida oddiy xodim boshqaga yozgan vazifa o'sha xodim qabul qilguncha taklif bo'lib turadi
        strict = not inc.lead and appsettings.load()["assign_policy"] == "rahbar"
        for item in parsed.items:
            who = resolve_person(item.assignee, sender)
            status = "taklif" if strict and who.id != sender.id else "open"
            task = Task.objects.create(project=project, title=item.title, assignee=who, status=status, created_at=when,
                                       created_msg=msg, deadline=item.deadline)
            (result.proposed if status == "taklif" else result.task_ids).append(task.id)
            result.created += 1

    elif parsed.kind == "done" and parsed.refs:
        # AI aniq qaysi vazifalar bajarilganini kontekstdan topdi
        for tid in parsed.refs:
            result.closed += Task.objects.filter(id=tid, status="open").update(status="done", done_at=when, done_msg=msg)

    elif parsed.kind == "done":
        remaining = list(parsed.items)
        if parent is not None and parent.kind == "blocker":
            result.closed += Blocker.objects.filter(msg=parent, resolved_at__isnull=True).update(resolved_at=when, resolved_msg=msg)
            remaining = []
        elif parent is not None and parent.kind == "task":
            open_tasks = list(Task.objects.filter(created_msg=parent, status="open").select_related("assignee"))
            if remaining:
                for item in list(remaining):
                    scored = sorted(((match_score(t.title, item.title), t) for t in open_tasks), key=lambda x: -x[0])
                    if scored and scored[0][0] >= 0.5:
                        _close(scored[0][1].id, when, msg.id)
                        open_tasks = [t for t in open_tasks if t.id != scored[0][1].id]
                        remaining.remove(item)
                        result.closed += 1
            else:
                mine = [t for t in open_tasks if t.assignee_id == sender.id] or open_tasks
                for t in mine:
                    _close(t.id, when, msg.id)
                    result.closed += 1
        if project:
            for item in remaining:
                candidates = Task.objects.filter(project=project, status="open", created_at__lte=when)
                best, best_score = None, 0.0
                for t in candidates:
                    score = match_score(t.title, item.title) + (0.1 if t.assignee_id == sender.id else 0)
                    if score > best_score:
                        best, best_score = t, score
                if best is not None and best_score >= 0.6:
                    _close(best.id, when, msg.id)
                else:
                    # Oldin vazifa sifatida yozilmagan ish: darhol bajarilgan vazifa bo'lib qo'shiladi
                    Task.objects.create(project=project, title=item.title, assignee=resolve_person(item.assignee, sender),
                                        status="done", created_at=when, done_at=when, created_msg=msg, done_msg=msg)
                result.closed += 1

    elif parsed.kind == "blocker" and project:
        for text in [i.title for i in parsed.items] or [inc.text.strip()[:160]]:
            Blocker.objects.create(project=project, text=text, author=sender, created_at=when, msg=msg)
            result.created += 1

    elif parsed.kind == "deadline" and parsed.deadline:
        # Muddat kimga: AI topgan vazifalar -> javob berilgan vazifa xabari -> butun loyiha
        targets = list(parsed.refs)
        if not targets and parent is not None and parent.kind == "task":
            targets = list(Task.objects.filter(created_msg=parent, status__in=("open", "taklif")).values_list("id", flat=True))
        if targets:
            result.changed += Task.objects.filter(id__in=targets).exclude(status="done").update(deadline=parsed.deadline)
        elif project:
            Project.objects.filter(id=project.id).update(deadline=parsed.deadline)
            result.changed += 1

    elif parsed.kind == "reassign" and parsed.refs and parsed.items:
        who = resolve_person(parsed.items[0].assignee, sender)
        result.changed += Task.objects.filter(id__in=parsed.refs, status="open").update(assignee=who)

    Message.objects.filter(id=msg.id).update(items=result.created + result.closed + result.changed)
    DataVersion.bump()
    return result


def process(inc: Incoming, use_ai: bool = True) -> Result:
    """Bot uchun."""
    return ingest(inc, use_ai)
