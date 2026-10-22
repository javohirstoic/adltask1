"""Hisob-kitob: davr ko'rsatkichlari, loyihalar, xodimlar, bo'limlar, Puls indeksi, qarorlar.

Barcha chegaralar sozlamalardan olinadi (settings.py) — kodga qotirib yozilmaydi.
"Vaqt mashinasi": now o'tgan sana bo'lsa, ma'lumot o'sha paytdagi holatga qaytariladi.
"""
import math
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from statistics import median

from django.conf import settings as dj_settings
from django.db.models import F, Q

from core import appsettings as settings
from core import conf
from people.models import Person
from people.services import departments
from projects.models import Blocker, Message, Project, Task

FMT = conf.FMT
MONTHS_UZ = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"]
WEEKDAYS_UZ = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
LEVEL_NAMES = {4: "kritik", 3: "yuqori", 2: "orta", 1: "past", 0: "yaxshi"}
STATUS_LABELS = {4: "Kritik", 3: "Xavf", 2: "Diqqat", 1: "Kuzatuv", 0: "Me'yorda"}
PERIOD_LABELS = {"day": "Bugun", "week": "So'nggi 7 kun", "month": "So'nggi 30 kun"}
PROJECT_HEALTH = {0: 100, 1: 85, 2: 65, 3: 35, 4: 10}
TEAM_HEALTH = {"ok": 1.0, "idle": 0.8, "stuck": 0.5, "silent": 0.3, "overloaded": 0.3}
GRADES = [(80, "A'lo"), (65, "Yaxshi"), (50, "O'rtacha"), (0, "Past")]
STATES = {"overloaded": "Ishi ko'p", "silent": "Jim", "stuck": "Cho'zilgan", "idle": "Bo'sh", "ok": "Me'yorida"}


def uz_date(d: date) -> str:
    return "%d-%s" % (d.day, MONTHS_UZ[d.month - 1])


def _due(t: dict, today: date) -> dict:
    """Vazifaning o'z muddati: necha kun qoldi (manfiy bo'lsa o'tib ketgan)."""
    if not t.get("deadline"):
        return {"deadline": None, "due_in": None, "due_label": None}
    d = date.fromisoformat(t["deadline"])
    return {"deadline": t["deadline"], "due_in": (d - today).days, "due_label": uz_date(d)}


def _ts(d: date, end: bool = False) -> str:
    return "%s %s" % (d.isoformat(), "23:59:59" if end else "00:00:00")


def _in(ts: str | None, a: str, b: str) -> bool:
    return ts is not None and a <= ts <= b


def _d(ts: str) -> date:
    return datetime.strptime(ts, FMT).date()


def _days(a: str, b: str) -> float:
    return (datetime.strptime(b, FMT) - datetime.strptime(a, FMT)).total_seconds() / 86400


def _num(x: float) -> str:
    return ("%g" % round(x, 1)).replace(".", ",")


def _workdays_between(last: date, today: date) -> int:
    """Oxirgi hisobotdan keyin necha ish kuni hisobotsiz o'tdi (bugun hisobga kirmaydi)."""
    count, d = 0, last + timedelta(days=1)
    while d < today:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def resolve_now(asof: str | None) -> datetime:
    """Vaqt mashinasi: o'tgan kun tanlansa — o'sha kun oxiri (19:00), bugun yoki bo'sh bo'lsa — hozir."""
    real = conf.now()
    if not asof:
        return real
    d = date.fromisoformat(asof)
    if d >= real.date():
        return real
    return datetime.combine(d, time(19, 0))


def uz_range(a: date, b: date) -> str:
    """14–20-oktyabr; 28-sentyabr – 4-oktyabr"""
    if a == b:
        return uz_date(a)
    if a.month == b.month and a.year == b.year:
        return "%d–%d-%s" % (a.day, b.day, MONTHS_UZ[a.month - 1])
    return "%s – %s" % (uz_date(a), uz_date(b))


def period_range(period: str, start: str | None, end: str | None, now: datetime):
    today = now.date()
    if period == "custom" and start and end:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if a > b:
            a, b = b, a
        b = min(b, today)
        a = min(a, b)
    else:
        span = {"day": 1, "week": 7, "month": 30}.get(period, 7)
        a, b = today - timedelta(days=span - 1), today
    days = (b - a).days + 1
    prev_b = a - timedelta(days=1)
    prev_a = prev_b - timedelta(days=days - 1)
    return a, b, prev_a, prev_b


def _s(dt: datetime | None) -> str | None:
    return dt.strftime(FMT) if dt else None


class Snapshot:
    """Tanlangan doiradagi (guruh/loyiha) ma'lumot — kerak bo'lsa o'tgan sanadagi holatga qaytarilgan."""

    def __init__(self, now: datetime, chat_id: int | None = None, project_id: int | None = None,
                 project_ids: set[int] | None = None):
        self.now, self.NOW = now, now.strftime(FMT)
        self.today = now.date()
        qs = Project.objects.select_related("chat").filter(Q(created_at__isnull=True) | Q(created_at__lte=now))
        if chat_id:
            qs = qs.filter(chat_id=chat_id)
        if project_id:
            qs = qs.filter(id=project_id)
        if project_ids is not None:  # menejer: faqat o'z loyihalari
            qs = qs.filter(id__in=project_ids)
        self.projects = [{"id": p.id, "key": p.key, "name": p.name, "aliases": p.aliases, "chat_id": p.chat_id,
                          "deadline": p.deadline.isoformat() if p.deadline else None, "created_at": _s(p.created_at),
                          "chat_title": p.chat.title if p.chat else None, "demo": p.chat.demo if p.chat else None} for p in qs]
        pids = [p["id"] for p in self.projects]
        self.tasks = []
        # giver: vazifani yozgan kishi. Xodim hali qabul qilmagan taklif vazifalar hisobga kirmaydi
        for t in Task.objects.filter(project_id__in=pids, created_at__lte=now).exclude(status="taklif").values(
                "id", "project_id", "title", "status", "created_at", "done_at", "deadline", assignee_name=F("assignee__name"),
                giver=F("created_msg__user__name")):
            t["assignee"] = t.pop("assignee_name")
            t["created_at"], t["done_at"] = _s(t["created_at"]), _s(t["done_at"])
            t["deadline"] = t["deadline"].isoformat() if t["deadline"] else None
            if t["done_at"] and t["done_at"] > self.NOW:
                t["status"], t["done_at"] = "open", None
            self.tasks.append(t)
        self.blockers = []
        for x in Blocker.objects.filter(project_id__in=pids, created_at__lte=now).values(
                "id", "project_id", "text", "created_at", "resolved_at", author_name=F("author__name")):
            x["author"] = x.pop("author_name")
            x["created_at"], x["resolved_at"] = _s(x["created_at"]), _s(x["resolved_at"])
            if x["resolved_at"] and x["resolved_at"] > self.NOW:
                x["resolved_at"] = None
            self.blockers.append(x)
        mq = Message.objects.filter(date__lte=now).exclude(kind="none")
        if chat_id:
            mq = mq.filter(chat_id=chat_id)
        if project_id:
            mq = mq.filter(project_id=project_id)
        if project_ids is not None:
            mq = mq.filter(project_id__in=project_ids)
        self.messages = []
        for m in mq.values("id", "project_id", "chat_id", "date", "kind", "user_id", name=F("user__name")):
            m["date"] = _s(m["date"])
            self.messages.append(m)
        self.project_names = {p["id"]: p["name"] for p in self.projects}
        self.people = {}
        for p in Person.objects.values("id", "telegram_id", "name", "username", "dm_chat_id", "role", department_name=F("department__name")):
            p["department"] = p.pop("department_name")
            self.people[p["name"]] = p


def compute(period: str = "week", start: str | None = None, end: str | None = None,
            chat_id: int | None = None, project_id: int | None = None, now: datetime | None = None,
            project_ids: set[int] | None = None) -> dict:
    S = settings.load()
    now = now or conf.now()
    snap = Snapshot(now, chat_id, project_id, project_ids)
    today = snap.today
    a, b, pa, pb = period_range(period, start, end, now)
    A, B, PA, PB = _ts(a), _ts(b, True), _ts(pa), _ts(pb, True)
    ndays = (b - a).days + 1
    tasks = snap.tasks

    by_project, blockers_by, msgs_by = defaultdict(list), defaultdict(list), defaultdict(list)
    for t in tasks:
        by_project[t["project_id"]].append(t)
    for x in snap.blockers:
        blockers_by[x["project_id"]].append(x)
    for m in snap.messages:
        if m["project_id"]:
            msgs_by[m["project_id"]].append(m)

    week_ago = _ts(today - timedelta(days=6))
    rows = []
    for p in snap.projects:
        pts = by_project[p["id"]]
        created = [t for t in pts if _in(t["created_at"], A, B)]
        done_period = [t for t in pts if _in(t["done_at"], A, B)]
        pct = round(100 * sum(t["status"] == "done" for t in created) / len(created)) if created else None
        people = Counter()
        for t in created + done_period:
            if t["assignee"]:
                people[t["assignee"]] += 1
        for m in msgs_by[p["id"]]:
            if _in(m["date"], A, B) and m["name"]:
                people[m["name"]] += 0
        total = len(pts)
        done_total = sum(t["status"] == "done" for t in pts)
        open_total = total - done_total
        progress = round(100 * done_total / total) if total else 0
        velocity = sum(1 for t in pts if t["done_at"] and t["done_at"] >= week_ago) / 7
        dates = [m["date"] for m in msgs_by[p["id"]]] + [t["created_at"] for t in pts]
        last = max(dates) if dates else None
        deadline = date.fromisoformat(p["deadline"]) if p["deadline"] else None
        days_left = (deadline - today).days if deadline else None
        open_blockers = [x for x in blockers_by[p["id"]] if not x["resolved_at"]]
        eta = math.ceil(open_total / velocity) if velocity > 0 and open_total else (0 if not open_total else None)
        eta_date = today + timedelta(days=eta) if eta is not None else None

        risks = []
        if deadline is not None and open_total > 0:
            if days_left < 0:
                risks.append(_risk(4, "overdue", "Muddat %d kun oldin o'tgan, %d ta vazifa ochiq" % (-days_left, open_total)))
            elif days_left <= S["deadline_warn_days"] and progress < S["deadline_warn_progress"]:
                risks.append(_risk(3, "deadline", "Muddatga %d kun qoldi, bajarilgani %d%%" % (days_left, progress)))
            if days_left >= 0:
                if velocity > 0 and eta > days_left:
                    risks.append(_risk(3 if days_left <= 7 else 2, "forecast",
                                       "Hozirgi sur'atda %s tugaydi, muddatdan %d kun kech" % (uz_date(eta_date), eta - days_left)))
                elif velocity == 0:
                    risks.append(_risk(3 if days_left <= 7 else 2, "stalled", "7 kunda birorta vazifa yopilmagan"))
        if last:
            silent = _workdays_between(_d(last), today)
            if silent >= S["project_silence_days"]:
                risks.append(_risk(3 if silent >= S["project_silence_high_days"] else 2, "silence", "%d ish kuni hisobot yo'q" % silent))
        late = [t for t in pts if t["status"] == "open" and t.get("deadline") and t["deadline"] < today.isoformat()]
        if late:
            risks.append(_risk(3 if len(late) >= 3 else 2, "late_tasks", "%d ta vazifa muddati o'tgan" % len(late)))
        for x in open_blockers:
            age = (today - _d(x["created_at"])).days
            risks.append(_risk(3 if age >= S["blocker_high_days"] else 2, "blocker", "Muammo: %s (%d kun)" % (x["text"][:80], age)))
        recent = Counter(t["assignee"] for t in pts if t["created_at"] >= _ts(today - timedelta(days=29)) and t["assignee"])
        if sum(recent.values()) >= 6:
            name, top = recent.most_common(1)[0]
            share = top / sum(recent.values())
            if share >= S["bus_share"] / 100:
                risks.append(_risk(1, "bus", "Ishning %d%% i bitta odamda: %s" % (round(share * 100), name)))

        rows.append({
            "id": p["id"], "key": p["key"], "name": p["name"], "chat_id": p["chat_id"], "chat_title": p["chat_title"],
            "demo": bool(p["demo"]),
            "created": len(created), "done": len(done_period), "pct": pct,
            "created_prev": sum(_in(t["created_at"], PA, PB) for t in pts), "done_prev": sum(_in(t["done_at"], PA, PB) for t in pts),
            "people": [n for n, _ in people.most_common()], "people_count": len(people),
            "total": total, "done_total": done_total, "open_total": open_total, "progress": progress,
            "velocity": round(velocity, 2),
            "deadline": p["deadline"], "deadline_label": uz_date(deadline) if deadline else None, "days_left": days_left,
            "eta_days": eta, "eta_date": eta_date.isoformat() if eta_date else None, "eta_label": uz_date(eta_date) if eta_date else None,
            "late_days": (eta - days_left) if (eta is not None and days_left is not None and eta > days_left) else 0,
            "start_date": min([t["created_at"][:10] for t in pts] or [(p["created_at"] or snap.NOW)[:10]]),
            "last_activity": last,
            "blocker_list": [{"text": x["text"], "age": (today - _d(x["created_at"])).days} for x in open_blockers],
            "risks": risks,
        })

    counts = [r["created"] for r in rows if r["total"]]
    med = median(counts) if counts else 0
    low = []
    for r in rows:
        if r["total"] and med >= 3 and r["created"] < S["low_activity_pct"] / 100 * med:
            r["risks"].append(_risk(1, "low", "Bu davrda %d ta vazifa (o'rtacha %s)" % (r["created"], _num(med))))
            low.append({"id": r["id"], "name": r["name"], "created": r["created"], "median": med})
    for r in rows:
        r["risks"].sort(key=lambda x: -x["level"])
        r["level"] = r["risks"][0]["level"] if r["risks"] else 0
        r["status"] = STATUS_LABELS[r["level"]]
    rows.sort(key=lambda r: (-r["level"], -r["late_days"], r["progress"], r["name"]))

    series = _series(tasks, a, ndays, A, B)
    people, departments = people_view(snap, S, A, B) if not project_id else ([], [])

    in_period = [t for t in tasks if _in(t["created_at"], A, B)]
    done_in = [t for t in tasks if _in(t["done_at"], A, B)]
    prev_done = [t for t in tasks if _in(t["done_at"], PA, PB)]
    cyc = [_days(t["created_at"], t["done_at"]) for t in done_in]
    pcyc = [_days(t["created_at"], t["done_at"]) for t in prev_done]
    people_all = set()
    for r in rows:
        people_all.update(r["people"])
    created_all, created_prev = len(in_period), sum(_in(t["created_at"], PA, PB) for t in tasks)

    def delta(cur, prev):
        return None if not prev else round(100 * (cur - prev) / prev)

    kpi = {
        "projects_active": sum(1 for r in rows if r["created"] or r["done"]), "projects_total": len(rows),
        "people": len(people_all),
        "created": created_all, "created_delta": delta(created_all, created_prev), "per_day": round(created_all / ndays, 1),
        "done": len(done_in), "done_delta": delta(len(done_in), len(prev_done)),
        "pct": round(100 * sum(t["status"] == "done" for t in in_period) / len(in_period)) if in_period else None,
        "cycle": round(sum(cyc) / len(cyc), 1) if cyc else None,
        "cycle_prev": round(sum(pcyc) / len(pcyc), 1) if pcyc else None,
        "at_risk": sum(1 for r in rows if r["level"] >= 3), "attention": sum(1 for r in rows if r["level"] == 2),
        "blockers_open": sum(len(r["blocker_list"]) for r in rows),
        "overloaded": sum(1 for p in people if p["state"] == "overloaded"),
        "idle": sum(1 for p in people if p["state"] == "idle"),
        "silent": sum(1 for p in people if p["state"] == "silent"),
        "stuck": sum(1 for p in people if p["state"] == "stuck"),
    }
    return {
        "period": {"key": period, "label": PERIOD_LABELS.get(period, uz_range(a, b)),
                   "from": a.isoformat(), "to": b.isoformat(), "days": ndays, "range_label": uz_range(a, b)},
        "now": snap.NOW, "historic": now < conf.now() - timedelta(minutes=2), "today_label": uz_date(today),
        "kpi": kpi,
        "spark": _spark(tasks, today),
        "pulse": pulse(rows, people, tasks, today),
        "heartbeat": heartbeat(_recent_messages(chat_id, now, project_ids), now),
        "projects": rows,
        "low_activity": low,
        "series": series,
        "people": people,
        "departments": departments,
        "decisions": decisions(rows, people, today),
    }


def _recent_messages(chat_id: int | None, now: datetime, project_ids: set[int] | None = None) -> list[dict]:
    qs = Message.objects.filter(date__lte=now, date__gte=now - timedelta(hours=24))
    if chat_id:
        qs = qs.filter(chat_id=chat_id)
    if project_ids is not None:
        qs = qs.filter(project_id__in=project_ids)
    return [{"date": _s(d)} for d in qs.values_list("date", flat=True)]


def _risk(level: int, code: str, text: str) -> dict:
    return {"level": level, "code": code, "text": text}


def _series(tasks: list[dict], a: date, ndays: int, A: str, B: str) -> list[dict]:
    out = []
    if ndays == 1:
        for h in range(8, 21):
            lo = A if h == 8 else "%s %02d:00:00" % (a.isoformat(), h)
            hi = B if h == 20 else "%s %02d:59:59" % (a.isoformat(), h)
            out.append({"label": "%02d:00" % h, "created": sum(_in(t["created_at"], lo, hi) for t in tasks),
                        "done": sum(_in(t["done_at"], lo, hi) for t in tasks)})
        return out
    for i in range(ndays):
        d = a + timedelta(days=i)
        lo, hi = _ts(d), _ts(d, True)
        out.append({"label": "%s %02d.%02d" % (WEEKDAYS_UZ[d.weekday()], d.day, d.month), "date": d.isoformat(),
                    "weekend": d.weekday() >= 5, "created": sum(_in(t["created_at"], lo, hi) for t in tasks),
                    "done": sum(_in(t["done_at"], lo, hi) for t in tasks)})
    return out


def _spark(tasks: list[dict], today: date) -> dict:
    """Ko'rsatkich plitkalaridagi 14 kunlik mini grafiklar."""
    created, done, pct, cycle = [], [], [], []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        lo, hi = _ts(d), _ts(d, True)
        c = [t for t in tasks if _in(t["created_at"], lo, hi)]
        dn = [t for t in tasks if _in(t["done_at"], lo, hi)]
        created.append(len(c))
        done.append(len(dn))
        week = [t for t in tasks if _in(t["created_at"], _ts(d - timedelta(days=6)), hi)]
        pct.append(round(100 * sum(1 for t in week if t["done_at"] and t["done_at"] <= hi) / len(week)) if week else None)
        cycle.append(round(sum(_days(t["created_at"], t["done_at"]) for t in dn) / len(dn), 1) if dn else None)
    return {"created": created, "done": done, "pct": pct, "cycle": cycle}


def pulse(rows: list[dict], people: list[dict], tasks: list[dict], today: date) -> dict:
    """Puls indeksi (0–100) = 0,4 loyihalar + 0,3 jamoa + 0,3 ritm. Har qismi alohida qaytariladi."""
    scored = [r for r in rows if r["total"]]
    P = sum(PROJECT_HEALTH[r["level"]] for r in scored) / len(scored) if scored else 100
    T = 100 * sum(TEAM_HEALTH[p["state"]] for p in people) / len(people) if people else 100
    lo = _ts(today - timedelta(days=6))
    c7 = sum(1 for t in tasks if t["created_at"] >= lo)
    d7 = sum(1 for t in tasks if t["done_at"] and t["done_at"] >= lo)
    flow = min(1.0, d7 / c7) if c7 else (1.0 if d7 else 0.5)
    active = [p for p in people if p["silent_days"] is not None]
    disc = sum(1 for p in active if p["silent_days"] <= 1) / len(active) if active else 1.0
    R = 50 * flow + 50 * disc
    value = round(0.4 * P + 0.3 * T + 0.3 * R)
    label = "A'lo" if value >= 85 else "Barqaror" if value >= 70 else "Diqqat kerak" if value >= 55 else "Xavfli"
    return {"value": value, "label": label, "parts": [
        {"name": "Loyihalar", "weight": 40, "value": round(P),
         "text": "%d ta loyihadan %d tasi me'yorda" % (len(scored), sum(1 for r in scored if r["level"] == 0))},
        {"name": "Jamoa", "weight": 30, "value": round(T),
         "text": "%d kishidan %d tasi me'yorida" % (len(people), sum(1 for p in people if p["state"] == "ok"))},
        {"name": "Ritm", "weight": 30, "value": round(R),
         "text": "7 kunda %d ta yangi, %d ta yopildi; %d%% xodim 2 kun ichida hisobot bergan" % (c7, d7, round(disc * 100))},
    ]}


def heartbeat(messages: list[dict], now: datetime) -> dict:
    """Yurak urishi chizig'i: so'nggi 24 soat, 20 daqiqalik bo'laklarda guruhlardagi barcha xabarlar soni."""
    start = now - timedelta(hours=24)
    buckets = [0] * 72
    last = None
    for m in messages:
        t = datetime.strptime(m["date"], FMT)
        if start <= t <= now:
            buckets[min(71, int((t - start).total_seconds() // 1200))] += 1
            last = max(last or m["date"], m["date"])
    return {"buckets": buckets, "total": sum(buckets), "last": last, "start": start.strftime(FMT)}


def people_view(snap: Snapshot, S: dict, A: str, B: str) -> tuple[list[dict], list[dict]]:
    """Har bir xodim: yuklama, vazifalar yoshi, samaradorlik, holat. Va bo'limlar kesimi."""
    today, tasks = snap.today, snap.tasks
    last: dict[str, str] = {}
    last_chat: dict[str, int] = {}
    active = defaultdict(set)
    for m in snap.messages:
        if m["name"]:
            if m["date"] >= last.get(m["name"], ""):
                last[m["name"]], last_chat[m["name"]] = m["date"], m["chat_id"]
            active[m["name"]].add(m["date"][:10])
    for t in tasks:
        if t["done_at"] and t["assignee"]:
            last[t["assignee"]] = max(last.get(t["assignee"], ""), t["done_at"])
            active[t["assignee"]].add(t["done_at"][:10])
    info = snap.people
    # Rahbar (OWNER_ID) xodim emas: uning holati, bahosi va "bo'sh" ro'yxati hisoblanmaydi
    head = next((n for n, p in info.items() if dj_settings.OWNER_ID and p["telegram_id"] == dj_settings.OWNER_ID), None)
    names = {t["assignee"] for t in tasks if t["assignee"] and t["assignee"] != head}
    d30, d14 = _ts(today - timedelta(days=29)), _ts(today - timedelta(days=13))
    workdays14 = {(today - timedelta(days=i)).isoformat() for i in range(14) if (today - timedelta(days=i)).weekday() < 5}
    w = (S["w_completion"], S["w_speed"], S["w_regular"], S["w_fresh"])

    rows = []
    for name in names:
        mine = [t for t in tasks if t["assignee"] == name]
        opened = []
        for t in mine:
            if t["status"] == "open":
                age = (today - _d(t["created_at"])).days
                opened.append({"id": t["id"], "title": t["title"], "project": snap.project_names.get(t["project_id"]),
                               "project_id": t["project_id"], "age": age, "created_at": t["created_at"],
                               "giver": t["giver"] if t["giver"] and t["giver"] != name else None,
                               "state": "new" if age < S["age_slow_days"] else "slow" if age < S["age_stuck_days"] else "stuck",
                               **_due(t, today)})
        opened.sort(key=lambda x: -x["age"])
        overdue = sum(1 for o in opened if o["due_in"] is not None and o["due_in"] < 0)
        recent = [t for t in mine if t["created_at"] >= d30]
        assigned14 = sum(1 for t in mine if t["created_at"] >= d14)
        completion = sum(t["status"] == "done" for t in recent) / len(recent) if recent else None
        cycles = [_days(t["created_at"], t["done_at"]) for t in mine if t["done_at"] and t["done_at"] >= d30]
        cycle = sum(cycles) / len(cycles) if cycles else None
        regular = len(active[name] & workdays14) / max(1, len(workdays14))
        stale = sum(1 for o in opened if o["age"] >= S["age_stuck_days"])
        score = parts = None
        if len(recent) >= 3:
            speed = 0.5 if cycle is None else 1.0 if cycle <= 1 else 0.0 if cycle >= 6 else (6 - cycle) / 5
            parts = {"completion": round(w[0] * (completion or 0)), "speed": round(w[1] * speed),
                     "regular": round(w[2] * min(1.0, regular * 1.25)),
                     "fresh": round(w[3] * (1 - stale / len(opened) if opened else 1))}
            score = round(100 * sum(parts.values()) / max(1, sum(w)))
        last_act = last.get(name)
        person = info.get(name, {})
        rows.append({
            "name": name, "id": person.get("id"), "username": person.get("username"), "dm": bool(person.get("dm_chat_id")),
            "role": person.get("role"),
            "department": person.get("department") or "Belgilanmagan",
            "open": len(opened), "open_tasks": opened, "assigned14": assigned14,
            "created": sum(_in(t["created_at"], A, B) for t in mine), "done": sum(_in(t["done_at"], A, B) for t in mine),
            "completion": round(100 * completion) if completion is not None else None,
            "cycle": round(cycle, 1) if cycle is not None else None, "regular": round(100 * regular),
            "stale": stale, "oldest": opened[0]["age"] if opened else 0, "overdue": overdue,
            "last_activity": last_act, "last_chat": last_chat.get(name),
            "silent_days": _workdays_between(_d(last_act), today) if last_act else None,
            "score": score, "score_parts": parts,
            "grade": next(g for limit, g in GRADES if score >= limit) if score is not None else None,
            "projects": sorted({snap.project_names[t["project_id"]] for t in recent if t["project_id"] in snap.project_names}),
        })

    given = [r["assigned14"] for r in rows if r["assigned14"]]
    med = median(given) if given else 0
    for r in rows:
        if r["open"] == 0:
            r["state"], r["fact"] = "idle", "ochiq vazifa yo'q"
        elif r["open"] >= S["overload_min_open"] and med and r["assigned14"] >= S["overload_ratio"] * med:
            r["state"], r["fact"] = "overloaded", "%d ta vazifa, o'rtachadan %s baravar ko'p" % (r["assigned14"], _num(r["assigned14"] / med))
        elif r["silent_days"] is not None and r["silent_days"] >= S["silent_days"]:
            r["state"], r["fact"] = "silent", "%d ish kuni hisobot yo'q" % r["silent_days"]
        elif r["overdue"]:
            r["state"], r["fact"] = "stuck", "%d ta vazifa muddati o'tgan" % r["overdue"]
        elif r["oldest"] >= S["stuck_days"]:
            r["state"], r["fact"] = "stuck", "%d kunlik vazifa ochiq" % r["oldest"]
        else:
            r["state"], r["fact"] = "ok", "%d ta ochiq" % r["open"]
        r["state_label"] = STATES[r["state"]]
        r["team_median"] = med
    order = {"overloaded": 0, "silent": 1, "stuck": 2, "ok": 3, "idle": 4}
    rows.sort(key=lambda r: (r["department"], order[r["state"]], -(r["score"] or 0)))

    depts = defaultdict(list)
    for r in rows:
        depts[r["department"]].append(r)
    dept_rows = []
    for name, ppl in depts.items():
        names_set = {p["name"] for p in ppl}
        created = [t for t in tasks if t["assignee"] in names_set and _in(t["created_at"], A, B)]
        scores = [p["score"] for p in ppl if p["score"] is not None]
        dept_rows.append({
            "name": name, "count": len(ppl), "people": [p["name"] for p in ppl],
            "open": sum(p["open"] for p in ppl), "created": len(created), "done": sum(p["done"] for p in ppl),
            "pct": round(100 * sum(t["status"] == "done" for t in created) / len(created)) if created else None,
            "score": round(sum(scores) / len(scores)) if scores else None,
            "states": dict(Counter(p["state"] for p in ppl)),
        })
    dept_rows.sort(key=lambda d: (d["name"] == "Belgilanmagan", d["name"]))
    return rows, dept_rows


def decisions(rows: list[dict], people: list[dict], today: date) -> list[dict]:
    """Rahbar qarori kerak bo'lgan masalalar. Har birida: qisqa sarlavha, bitta fakt, tugma va bajariladigan harakat."""
    out = []
    for r in rows:
        if r["level"] < 3:
            continue
        codes = {x["code"]: x for x in r["risks"]}
        bl = r["blocker_list"][0] if r["blocker_list"] else None
        base = {"target": {"type": "project", "id": r["id"]}, "project": r["name"]}
        new_date = date.fromisoformat(r["eta_date"]) if r["eta_date"] else today + timedelta(days=7)
        move = {"type": "deadline", "project_id": r["id"], "date": new_date.isoformat()}
        if "overdue" in codes:
            fact = "Muddat %d kun o'tdi, %d ta vazifa ochiq." % (-r["days_left"], r["open_total"])
            if bl:
                fact += " %s." % bl["text"][:70].rstrip(".")
            out.append({**base, "id": "p%d-overdue" % r["id"], "level": 4, "icon": "hourglass", "title": "%s kechikdi" % r["name"],
                        "fact": fact, "button": "Muddatni %sga surish" % uz_date(new_date), "action": move})
        elif "deadline" in codes or "forecast" in codes:
            out.append({**base, "id": "p%d-late" % r["id"], "level": 3, "icon": "graph-down", "title": "%s ulgurmaydi" % r["name"],
                        "fact": "Muddat %s, hozirgi sur'atda %s tugaydi." % (r["deadline_label"], r["eta_label"] or "noma'lum"),
                        "button": "Muddatni %sga surish" % uz_date(new_date), "action": move})
        elif "stalled" in codes or "silence" in codes:
            fact = codes["stalled"]["text"] if "stalled" in codes else codes["silence"]["text"]
            out.append({**base, "id": "p%d-quiet" % r["id"], "level": 3, "icon": "chat-dots", "title": "%s to'xtab qolgan" % r["name"],
                        "fact": fact, "button": "Guruhdan holatni so'rash",
                        "action": {"type": "ping_project", "project_id": r["id"]}})
        elif "blocker" in codes and bl:
            out.append({**base, "id": "p%d-blocker" % r["id"], "level": 3, "icon": "danger", "title": "%s: muammo" % r["name"],
                        "fact": "%s. %d kundan beri hal bo'lmagan." % (bl["text"][:70].rstrip("."), bl["age"]), "button": "Mas'ulga eslatish",
                        "action": {"type": "ping_blocker", "project_id": r["id"]}})

    free = sorted((p for p in people if p["state"] in ("idle", "ok", "stuck")), key=lambda p: p["open"])
    used = set()
    for p in people:
        base = {"target": {"type": "person", "name": p["name"]}}
        first = p["name"].split()[0]
        if p["state"] == "overloaded":
            fits = {p["department"]} | ({"Fullstack"} if p["department"] in ("Backend", "Frontend") else set())
            pool = sorted((q for q in free if q["department"] in fits and q["name"] not in used and q["open"] < p["open"] - 3),
                          key=lambda q: (q["department"] != p["department"], q["open"]))
            item = {**base, "id": "u-%s-load" % p["name"], "level": 3, "icon": "fire", "title": "%sning ishi ko'p" % first,
                    "fact": "2 haftada %d ta vazifa berilgan, jamoada o'rtacha %s ta." % (p["assigned14"], _num(p["team_median"]))}
            if pool:
                q = pool[0]
                used.add(q["name"])
                n = max(1, min(5, (p["open"] - q["open"]) // 2))
                ids = [t["id"] for t in sorted(p["open_tasks"], key=lambda t: t["age"])[:n]]
                item.update(button="%d vazifani %sga berish" % (n, q["name"].split()[0]),
                            action={"type": "reassign", "from": p["name"], "to": q["name"], "task_ids": ids})
            out.append(item)
        elif p["state"] == "silent":
            out.append({**base, "id": "u-%s-silent" % p["name"], "level": 3 if p["silent_days"] >= 5 else 2, "icon": "chat-dots",
                        "title": "%s %d kundan beri jim" % (first, p["silent_days"]),
                        "fact": "%d ta ochiq vazifa, oxirgi xabar %s." % (p["open"], uz_date(_d(p["last_activity"]))),
                        "button": "Shaxsan eslatish" if p.get("dm") else "Guruhda holatini so'rash",
                        "action": {"type": "ping_person", "name": p["name"]}})
    out.sort(key=lambda d: -d["level"])
    return out


def person_detail(name: str, period: str = "week", start: str | None = None,
                  end: str | None = None, chat_id: int | None = None, now: datetime | None = None,
                  project_ids: set[int] | None = None) -> dict | None:
    now = now or conf.now()
    data = compute(period, start, end, chat_id=chat_id, now=now, project_ids=project_ids)
    person = next((p for p in data["people"] if p["name"] == name), None)
    if person is None:
        return None
    a, b = date.fromisoformat(data["period"]["from"]), date.fromisoformat(data["period"]["to"])
    snap = Snapshot(now, chat_id, project_ids=project_ids)
    mine = [t for t in snap.tasks if t["assignee"] == name]
    done = sorted(({"title": t["title"], "project": snap.project_names.get(t["project_id"]), "done_at": t["done_at"],
                    "days": round(_days(t["created_at"], t["done_at"]), 1)}
                   for t in mine if _in(t["done_at"], _ts(a), _ts(b, True))), key=lambda x: x["done_at"], reverse=True)[:25]
    series = []
    for i in range(13, -1, -1):
        d = snap.today - timedelta(days=i)
        series.append({"label": "%s %02d.%02d" % (WEEKDAYS_UZ[d.weekday()], d.day, d.month), "weekend": d.weekday() >= 5,
                       "done": sum(_in(t["done_at"], _ts(d), _ts(d, True)) for t in mine)})
    team = [p for p in data["people"] if p["score"] is not None]
    avg = {k: round(sum(p[k] or 0 for p in team) / len(team)) if team else None for k in ("completion", "regular")}
    return {"person": person, "done_tasks": done, "series": series, "period": data["period"],
            "team_avg": avg, "departments": departments()}


def project_detail(pid: int, period: str = "week", start: str | None = None,
                   end: str | None = None, now: datetime | None = None, project_ids: set[int] | None = None) -> dict | None:
    now = now or conf.now()
    data = compute(period, start, end, project_id=pid, now=now)
    if not data["projects"]:
        return None
    snap = Snapshot(now, project_id=pid)
    open_tasks = sorted(({"id": t["id"], "title": t["title"], "assignee": t["assignee"],
                          "giver": t["giver"] if t["giver"] and t["giver"] != t["assignee"] else None,
                          "age": (snap.today - _d(t["created_at"])).days, **_due(t, snap.today)}
                         for t in snap.tasks if t["status"] == "open"),
                        key=lambda t: -t["age"])
    load = defaultdict(lambda: {"open": 0, "done": 0})
    a, b = data["period"]["from"], data["period"]["to"]
    for t in snap.tasks:
        if t["assignee"]:
            if t["status"] == "open":
                load[t["assignee"]]["open"] += 1
            if _in(t["done_at"], _ts(date.fromisoformat(a)), _ts(date.fromisoformat(b), True)):
                load[t["assignee"]]["done"] += 1
    team = sorted(({"name": n, **v} for n, v in load.items()), key=lambda x: -(x["open"] + x["done"]))
    return {"project": data["projects"][0], "series": data["series"], "team": team, "open_tasks": open_tasks,
            "team_progress": team_progress(snap), "period": data["period"]}


def team_progress(snap: Snapshot) -> list[dict]:
    """Loyihada kim qaysi vazifani qay darajada bajargan: jami, bajarilgan, ochiq, muddati o'tgan, o'rtacha muddat, o'z vaqtida."""
    today = snap.today.isoformat()
    by_person: dict[str, list[dict]] = defaultdict(list)
    for t in snap.tasks:
        by_person[t["assignee"] or "Mas'ulsiz"].append(t)
    out = []
    for name, ts in by_person.items():
        done = [t for t in ts if t["status"] == "done"]
        with_dl = [t for t in done if t["deadline"]]
        cycles = [_days(t["created_at"], t["done_at"]) for t in done]
        out.append({
            "name": name, "total": len(ts), "done": len(done), "open": len(ts) - len(done),
            "overdue": sum(1 for t in ts if t["status"] == "open" and t["deadline"] and t["deadline"] < today),
            "pct": round(100 * len(done) / len(ts)) if ts else None,
            "avg_days": round(sum(cycles) / len(cycles), 1) if cycles else None,
            "on_time": round(100 * sum(1 for t in with_dl if t["done_at"][:10] <= t["deadline"]) / len(with_dl)) if with_dl else None,
            "tasks": [{"id": t["id"], "title": t["title"], "status": t["status"], "deadline": t["deadline"],
                       "created_at": t["created_at"], "done_at": t["done_at"]}
                      for t in sorted(ts, key=lambda t: (t["status"] == "done", t["created_at"]))][:200],
        })
    out.sort(key=lambda x: (-x["total"], x["name"]))
    return out


def feed(chat_id: int | None = None, now: datetime | None = None, limit: int = 30, project_ids: set[int] | None = None) -> list[dict]:
    now = now or conf.now()
    qs = (Message.objects.exclude(kind="none").filter(date__lte=now).order_by("-date", "-id")
          .values("id", "date", "text", "kind", "source", "items", "project_id", project_name=F("project__name"), author=F("user__name"),
                  department=F("user__department__name"), chat_title=F("chat__title"), chat_demo=F("chat__demo")))
    if chat_id:
        qs = qs.filter(chat_id=chat_id)
    if project_ids is not None:
        qs = qs.filter(project_id__in=project_ids)
    out = []
    for d in qs[:limit]:
        d["date"] = _s(d["date"])
        d["text"] = (d["text"] or "")[:240]
        d["project"], d["chat"], d["demo"] = d.pop("project_name"), d.pop("chat_title"), int(bool(d.pop("chat_demo")))
        out.append(d)
    return out


def timeline_bounds() -> dict:
    first = Message.objects.order_by("date").values_list("date", flat=True).first()
    return {"first": (first.date() if first else conf.now().date()).isoformat(), "today": conf.now().date().isoformat()}


def digest_text(now: datetime | None = None, chat_id: int | None = None, morning: bool = False) -> str:
    """Telegram uchun qisqa brifing (emoji yo'q, faqat kerakli fakt)."""
    now = now or conf.now()
    data = compute("day" if not morning else "week", chat_id=chat_id, now=now)
    k = data["kpi"]
    head = "Ertalabki brifing" if morning else "Kun yakuni"
    lines = ["<b>%s, %s</b>" % (head, uz_date(now.date())), ""]
    if not data["projects"]:
        return "\n".join(lines + ["Hali loyiha yo'q. Guruhda #task #LoyihaNomi bilan yozing."])
    if morning:
        lines.append("So'nggi 7 kun: %d ta yangi vazifa, %d tasi bajarildi." % (k["created"], k["done"]))
    else:
        lines.append("Bugun: %d ta yangi vazifa, %d tasi bajarildi." % (k["created"], k["done"]))
    lines.append("Loyihalar: %d, xavf ostida %d. Xodimlar: %d, ishi ko'p %d, jim %d." % (
        k["projects_total"], k["at_risk"], len(data["people"]), k["overloaded"], k["silent"]))
    dec = [d for d in data["decisions"] if d["level"] >= 3][:4]
    if dec:
        lines += ["", "<b>Qaroringiz kerak:</b>"]
        for i, d in enumerate(dec, 1):
            lines.append("%d. %s. %s" % (i, _esc(d["title"]), _esc(d["fact"])))
    else:
        lines += ["", "Aralashuv talab qiladigan masala yo'q."]
    if k["idle"]:
        idle = [p["name"] for p in data["people"] if p["state"] == "idle"]
        lines += ["", "Bo'sh, ish berish mumkin: " + ", ".join(_esc(n) for n in idle[:4])]
    return "\n".join(lines)


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
