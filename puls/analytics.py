"""Hisob-kitob: davr ko'rsatkichlari, loyihalar, xodimlar, bo'limlar, Puls indeksi, qarorlar.

Barcha chegaralar sozlamalardan olinadi (settings.py) — kodga qotirib yozilmaydi.
"Vaqt mashinasi": now o'tgan sana bo'lsa, ma'lumot o'sha paytdagi holatga qaytariladi.
"""
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from statistics import median

from . import config, db, settings

FMT = "%Y-%m-%d %H:%M:%S"
MONTHS_UZ = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"]
WEEKDAYS_UZ = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
LEVEL_NAMES = {4: "kritik", 3: "yuqori", 2: "orta", 1: "past", 0: "yaxshi"}
STATUS_LABELS = {4: "Kechikdi", 3: "Xavf ostida", 2: "E'tibor kerak", 1: "Kuzatuvda", 0: "Rejada"}
PERIOD_LABELS = {"day": "Bugun", "week": "So'nggi 7 kun", "month": "So'nggi 30 kun"}
PROJECT_HEALTH = {0: 100, 1: 85, 2: 65, 3: 35, 4: 10}
TEAM_HEALTH = {"ok": 1.0, "idle": 0.8, "stuck": 0.5, "silent": 0.3, "overloaded": 0.3}
STATES = {"overloaded": "Ishi ko'p", "silent": "Hisobot yo'q", "stuck": "Kechikyapti", "idle": "Bo'sh", "ok": "Yaxshi"}


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
    """Vaqt mashinasi: o'tgan kun tanlansa — o'sha kunning oxiri (23:59: muddatdan keyin yozilgan kechikkan hisobotlar ham
    kiradi), bugun yoki bo'sh bo'lsa — hozir."""
    real = config.now()
    if not asof:
        return real
    d = date.fromisoformat(asof)
    if d >= real.date():
        return real
    return datetime.combine(d, time(23, 59, 59))


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


class Snapshot:
    """Tanlangan doiradagi (guruh/loyiha) ma'lumot — kerak bo'lsa o'tgan sanadagi holatga qaytarilgan."""

    def __init__(self, conn: sqlite3.Connection, now: datetime, chat_id: int | None = None, project_id: int | None = None,
                 scope: set[int] | None = None, dept: str | None = None):
        self.now, self.NOW = now, now.strftime(FMT)
        self.today = now.date()
        # yordam guruhidan ochilgan tizim (ish guruhi yo'q) ish tahlilida ko'rinmaydi: uning murojaatlari alohida bo'limda
        where, args = ["(p.created_at IS NULL OR p.created_at <= ?)", "coalesce(p.yordam, 0) = 0"], [self.NOW]
        if chat_id:
            where.append("p.chat_id = ?"); args.append(chat_id)
        if project_id:
            where.append("p.id = ?"); args.append(project_id)
        if scope is not None:  # loyiha menejeri: faqat o'ziga biriktirilgan loyihalar
            where.append("p.id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL"))
        self.projects = [dict(r) for r in conn.execute(
            "SELECT p.*, c.title AS chat_title, c.demo AS demo FROM projects p LEFT JOIN chats c ON c.id = p.chat_id WHERE "
            + " AND ".join(where), args)]
        pids = [p["id"] for p in self.projects]
        marks = ",".join("?" * len(pids)) or "NULL"
        self.tasks = []
        # giver: vazifani yozgan kishi. Xodim hali qabul qilmagan taklif vazifalar hisobga kirmaydi
        # done_deleted: bajarildi deb yozilgan xabar keyin o'chirilgan (akkaunt orqali ulanganda ma'lum bo'ladi)
        for r in conn.execute(f"SELECT t.*, pe.name AS giver, dm.deleted_at AS done_deleted FROM tasks t "
                              f"LEFT JOIN messages m ON m.id = t.created_msg LEFT JOIN people pe ON pe.id = m.user_id "
                              f"LEFT JOIN messages dm ON dm.id = t.done_msg WHERE t.project_id IN ({marks}) AND t.created_at <= ? "
                              f"AND t.status != 'taklif'", pids + [self.NOW]):
            t = dict(r)
            if t["done_at"] and t["done_at"] > self.NOW:
                t["status"], t["done_at"] = "open", None
            self.tasks.append(t)
        self.blockers = []
        for r in conn.execute(f"SELECT * FROM blockers WHERE project_id IN ({marks}) AND created_at <= ?", pids + [self.NOW]):
            x = dict(r)
            if x["resolved_at"] and x["resolved_at"] > self.NOW:
                x["resolved_at"] = None
            self.blockers.append(x)
        sql = ("SELECT m.id, m.project_id, m.chat_id, m.date, m.kind, m.user_id, m.report_day, m.holat, pe.name FROM messages m "
               "LEFT JOIN people pe ON pe.id = m.user_id WHERE m.date <= ? AND m.kind != 'none'")
        margs: list = [self.NOW]
        if chat_id:
            sql += " AND m.chat_id = ?"; margs.append(chat_id)
        if project_id:
            sql += " AND m.project_id = ?"; margs.append(project_id)
        if scope is not None:
            sql += " AND m.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
        self.messages = [dict(r) for r in conn.execute(sql, margs)]
        self.people = {r["name"]: dict(r) for r in conn.execute(
            "SELECT id, name, username, department, dm_chat_id, role, status FROM people")}
        # Guruh a'zolari (chat_id -> ismlar): qo'shilgan, lekin hali yozmagan odam ham jamoada va "yozmadi"da ko'rinadi
        self.members: dict[int, set[str]] = defaultdict(set)
        chats = sorted({p["chat_id"] for p in self.projects if p["chat_id"] and not p.get("demo")})
        if chats:
            for r in conn.execute("SELECT m.chat_id, pe.name FROM members m JOIN people pe ON pe.id = m.user_id WHERE m.left_at IS NULL "
                                  "AND m.joined_at <= ? AND m.chat_id IN (%s)" % ",".join("?" * len(chats)), [self.NOW] + chats):
                self.members[r["chat_id"]].add(r["name"])
        outsiders = {n for n, p in self.people.items() if p.get("status") == "begona"}
        if outsiders:  # rahbar "begona" degan odamlar hech qayerda hisobga olinmaydi
            self.tasks = [t for t in self.tasks if t["assignee"] not in outsiders]
            self.messages = [m for m in self.messages if m["name"] not in outsiders]
            for c in self.members:
                self.members[c] -= outsiders
        if dept:  # bo'lim paneli: faqat shu bo'lim xodimlari, ularning ishlari va ular ishlayotgan loyihalar
            members = {n for n, p in self.people.items() if (p["department"] or "Belgilanmagan") == dept}
            self.tasks = [t for t in self.tasks if t["assignee"] in members]
            keep = {t["project_id"] for t in self.tasks}
            self.projects = [p for p in self.projects if p["id"] in keep]
            self.blockers = [b for b in self.blockers if b["project_id"] in keep]
            self.messages = [m for m in self.messages if m["name"] in members]
            for c in self.members:
                self.members[c] &= members
        self.project_names = {p["id"]: p["name"] for p in self.projects}


def compute(conn: sqlite3.Connection, period: str = "week", start: str | None = None, end: str | None = None,
            chat_id: int | None = None, project_id: int | None = None, now: datetime | None = None,
            scope: set[int] | None = None, dept: str | None = None) -> dict:
    S = settings.load(conn)
    now = now or config.now()
    snap = Snapshot(conn, now, chat_id, project_id, scope, dept)
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
    since14 = _ts(today - timedelta(days=13))
    # faqat topshiriq berib turgan rahbar loyihaning "yozganlari" qatoriga kirmaydi (o'zi ishlasa kiradi)
    bosses = boss_names(snap.people)
    from . import appeals
    ap_counts = appeals.project_counts(conn, now)  # shu tizimga yordam guruhi va chatbotdan kelgan murojaatlar (30 kun)
    rows = []
    for p in snap.projects:
        pts = by_project[p["id"]]
        created = [t for t in pts if _in(t["created_at"], A, B)]
        done_period = [t for t in pts if _in(t["done_at"], A, B)]
        pct = round(100 * sum(t["status"] == "done" for t in created) / len(created)) if created else None
        people = Counter()
        for t in created + done_period:
            if t["assignee"] and t["assignee"] not in bosses:  # rahbar joylagan namuna hisobot "yozdi" emas
                people[t["assignee"]] += 1
        for m in msgs_by[p["id"]]:
            if _in(m["date"], A, B) and m["name"] and m["name"] not in bosses:
                people[m["name"]] += 0
        # Shu guruhda oxirgi 2 haftada yozib turganlar: davrda yozmaganlari "yozmadi" bo'lib ko'rinadi (asosan "Bugun" uchun)
        regulars = {t["assignee"] for t in pts if t["assignee"] and max(t["created_at"] or "", t["done_at"] or "") >= since14}
        regulars |= {m["name"] for m in msgs_by[p["id"]] if m["name"] and m["date"] >= since14}
        if p["chat_id"] and len([q for q in snap.projects if q["chat_id"] == p["chat_id"]]) == 1:
            regulars |= snap.members.get(p["chat_id"], set())  # guruh = loyiha: a'zo yozmasa ham "yozmadi"
        absent = sorted(regulars - bosses - set(people))
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
        muammo = [x for x in open_blockers if (x.get("kind") or "muammo") != "murojaat"]
        muroj = [x for x in open_blockers if x.get("kind") == "murojaat"]
        for x in muammo:
            age = (today - _d(x["created_at"])).days
            risks.append(_risk(3 if age >= S["blocker_high_days"] else 2, "blocker", "Muammo: %s (%d kun)" % (x["text"][:80], age)))
        muroj_old = max(((today - _d(x["created_at"])).days for x in muroj), default=0)
        if muroj:
            risks.append(_risk(3 if len(muroj) >= 3 or muroj_old >= 2 else 2, "requests",
                               "%d ta ochiq so'rov, eng eskisi %d kun" % (len(muroj), muroj_old)))
        recent = Counter(t["assignee"] for t in pts if t["created_at"] >= _ts(today - timedelta(days=29)) and t["assignee"])
        if sum(recent.values()) >= 6:
            name, top = recent.most_common(1)[0]
            share = top / sum(recent.values())
            if share >= S["bus_share"] / 100:
                risks.append(_risk(1, "bus", "Ishning %d foizi bitta odamda: %s" % (round(share * 100), name)))

        # Boshqaruv sahifasi uchun: jamoa, murojaatlar, reja, kechikkan hisobot, holat va 10 ish kunlik hisobot matritsasi
        team = regulars - bosses
        mine_b = blockers_by[p["id"]]
        plan = [t for t in pts if t.get("plan_day") and a.isoformat() <= t["plan_day"] <= b.isoformat()]
        # hisobot: bo'limli hisobot (report_day bor) yoki, eski/erkin xabarlarda, bajarilgan ish haqidagi xabar o'z kuni uchun
        reports = [m for m in msgs_by[p["id"]] if _in(m["date"], A, B) and m["name"] and m["name"] not in bosses and _rday(m)]
        first = {}
        for m in sorted(reports, key=lambda m: m["date"]):
            first.setdefault((m["name"], _rday(m)), m)
        late_reports = sorted({k[0] for k, m in first.items() if m["date"] > "%s %s:00" % (k[1], S["report_deadline"])})
        holat = {}
        for m in sorted(reports, key=lambda m: m["date"]):
            if m.get("holat"):
                holat[m["name"]] = m["holat"]
        wrote_by_day = defaultdict(set)
        for m in msgs_by[p["id"]]:
            if m["name"] and m["name"] not in bosses and m["kind"] != "none":
                wrote_by_day[m.get("report_day") or m["date"][:10]].add(m["name"])
        for t in pts:
            if t["done_at"] and t["assignee"] and t["assignee"] not in bosses:
                wrote_by_day[t["done_at"][:10]].add(t["assignee"])
        # guruh kuzatila boshlanmagan kunlar (bot qo'shilishidan oldin, tarix import qilinmagan) — "kuzatuv yo'q", qizil emas
        began = min([(p["created_at"] or snap.NOW)[:10]] + [m["date"][:10] for m in msgs_by[p["id"]]]
                    + [t["created_at"][:10] for t in pts])
        days10, d = [], b
        while len(days10) < 10:
            if d.weekday() < 5:
                k = d.isoformat()
                days10.append([k, len(wrote_by_day.get(k, set())), len(team) if k >= began else 0])
            d -= timedelta(days=1)
        days10.reverse()
        silent_days = _workdays_between(_d(last), today) if last else None
        stalled = [t for t in pts if t["status"] == "open" and t.get("stage") == "jarayon"
                   and _days(t.get("accepted_at") or t["created_at"], _ts(today)) >= 3]
        if not team and not pts:
            pstate = "yangi"
        elif len(muroj) >= 3 or (muroj and muroj_old >= 2):
            pstate = "kritik"
        elif late or stalled or any(r["level"] >= 3 for r in risks if r["code"] in ("overdue", "deadline", "forecast")):
            pstate = "kechikyapti"
        elif team and (silent_days is None or silent_days >= 2):
            pstate = "jim"
        else:
            pstate = "yaxshi"

        rows.append({
            "pstate": pstate, "team": sorted(team), "team_count": len(team), "days10": days10,
            "requests_open": len(muroj), "requests_oldest": muroj_old,
            "requests_new": sum(1 for x in mine_b if x.get("kind") == "murojaat" and _in(x["created_at"], A, B)),
            "requests_closed": sum(1 for x in mine_b if x.get("kind") == "murojaat" and x["resolved_at"] and _in(x["resolved_at"], A, B)),
            "request_list": [{"text": x["text"], "author": x["author"], "age": (today - _d(x["created_at"])).days} for x in muroj],
            "problems_open": len(muammo),
            "plan_total": len(plan), "plan_done": sum(1 for t in plan if t["done_at"] and t["done_at"][:10] <= t["plan_day"]),
            "plan_missed": [{"title": t["title"], "who": t["assignee"], "day": t["plan_day"]} for t in plan
                            if not (t["done_at"] and t["done_at"][:10] <= t["plan_day"]) and t["plan_day"] < today.isoformat()][:20],
            "late_reports": late_reports, "holat": holat, "stalled": len(stalled),
            # loyiha jarayoni bir qarashda: eng og'ir bajarilgan ishlar, jarayondagilar va keyingi ish kuni rejasi
            "done_top": [{"title": t["title"], "who": t["assignee"], "weight": t.get("weight")} for t in
                         sorted((t for t in done_period if _real(t, bosses)), key=lambda t: (-(t.get("weight") or 0), t["done_at"]))[:3]],
            "doing_n": sum(1 for t in pts if t["status"] == "open" and t.get("stage") == "jarayon" and t["assignee"] not in bosses),
            "doing_top": next((t["title"] for t in sorted(pts, key=lambda t: t["created_at"], reverse=True)
                               if t["status"] == "open" and t.get("stage") == "jarayon" and t["assignee"] not in bosses), None),
            "plan_next": sum(1 for t in pts if t.get("plan_day") and t["plan_day"] > b.isoformat() and t["status"] == "open"),
            # davr oxirgi kuni haqidagi birinchi hisobotlar vaqti: "Hisobot yuborilgan vaqt" grafigi uchun
            "report_times": sorted(({"name": k[0], "at": m["date"][11:16], "on": m["date"][:10],
                                     "late": m["date"] > "%s %s:00" % (k[1], S["report_deadline"])}
                                    for k, m in first.items() if k[1] == b.isoformat()), key=lambda x: (x["on"], x["at"])),
            "msgs7": sum(1 for m in msgs_by[p["id"]] if m["date"] >= week_ago),
            "members_count": len(snap.members.get(p["chat_id"], ())) if p["chat_id"] else 0,
            "repeats": sum(1 for t in done_period if t.get("dup_kind") in REPEAT_KINDS and t["assignee"] not in bosses),  # rahbar joylagan nusxa xodim xatosi emas
            "appeals": ap_counts.get(p["id"]),
            "id": p["id"], "key": p["key"], "name": p["name"], "chat_id": p["chat_id"], "chat_title": p["chat_title"],
            "demo": bool(p["demo"]),
            # bajarilgan ish: qayta yozilgan yoki boshqaning hisobotidan ko'chirilgan band va rahbar joylagan namuna sanalmaydi
            "created": len(created), "done": sum(1 for t in done_period if _real(t, bosses)), "pct": pct,
            "created_prev": sum(_in(t["created_at"], PA, PB) for t in pts),
            "done_prev": sum(1 for t in pts if _in(t["done_at"], PA, PB) and _real(t, bosses)),
            "people": [n for n, _ in people.most_common()], "people_count": len(people), "absent": absent,
            "total": total, "done_total": done_total, "open_total": open_total, "progress": progress,
            "velocity": round(velocity, 2),
            "deadline": p["deadline"], "deadline_label": uz_date(deadline) if deadline else None, "days_left": days_left,
            "eta_days": eta, "eta_date": eta_date.isoformat() if eta_date else None, "eta_label": uz_date(eta_date) if eta_date else None,
            "late_days": (eta - days_left) if (eta is not None and days_left is not None and eta > days_left) else 0,
            "start_date": min([t["created_at"][:10] for t in pts] or [(p["created_at"] or snap.NOW)[:10]]),
            "last_activity": last,
            "blocker_list": [{"text": x["text"], "age": (today - _d(x["created_at"])).days, "kind": x.get("kind") or "muammo",
                              "author": x["author"]} for x in open_blockers],
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
    done_in = [t for t in tasks if _in(t["done_at"], A, B) and _real(t, bosses)]
    prev_done = [t for t in tasks if _in(t["done_at"], PA, PB) and _real(t, bosses)]
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
        "now": snap.NOW, "historic": now < config.now() - timedelta(minutes=2), "today_label": uz_date(today),
        "kpi": kpi,
        "spark": _spark(tasks, today),
        "pulse": pulse(rows, people, tasks, today),
        "heartbeat": heartbeat([dict(r) for r in conn.execute(
            "SELECT date FROM messages WHERE date <= ? AND date >= ?" + (" AND chat_id = ?" if chat_id else ""),
            [snap.NOW, (now - timedelta(hours=24)).strftime(FMT)] + ([chat_id] if chat_id else []))], now),
        "projects": rows,
        "low_activity": low,
        "series": series,
        "people": people,
        "departments": departments,
        "decisions": decisions(rows, people, today),
        "weights": {k: S["w_" + k] for k in ("completion", "output", "speed", "regular", "fresh")},
    }


def _real(t: dict, bosses: set[str]) -> bool:
    """Haqiqiy bajarilgan ish: qayta yozilgan yoki nusxa emas va rahbar joylagan namuna hisobot emas."""
    return t.get("dup_kind") not in REPEAT_KINDS and t.get("assignee") not in bosses


def _rday(m: dict) -> str | None:
    """Xabar qaysi kun hisoboti: bo'limli hisobotda yozilgan kun; hisobot kuni yo'q eski yoki erkin xabarda —
    bajarilgan ish haqidagi xabar yozilgan kuni. Boshqa xabarlar (savol, vazifa, murojaat) hisobot emas."""
    return m.get("report_day") or (m["date"][:10] if m.get("kind") == "done" else None)


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


REPEAT_KINDS = ("takror", "nusxa")


def boss_names(people: dict) -> set[str]:
    """Rahbarlar: panel egasi va "Rahbar" deb belgilanganlar (topshiriq beradi, hisobot bermaydi). Namuna jamoadagi loyiha
    rahbarlari o'zlari ham ishlaydi, ular xodimlar qatorida qoladi."""
    return {n for n, p in people.items() if (config.OWNER_ID and p.get("id") == config.OWNER_ID)
            or (p.get("role") == "rahbar" and not db.is_demo_person(p.get("id")))}
CURRENT_ORDER = {"jarayon": 0, "tekshiruv": 1, "qabul": 2}


def _fake(t: dict) -> bool:
    """Hisobga kirmaydigan ish: eski ish qayta yozilgan yoki hisobot xabari o'chirilgan."""
    return t.get("dup_kind") in REPEAT_KINDS or bool(t.get("done_deleted"))


def _points(t: dict) -> int:
    """Bajarilgan ish og'irligi: til modeli bahosi (1-5); baholanmagan bo'lsa 2 (kichik ish), takror bo'lsa 0."""
    return 0 if _fake(t) else (t.get("weight") or 2)


# ---------------- Reyting ----------------
# Reyting yig'ilib boradigan ball emas, daraja: xodim necha oydan beri ishlayotganidan qat'i nazar hamma bir xil o'lchanadi.
#  * Oyna (Uber "oxirgi 500 safar" kabi): faqat oxirgi 4 hafta. Eski oylar ustunlik bermaydi va ayb ham bo'lmaydi.
#  * Sur'at: hamma narsa "kuniga" — xodim kelgan kundan boshlab kuzatilgan ish kunlariga bo'linadi.
#    Yangi xodim faxriy bilan birinchi haftadan teng solishtiriladi, hech kimga "yetib olish" shart emas.
#  * Ishonch (Glicko/Lichess "taxminiy reyting", aktuariy ishonch nazariyasi): kam kuzatilgan xodim reytingi jamoa
#    o'rtachasidan boshlanadi va har ish kuni o'z natijasi tomon siljiydi; 10 ish kunida to'liq o'ziniki bo'ladi.
#    Birinchi kunlarning tasodifiy omadi yoki omadsizligi uni tepaga ham, pastga ham otib yubormaydi.
#  * Mayda ishlar (Goodhart qonuni): bir kunda 3 tadan ortiq mayda ish chorak hisoblanadi — ro'yxatni uzaytirish foyda bermaydi.
#  * O'rin o'zgarishi (reyting jadvallari): bir hafta oldingi holatga nisbatan, faqat o'sha paytda ham bo'lgan xodimlar orasida.
WINDOW = 28
FULL_DAYS = 10
SMALL_FREE = 3


def _wd(a: date, b: date) -> int:
    """a dan b gacha (ikkalasi ham kiradi) ish kunlari (dushanba-juma) soni."""
    if b < a:
        return 0
    full, rest = divmod((b - a).days + 1, 7)
    return full * 5 + sum(1 for i in range(rest) if (a + timedelta(days=full * 7 + i)).weekday() < 5)


def _day_value(weights: list[int]) -> float:
    """Bir kunlik ish hajmi: mayda ishlar (og'irligi 1) kuniga 3 tagacha to'liq, undan keyingisi chorak."""
    small, total = 0, 0.0
    for w in weights:
        if w <= 1:
            small += 1
            total += w if small <= SMALL_FREE else w / 4
        else:
            total += w
    return total


def _volume(tasks: list[dict], a: str, b: str) -> float:
    """[a, b] oralig'ida bajarilgan ishlar hajmi, har kun alohida hisoblanadi (takror va o'chirilgan hisobotsiz)."""
    days = defaultdict(list)
    for t in tasks:
        if t["done_at"] and a <= t["done_at"] <= b and not _fake(t):
            days[t["done_at"][:10]].append(t.get("weight") or 2)
    return sum(_day_value(ws) for ws in days.values())


def ratings(tasks: list[dict], messages: list[dict], names: set[str], today: date, S: dict) -> dict[str, dict]:
    """Har xodim reytingi (0-100) va tarkibi. Hisob qoidalari yuqorida (Reyting bo'limi)."""
    by = defaultdict(list)
    for t in tasks:
        if t["assignee"] in names:
            by[t["assignee"]].append(t)
    act, first = defaultdict(set), {}
    for m in messages:
        if m["name"] in names:
            act[m["name"]].add(m["date"][:10])
            first[m["name"]] = min(first.get(m["name"], m["date"]), m["date"])
    for name, mine in by.items():
        for t in mine:
            first[name] = min(first.get(name, t["created_at"]), t["created_at"])
            if t["done_at"]:
                act[name].add(t["done_at"][:10])
    tstr, end, fresh_cut = today.isoformat(), _ts(today, True), _ts(today - timedelta(days=1))
    win0, reg0 = today - timedelta(days=WINDOW - 1), today - timedelta(days=13)
    prev0, prev1 = win0 - timedelta(days=WINDOW), win0 - timedelta(days=1)
    stats = {}
    for name in names:
        mine = by.get(name, [])
        joined = _d(first[name]) if name in first else today
        # bugun hali hisobot yozilmagan bo'lsa bugungi kun hisobga kirmaydi: ertalab hamma "ishlamagan" bo'lib qolmasin
        skip = 1 if today.weekday() < 5 and tstr not in act[name] else 0
        start = max(win0, joined)
        days = max(0, _wd(start, today) - skip)
        A = _ts(start)
        made = [t for t in mine if t["created_at"] >= A]
        # endigina berilgan va hali ochiq vazifa bajarish foizini tushirmaydi
        given = [t for t in made if t["status"] == "done" or t["created_at"] < fresh_cut]
        # tezlik faqat oldindan berilgan vazifalardan: hisobotda yozilib darhol yopilgan ish tezlikni ko'rsatmaydi
        cycles = [_days(t["created_at"], t["done_at"]) for t in mine if t["done_at"] and t["done_at"] >= A
                  and not (t.get("created_msg") and t["created_msg"] == t.get("done_msg"))]
        rs = max(reg0, joined)
        rdays = max(0, _wd(rs, today) - skip)
        reported = sum(1 for d in act[name] if d >= rs.isoformat() and date.fromisoformat(d).weekday() < 5)
        opened = [t for t in mine if t["status"] == "open"]
        prev = None
        if joined <= prev0:  # oldingi 4 hafta to'liq kuzatilgan bo'lsagina o'sish/pasayish aytiladi
            pv = _volume(mine, _ts(prev0), _ts(prev1, True))
            prev = (pv / _wd(prev0, prev1), pv)
        stats[name] = {
            "days": days, "made": len(made), "pace": _volume(mine, A, end) / days if days else None, "prev": prev,
            "completion": sum(t["status"] == "done" for t in given) / len(given) if given else None,
            "cycle": sum(cycles) / len(cycles) if cycles else None,
            "regular": min(1.0, reported / rdays) if rdays else None,
            "stale": sum(1 for t in opened if (today - _d(t["created_at"])).days >= S["age_stuck_days"]), "open": len(opened),
            "repeats": sum(1 for t in mine if t["done_at"] and t["done_at"] >= A and t.get("dup_kind") in REPEAT_KINDS),
        }
    paces = [s["pace"] for s in stats.values() if s["pace"]]
    med = median(paces) if paces else 0
    W = {k: S["w_" + k] for k in ("completion", "output", "speed", "regular", "fresh")}
    base = {}
    for name, s in stats.items():
        if s["made"] < 3 or not s["days"]:
            continue
        c = s["cycle"]
        v = {"completion": s["completion"],
             "output": min(1.0, (s["pace"] or 0) / (1.25 * med)) if med else 0.5,
             "speed": None if c is None else 1.0 if c <= 1 else 0.0 if c >= 6 else (6 - c) / 5,
             "regular": None if s["regular"] is None else min(1.0, s["regular"] * 1.25),
             "fresh": 1 - s["stale"] / s["open"] if s["open"] else 1.0}
        have = [k for k in W if v[k] is not None and W[k] > 0]
        if have:  # ma'lumoti yo'q qism (masalan, oldindan berilgan vazifa yo'q — tezlik) hisobga kirmaydi
            s["parts"] = {k: round(W[k] * v[k]) if v[k] is not None else None for k in W}
            base[name] = 100 * sum(W[k] * v[k] for k in have) / sum(W[k] for k in have)
    full = [b for n, b in base.items() if stats[n]["days"] >= FULL_DAYS] or list(base.values())
    M = median(full) if full else 0
    out = {}
    for name, s in stats.items():
        z = min(1.0, math.sqrt(s["days"] / FULL_DAYS))
        penalty = min(30, s["repeats"] * S["repeat_penalty"])
        score = parts = None
        if name in base:  # jarima ishonchga bog'liq emas: yangi xodim ham eski ishni qayta yozsa to'liq jazolanadi
            score = max(0, min(100, round(M + z * (base[name] - M) - penalty)))
            parts = {**s["parts"], "penalty": -penalty}
        pace, prev = s["pace"], s["prev"]
        out[name] = {
            "score": score, "parts": parts, "days": s["days"], "new": s["days"] < FULL_DAYS,
            "pace": round(pace, 2) if pace is not None else None,
            "pace_ratio": round(pace / med, 2) if pace is not None and med else None,
            "pace_prev": round(prev[0], 2) if prev else None, "volume_prev": prev[1] if prev else 0,
            "trend": max(-99, min(300, round(100 * (pace - prev[0]) / prev[0])))
            if prev and prev[1] >= 8 and prev[0] and pace is not None else None,
            "completion": round(100 * s["completion"]) if s["completion"] is not None else None,
            "cycle": round(s["cycle"], 1) if s["cycle"] is not None else None,
            "regular": round(100 * s["regular"]) if s["regular"] is not None else None,
            "stale": s["stale"], "repeats": s["repeats"],
        }
    return out


GROWTH_LABELS = {"ancha_osdi": "Ancha o'sdi", "osdi": "O'sdi", "barqaror": "Barqaror", "pasaydi": "Pasaydi"}


def _growth(g: dict) -> dict | None:
    """Oxirgi 2 hafta oldingi 2 haftaga nisbatan: ish hajmi (kuniga), ish og'irligi, muntazamlik va halollik (eski ishni qayta
    yozish) qanday o'zgardi. "Oldin eski ishni qayta yozardi, endi yozmayapti" — eng muhim yaxshilanish: bunday xodimning
    motivatsiyasini yo'qotmaslik uchun rahbar uni ko'radi va rahmat aytadi. Oldingi davr kuzatilmagan bo'lsa (yangi xodim) — None."""
    if not g["observed"]:
        return None
    pts, why = 0, []
    if g["pace_prev"] and g["pace_now"] is not None and g["vol_prev"] >= 6:
        t = round(100 * (g["pace_now"] - g["pace_prev"]) / g["pace_prev"])
        if abs(t) >= 15:
            pts += (2 if t >= 40 else 1) if t > 0 else (-2 if t <= -40 else -1)
            why.append("ish hajmi %s%d%%" % ("+" if t > 0 else "", max(-99, min(300, t))))
    if g["w_now"] and g["w_prev"] and g["n_now"] >= 4 and g["n_prev"] >= 4:
        dw = g["w_now"] - g["w_prev"]
        if dw >= 0.25:
            pts += 2 if dw >= 0.5 else 1
            why.append("ishlari og'irlashdi: %s dan %s ga" % (_num(g["w_prev"]), _num(g["w_now"])))
        elif dw <= -0.5:
            pts -= 1
            why.append("ishlari yengillashdi: %s dan %s ga" % (_num(g["w_prev"]), _num(g["w_now"])))
    if g["reg_now"] is not None and g["reg_prev"] is not None and abs(g["reg_now"] - g["reg_prev"]) >= 25:
        up = g["reg_now"] > g["reg_prev"]
        pts += 1 if up else -1
        why.append("%s yozyapti: %d%% kunda (oldin %d%%)" % ("muntazamroq" if up else "kamroq", g["reg_now"], g["reg_prev"]))
    if g["reps_before"] >= 2 and g["reps_now"] == 0:
        pts += 2
        why.insert(0, "eski ishni qayta yozishni to'xtatdi (oldin %d marta)" % g["reps_before"])
    elif g["reps_now"] >= 2 and g["reps_before"] == 0:
        pts -= 2
        why.insert(0, "eski ishni qayta yoza boshladi (%d marta)" % g["reps_now"])
    verdict = "ancha_osdi" if pts >= 3 else "osdi" if pts >= 1 else "pasaydi" if pts <= -2 else "barqaror"
    return {"verdict": verdict, "label": GROWTH_LABELS[verdict], "why": why, "points": pts}


def people_view(snap: Snapshot, S: dict, A: str, B: str) -> tuple[list[dict], list[dict]]:
    """Har bir xodim: yuklama, vazifalar yoshi, samaradorlik, holat. Va bo'limlar kesimi."""
    today, tasks = snap.today, snap.tasks
    last: dict[str, str] = {}
    last_chat: dict[str, int] = {}
    for m in snap.messages:
        if m["name"] and m["date"] >= last.get(m["name"], ""):
            last[m["name"]], last_chat[m["name"]] = m["date"], m["chat_id"]
    for t in tasks:
        if t["done_at"] and t["assignee"]:
            last[t["assignee"]] = max(last.get(t["assignee"], ""), t["done_at"])
    info = snap.people
    # Rahbar (OWNER_ID) xodim emas: uning holati, bahosi va "bo'sh" ro'yxati hisoblanmaydi
    head = next((n for n, p in info.items() if config.OWNER_ID and p["id"] == config.OWNER_ID), None)
    # Rahbarlar (egasi va "Rahbar" belgilanganlar) xodim emas: reyting va holat ularga hisoblanmaydi
    bosses = boss_names(info) | ({head} if head else set())
    names = {t["assignee"] for t in tasks if t["assignee"]} - bosses
    # guruhda turgan, lekin hali hech narsa yozmagan odamlar ham jamoada
    names |= {n for ns in snap.members.values() for n in ns} - bosses
    d30, d14 = _ts(today - timedelta(days=29)), _ts(today - timedelta(days=13))
    t0, d28 = _ts(today), _ts(today - timedelta(days=WINDOW - 1))
    by_id = {t["id"]: t for t in tasks}
    R = ratings(tasks, snap.messages, names, today, S)
    # bir hafta oldingi reyting: o'rin o'zgarishi uchun (o'sha paytdagi holatga qaytarilgan nusxada hisoblanadi)
    past = today - timedelta(days=7)
    pn = _ts(past, True)
    R_prev = ratings([t if not (t["done_at"] and t["done_at"] > pn) else {**t, "status": "open", "done_at": None}
                      for t in tasks if t["created_at"] <= pn], [m for m in snap.messages if m["date"] <= pn], names, past, S)

    # tanlangan kun hisoboti: birinchi hisobot vaqti (muddatdan keyin bo'lsa kechikkan) va xodimning o'zi bergan holati
    day_d, rep_first, holat_by = B[:10], {}, {}
    for m in sorted(snap.messages, key=lambda m: m["date"]):
        if m["name"] and _rday(m):
            if _rday(m) == day_d:
                rep_first.setdefault(m["name"], m)
            if A <= m["date"] <= B and m.get("holat"):
                holat_by[m["name"]] = m["holat"]
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
                               "stage": t.get("stage") or "yangi", "progress": t.get("progress") or 0, "flag": t.get("flag"),
                               **_due(t, today)})
        opened.sort(key=lambda x: -x["age"])
        # hozir nima qilyapti: doskada "Jarayonda" bo'lgan vazifa, bo'lmasa tekshiruvdagi, qabul qilingan, eng yangi ochiq
        cur = min(opened, key=lambda o: (CURRENT_ORDER.get(o["stage"], 3), o["age"])) if opened else None
        tdone = sorted((t for t in mine if t["done_at"] and t["done_at"] >= t0), key=lambda t: t["done_at"])
        treal = [t for t in tdone if not _fake(t)]
        # 4 haftalik hisobot sifati: qayta yozilgan (eng oxirgisi misol sifatida), mayda va og'ir ishlar
        w28 = [t for t in mine if t["done_at"] and t["done_at"] >= d28]
        rated28 = [t["weight"] for t in w28 if t.get("weight") and not _fake(t)]
        reps28 = sorted((t for t in w28 if t.get("dup_kind") in REPEAT_KINDS), key=lambda t: t["done_at"])
        ex = reps28[-1] if reps28 else None
        old = by_id.get(ex.get("dup_of")) if ex else None
        per_day = defaultdict(list)
        for t in w28:
            if not _fake(t):
                per_day[t["done_at"][:10]].append(t.get("weight") or 2)
        strip = [[k, round(_day_value(per_day.get(k, [])), 1), len(per_day.get(k, []))]
                 for k in ((today - timedelta(days=i)).isoformat() for i in range(13, -1, -1))]
        usual_days = [_day_value(v) for k, v in per_day.items() if k != today.isoformat()]
        wk = (today - timedelta(days=6)).isoformat()
        joined = min((t["created_at"] for t in mine), default=t0)[:10]
        # o'sish: oxirgi 2 hafta va oldingi 2 hafta (qayta yozish uchun oldingi 4 hafta) — kuzatilgan bo'lsa
        g0, g1, g2 = today - timedelta(days=13), today - timedelta(days=27), today - timedelta(days=41)
        def _win(a, b):
            ts = [t for t in mine if t["done_at"] and _ts(a) <= t["done_at"] <= _ts(b, True)]
            ws = [t["weight"] for t in ts if t.get("weight") and not _fake(t)]
            wd = _wd(max(a, date.fromisoformat(joined)), b)
            days = {t["done_at"][:10] for t in ts if not _fake(t) and _d(t["done_at"]).weekday() < 5}
            vol = _volume(ts, _ts(a), _ts(b, True))
            return {"pace": vol / wd if wd else None, "vol": vol, "w": sum(ws) / len(ws) if ws else None, "n": len(ws),
                    "reg": round(100 * len(days) / wd) if wd else None}
        cur_w, prev_w = _win(g0, today), _win(g1, g0 - timedelta(days=1))
        growth_in = {"observed": joined <= g1.isoformat(), "pace_now": cur_w["pace"], "pace_prev": prev_w["pace"],
                     "vol_prev": prev_w["vol"], "w_now": cur_w["w"], "w_prev": prev_w["w"], "n_now": cur_w["n"], "n_prev": prev_w["n"],
                     "reg_now": cur_w["reg"], "reg_prev": prev_w["reg"],
                     "reps_now": sum(1 for t in mine if t["done_at"] and t["done_at"] >= _ts(g0) and t.get("dup_kind") in REPEAT_KINDS),
                     "reps_before": sum(1 for t in mine if t["done_at"] and _ts(g2) <= t["done_at"] < _ts(g0)
                                        and t.get("dup_kind") in REPEAT_KINDS)}
        overdue = sum(1 for o in opened if o["due_in"] is not None and o["due_in"] < 0)
        recent = [t for t in mine if t["created_at"] >= d30]
        assigned14 = sum(1 for t in mine if t["created_at"] >= d14)
        done_p = [t for t in mine if _in(t["done_at"], A, B)]
        real_p = [t for t in done_p if not _fake(t)]
        rated = [t for t in real_p if t.get("weight")]
        r = R[name]
        last_act = last.get(name)
        person = info.get(name, {})
        rows.append({
            "name": name, "id": person.get("id"), "username": person.get("username"), "dm": bool(person.get("dm_chat_id")),
            "role": person.get("role"),
            "department": person.get("department") or "Belgilanmagan",
            "open": len(opened), "open_tasks": opened, "assigned14": assigned14,
            "created": sum(_in(t["created_at"], A, B) for t in mine), "done": sum(1 for t in mine if _in(t["done_at"], A, B) and t.get("dup_kind") not in REPEAT_KINDS),
            "completion": r["completion"], "cycle": r["cycle"], "regular": r["regular"],
            "stale": r["stale"], "oldest": opened[0]["age"] if opened else 0, "overdue": overdue,
            "last_activity": last_act, "last_chat": last_chat.get(name),
            "silent_days": _workdays_between(_d(last_act), today) if last_act else None,
            "score": r["score"], "score_parts": r["parts"], "evidence": r["days"], "new": r["new"],
            "pace": r["pace"], "pace_ratio": r["pace_ratio"], "pace_prev": r["pace_prev"], "volume_prev": r["volume_prev"],
            "points": round(_volume(mine, A, B), 1), "hours": round(sum(t.get("hours") or 0 for t in real_p), 1),
            "avg_weight": round(sum(t["weight"] for t in rated) / len(rated), 1) if rated else None,
            "small": sum(1 for t in rated if t["weight"] == 1), "rated": len(rated),
            "repeats": sum(1 for t in done_p if t.get("dup_kind") in REPEAT_KINDS), "repeats30": r["repeats"],
            "repeat_list": [{"id": t["id"], "title": t["title"], "kind": t["dup_kind"]} for t in done_p if t.get("dup_kind") in REPEAT_KINDS][:10],
            "trust": round(100 * len(real_p) / len(done_p)) if done_p else None,
            "grade": None,  # nisbiy o'rin bo'yicha pastda yoziladi
            # o'sish/pasayish: kunlik sur'at oldingi 4 haftaga nisbatan (faqat o'sha 4 hafta to'liq kuzatilgan bo'lsa)
            "trend": r["trend"],
            "projects": sorted({snap.project_names[t["project_id"]] for t in recent if t["project_id"] in snap.project_names}),
            "current": {k: cur[k] for k in ("id", "title", "project", "stage", "progress", "age", "flag")} if cur else None,
            "q28": {"items": len(w28), "rated": len(rated28), "small": sum(1 for w in rated28 if w == 1),
                    "avg_weight": round(sum(rated28) / len(rated28), 1) if rated28 else None,
                    "repeats": len(reps28), "copies": sum(1 for t in reps28 if t["dup_kind"] == "nusxa"),
                    "example": {"id": ex["id"], "title": ex["title"], "at": ex["done_at"], "kind": ex["dup_kind"],
                                "old_at": old["done_at"] if old else None,
                                "old_who": old["assignee"] if old and old["assignee"] != name else None} if ex else None},
            # odat: rahbar xodimni o'zining odatdagi ishi bilan solishtiradi ("bu hafta 4 ta, odatda 11")
            "days14": strip, "usual_day": round(median(usual_days), 1) if len(usual_days) >= 3 else None,
            "week_items": sum(len(v) for k, v in per_day.items() if k >= wk),
            "usual_week": round(sum(len(v) for k, v in per_day.items() if k < wk) / 3)
            if joined <= (today - timedelta(days=WINDOW - 1)).isoformat() else None,
            "last_done": max((t["done_at"] for t in mine if t["done_at"]), default=None),
            "growth": _growth(growth_in),
            "report_at": rep_first[name]["date"][11:16] if name in rep_first else None,
            "report_late": bool(name in rep_first and rep_first[name]["date"] > "%s %s:00" % (day_d, S["report_deadline"])),
            "holat": holat_by.get(name),
            "plan_total": sum(1 for t in mine if t.get("plan_day") == day_d),
            "plan_done": sum(1 for t in mine if t.get("plan_day") == day_d and t["done_at"] and t["done_at"][:10] <= day_d),
            "today": {"items": len(tdone), "repeats": sum(1 for t in tdone if t.get("dup_kind") in REPEAT_KINDS),
                      "hours": round(sum(t.get("hours") or 0 for t in treal), 1), "small": sum(1 for t in treal if t.get("weight") == 1),
                      "last": tdone[-1]["title"] if tdone else None, "last_at": tdone[-1]["done_at"] if tdone else None},
        })

    given = [r["assigned14"] for r in rows if r["assigned14"]]
    med = median(given) if given else 0
    for r in rows:
        if r["open"] == 0 and r["last_activity"] is None and not r["last_done"]:
            r["state"], r["fact"] = "silent", "guruhda, hali hech narsa yozmagan"
        elif r["open"] == 0:
            r["state"], r["fact"] = "idle", "ochiq vazifa yo'q"
        elif r["open"] >= S["overload_min_open"] and med and r["assigned14"] >= S["overload_ratio"] * med:
            r["state"], r["fact"] = "overloaded", "2 haftada %d ta vazifa, o'rtachadan %s baravar ko'p" % (r["assigned14"], _num(r["assigned14"] / med))
        elif r["silent_days"] is not None and r["silent_days"] >= S["silent_days"]:
            r["state"], r["fact"] = "silent", "%d ish kunidan beri yozmayapti" % r["silent_days"]
        elif r["overdue"]:
            r["state"], r["fact"] = "stuck", "%d ta vazifa muddati o'tgan" % r["overdue"]
        elif r["oldest"] >= S["stuck_days"]:
            r["state"], r["fact"] = "stuck", "%d kundan beri ochiq vazifa bor" % r["oldest"]
        else:
            r["state"], r["fact"] = "ok", "%d ta ochiq vazifa" % r["open"]
        r["state_label"] = STATES[r["state"]]
        r["team_median"] = med
    rank_people(rows, {n: R_prev[n]["score"] for n in names})
    order = {"overloaded": 0, "silent": 1, "stuck": 2, "ok": 3, "idle": 4}
    rows.sort(key=lambda r: (r["department"], order[r["state"]], -(r["score"] or 0)))

    depts = defaultdict(list)
    for r in rows:
        depts[r["department"]].append(r)
    paces = [r["pace"] for r in rows if r["pace"]]
    med_pace = median(paces) if paces else 0
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
            **dept_quality(ppl, med_pace),
        })
    rank_departments(dept_rows)
    dept_rows.sort(key=lambda d: (d["name"] == "Belgilanmagan", d["name"]))
    return rows, dept_rows


def dept_quality(ppl: list[dict], med_pace: float = 0) -> dict:
    """Bo'lim sifati: bir xodimga kunlik ish hajmi (jamoa o'rtachasiga nisbatan), og'irlik, mayda ishlar, o'sish,
    qayta yozish, eng kuchli xodim. Xodimlar soni ko'p bo'lim ustun chiqmasin — hammasi bir xodimga hisoblanadi."""
    rated = sum(p["rated"] for p in ppl)
    paces = [p["pace"] for p in ppl if p.get("pace") is not None]
    per = sum(paces) / len(paces) if paces else 0
    both = [p for p in ppl if p.get("pace") is not None and p.get("pace_prev")]
    now_s, prev_s = sum(p["pace"] for p in both), sum(p["pace_prev"] for p in both)
    best = min((p for p in ppl if p.get("rank")), key=lambda p: p["rank"], default=None)
    weighted = sum((p["avg_weight"] or 0) * p["rated"] for p in ppl if p["avg_weight"])
    return {
        "per_person": round(per, 2), "pace_ratio": round(per / med_pace, 2) if med_pace and paces else None,
        "avg_weight": round(weighted / rated, 1) if rated else None,
        "small_share": round(100 * sum(p["small"] for p in ppl) / rated) if rated else None,
        "repeats30": sum(p["repeats30"] for p in ppl),
        "trend": max(-99, min(300, round(100 * (now_s - prev_s) / prev_s)))
        if prev_s and sum(p.get("volume_prev") or 0 for p in both) >= 15 else None,
        "best": {"name": best["name"], "rank": best["rank"], "score": best["score"]} if best else None,
    }


def rank_departments(depts: list[dict]) -> None:
    """Bo'limlar o'rni: o'rtacha baho, teng bo'lsa bir xodimga ish hajmi. "Belgilanmagan" reytingga kirmaydi."""
    real = [d for d in depts if d["name"] != "Belgilanmagan" and d["score"] is not None]
    for i, d in enumerate(sorted(real, key=lambda d: (-d["score"], -d["per_person"], d["name"]))):
        d["rank"], d["rank_of"] = i + 1, len(real)
    for i, d in enumerate(sorted(real, key=lambda d: (-d["per_person"], d["name"]))):
        d["out_rank"] = i + 1


def _q(values: list[float], q: float) -> float | None:
    v = sorted(values)
    return v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))] if v else None


def rank_people(rows: list[dict], prev: dict[str, int | None] | None = None) -> None:
    """Nisbiy o'rin: qotirilgan "yaxshi / past" emas, jamoa ichidagi aniq o'rin va foiz. 1000 xodimda ham har biri
    o'z o'rniga ega; belgilar (og'ir ishlar, mayda ishlar, o'sish) ham jamoaning o'ziga nisbatan hisoblanadi.
    prev: bir hafta oldingi reyting — o'rin o'zgarishi faqat o'sha paytda ham bo'lganlar orasida (yangi kelgan xodim
    boshqalarni "pastga surgan" bo'lib ko'rinmasin)."""
    scored = sorted((r for r in rows if r["score"] is not None), key=lambda r: (-r["score"], -(r.get("pace") or 0), r["name"]))
    n = len(scored)
    for i, r in enumerate(scored):
        r["rank"], r["rank_of"] = i + 1, n
        r["top_pct"] = max(1, round(100 * (i + 1) / n))
        r["grade"] = "Eng yaxshi %d%% ichida" % r["top_pct"] if r["top_pct"] <= 50 else "Eng past %d%% ichida" % max(1, 101 - r["top_pct"])
    both = [r for r in scored if prev and prev.get(r["name"]) is not None]
    before = {r["name"]: i for i, r in enumerate(sorted(both, key=lambda r: (-prev[r["name"]], r["name"])))}
    for i, r in enumerate(both):
        r["move"] = before[r["name"]] - i
    groups = defaultdict(list)
    for r in scored:
        groups[r.get("department")].append(r)
    for g in groups.values():
        for i, r in enumerate(g):
            r["dept_rank"], r["dept_rank_of"] = i + 1, len(g)
    by_out = sorted(rows, key=lambda r: (-(r.get("pace") or 0), r["name"]))
    for i, r in enumerate(by_out):
        r["out_rank"] = i + 1
    heavy_q = _q([r["avg_weight"] for r in rows if r["avg_weight"] and r["rated"] >= 5], 0.75)
    out_q = _q([r["pace"] for r in rows if r.get("pace")], 0.9)
    for r in rows:
        traits = []
        if r.get("new") and r.get("evidence"):
            traits.append({"key": "new", "label": "Yangi xodim, %d ish kuni" % r["evidence"], "tone": "ok"})
        if out_q and (r.get("pace") or 0) >= out_q:
            traits.append({"key": "lead", "label": "Ish hajmi bo'yicha eng yaxshi 10% ichida", "tone": "ok"})
        if heavy_q and r["avg_weight"] and r["rated"] >= 5 and r["avg_weight"] >= heavy_q:
            traits.append({"key": "heavy", "label": "Og'ir ishlar qiladi (%s / 5)" % _num(r["avg_weight"]), "tone": "ok"})
        if r["rated"] >= 6 and r["small"] / r["rated"] >= 0.5:
            traits.append({"key": "small", "label": "Ishlarining %d foizi mayda" % round(100 * r["small"] / r["rated"]), "tone": "warn"})
        g = r.get("growth")
        if g and g["verdict"] in ("ancha_osdi", "osdi") and g["why"]:
            traits.append({"key": "grow", "label": "%s: %s" % (g["label"], g["why"][0]), "tone": "ok"})
        elif r["trend"] is not None and r["trend"] <= -30:
            traits.append({"key": "down", "label": "Ish hajmi kamaymoqda, %d%%" % r["trend"], "tone": "warn"})
        if r["repeats30"]:
            traits.append({"key": "repeat", "label": "%d ta ishni qayta yozgan" % r["repeats30"], "tone": "risk"})
        r["traits"] = traits


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
        elif p["state"] == "silent" and p["silent_days"] is not None:  # guruhga endi qo'shilgan, hech yozmagan odam — jamoa ro'yxatida
            out.append({**base, "id": "u-%s-silent" % p["name"], "level": 3 if p["silent_days"] >= 5 else 2, "icon": "chat-dots",
                        "title": "%s %d ish kunidan beri yozmayapti" % (first, p["silent_days"]),
                        "fact": "%d ta ochiq vazifa, oxirgi xabar %s." % (p["open"], uz_date(_d(p["last_activity"]))),
                        "button": "Shaxsan eslatish" if p.get("dm") else "Guruhda holatini so'rash",
                        "action": {"type": "ping_person", "name": p["name"]}})
        # Hisobot haqqoniyligi: eski ish qayta yozilgan yoki hisobot asosan mayda ishlardan iborat
        if p.get("repeats30"):
            out.append({**base, "id": "u-%s-repeat" % p["name"], "level": 3, "icon": "copy",
                        "title": "%s eski ishni qayta yozgan" % first,
                        "fact": "4 haftada %d ta ish oldingi hisobotlarida ham bor: reytingda hisobga olinmadi." % p["repeats30"],
                        "button": "Hisobotini ko'rish", "action": {"type": "open_report", "name": p["name"]}})
        elif p.get("rated", 0) >= 8 and p["small"] / p["rated"] >= 0.6:
            out.append({**base, "id": "u-%s-small" % p["name"], "level": 2, "icon": "graph-down",
                        "title": "%sning ishlari asosan mayda" % first,
                        "fact": "%d ta ishdan %d tasi mayda: o'rtacha og'irlik %s (5 dan)." % (p["rated"], p["small"], _num(p["avg_weight"] or 0)),
                        "button": "Hisobotini ko'rish", "action": {"type": "open_report", "name": p["name"]}})
        # Yaxshi xabar ham qaror: ancha o'sgan xodimga rahbarning bir og'iz rahmati motivatsiyani saqlaydi
        g = p.get("growth")
        if g and g["verdict"] == "ancha_osdi":
            out.append({**base, "id": "u-%s-grow" % p["name"], "level": 1, "icon": "graph-up", "good": True,
                        "title": "%s ancha o'sdi" % first, "fact": "%s." % "; ".join(g["why"][:2]).capitalize(),
                        "button": "Rahmat aytish", "action": {"type": "thank_person", "name": p["name"],
                                                              "why": g["why"][0] if g["why"] else ""}})
    out.sort(key=lambda d: -d["level"])
    return out


def person_detail(conn: sqlite3.Connection, name: str, period: str = "week", start: str | None = None,
                  end: str | None = None, chat_id: int | None = None, now: datetime | None = None,
                  scope: set[int] | None = None, dept: str | None = None) -> dict | None:
    now = now or config.now()
    data = compute(conn, period, start, end, chat_id=chat_id, now=now, scope=scope, dept=dept)
    person = next((p for p in data["people"] if p["name"] == name), None)
    if person is None:
        return None
    a, b = date.fromisoformat(data["period"]["from"]), date.fromisoformat(data["period"]["to"])
    snap = Snapshot(conn, now, chat_id, scope=scope, dept=dept)
    mine = [t for t in snap.tasks if t["assignee"] == name]
    done = sorted(({"title": t["title"], "project": snap.project_names.get(t["project_id"]), "done_at": t["done_at"],
                    "days": round(_days(t["created_at"], t["done_at"]), 1), "weight": t.get("weight"), "hours": t.get("hours"),
                    "wnote": t.get("wnote"), "dup_kind": t.get("dup_kind"), "dup_note": t.get("dup_note")}
                   for t in mine if _in(t["done_at"], _ts(a), _ts(b, True))), key=lambda x: x["done_at"], reverse=True)[:25]
    series = []
    for i in range(13, -1, -1):
        d = snap.today - timedelta(days=i)
        series.append({"label": "%s %02d.%02d" % (WEEKDAYS_UZ[d.weekday()], d.day, d.month), "weekend": d.weekday() >= 5,
                       "done": sum(_in(t["done_at"], _ts(d), _ts(d, True)) for t in mine)})
    team = [p for p in data["people"] if p["score"] is not None]
    avg = {k: round(sum(p[k] or 0 for p in team) / len(team)) if team else None for k in ("completion", "regular")}
    S = settings.load(conn)
    return {"person": person, "done_tasks": done, "series": series, "period": data["period"],
            "team_avg": avg, "departments": db.DEPARTMENTS,
            "weights": {k: S["w_" + k] for k in ("completion", "output", "speed", "regular", "fresh")}}


def project_detail(conn: sqlite3.Connection, pid: int, period: str = "week", start: str | None = None,
                   end: str | None = None, now: datetime | None = None) -> dict | None:
    now = now or config.now()
    data = compute(conn, period, start, end, project_id=pid, now=now)
    if not data["projects"]:
        return None
    snap = Snapshot(conn, now, project_id=pid)
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
    A, B = _ts(date.fromisoformat(a)), _ts(date.fromisoformat(b), True)
    done_list = sorted(({"id": t["id"], "title": t["title"], "who": t["assignee"], "weight": t.get("weight"), "dup": t.get("dup_kind"),
                         "at": t["done_at"]} for t in snap.tasks if _in(t["done_at"], A, B)), key=lambda x: x["at"], reverse=True)[:80]
    return {"project": data["projects"][0], "series": data["series"], "team": team, "open_tasks": open_tasks,
            "done_list": done_list, "period": data["period"]}


def project_feed(conn: sqlite3.Connection, pid: int, until: date, days: int = 14) -> list[dict]:
    """Loyiha guruhidagi ish xabarlari (eng yangisi birinchi): asl matn va bot undan nimani ajratib olgani.
    Bo'limli hisobot qayta o'qiladi (Bajarildi / Jarayonda / Ertangi reja / Bloker); erkin matn bo'lsa — shu xabardan
    yaratilgan yoki yopilgan vazifalar va muammolar. Qayta yozilgan ish va kechikkan hisobot belgisi ham shu yerda."""
    from . import parser
    S = settings.load(conn)
    since = until - timedelta(days=days - 1)
    msgs = [dict(r) for r in conn.execute(
        "SELECT m.id, m.date, m.text, m.kind, m.source, m.holat, m.report_day, m.edited_at, m.deleted_at, pe.name AS author "
        "FROM messages m LEFT JOIN people pe ON pe.id = m.user_id WHERE m.project_id = ? AND m.date >= ? AND m.date <= ? "
        "AND m.kind != 'none' ORDER BY m.date DESC, m.id DESC", (pid, _ts(since), _ts(until, True)))]
    if not msgs:
        return []
    ids = [m["id"] for m in msgs]
    marks = ",".join("?" * len(ids))
    tasks = [dict(r) for r in conn.execute(
        f"SELECT id, title, status, done_at, created_msg, done_msg, progress, stage, plan_day, dup_kind, weight FROM tasks "
        f"WHERE created_msg IN ({marks}) OR done_msg IN ({marks})", ids + ids)]
    blockers = [dict(r) for r in conn.execute(f"SELECT text, kind, msg, resolved_at FROM blockers WHERE msg IN ({marks})", ids)]
    out = []
    for m in msgs:
        mine_done = [t for t in tasks if t["done_msg"] == m["id"]]
        mine_new = [t for t in tasks if t["created_msg"] == m["id"] and t["done_msg"] != m["id"]]
        p = parser.parse_report(m["text"] or "", _d(m["date"]))
        if p and p.sections:
            sec = {k: [{"title": i.title, "progress": i.progress} for i in v] for k, v in p.sections.items()}
        else:
            sec = {}
            if mine_done:
                sec["done"] = [{"title": t["title"], "progress": None} for t in mine_done]
            doing = [t for t in mine_new if t.get("stage") == "jarayon"]
            plan = [t for t in mine_new if t.get("plan_day") and t not in doing]
            rest = [t for t in mine_new if t not in doing and t not in plan]
            if doing:
                sec["doing"] = [{"title": t["title"], "progress": t.get("progress")} for t in doing]
            if plan:
                sec["plan"] = [{"title": t["title"], "progress": None} for t in plan]
            if rest:
                sec["task"] = [{"title": t["title"], "progress": None} for t in rest]
            mb = [x for x in blockers if x["msg"] == m["id"]]
            if mb:
                sec["blocker"] = [{"title": x["text"], "progress": None} for x in mb]
        day = m["report_day"] or m["date"][:10]
        out.append({"id": m["id"], "date": m["date"], "author": m["author"], "text": (m["text"] or "")[:6000],
                    "kind": m["kind"], "source": m["source"], "holat": m["holat"], "day": day,
                    "edited": bool(m["edited_at"]), "deleted": bool(m["deleted_at"]),
                    "late": bool(m["report_day"]) and m["date"] > "%s %s:00" % (day, S["report_deadline"]),
                    "sections": sec,
                    "repeats": [{"id": t["id"], "title": t["title"], "kind": t["dup_kind"]} for t in mine_done if t.get("dup_kind") in REPEAT_KINDS],
                    "requests": sum(1 for x in blockers if x["msg"] == m["id"] and x.get("kind") == "murojaat")})
    return out


def blockers_list(conn: sqlite3.Connection, now: datetime, days: int = 30, scope: set[int] | None = None,
                  dept: str | None = None) -> dict:
    """Muammolar va murojaatlar: hozir ochiqlari hammasi, hal bo'lganlari oxirgi `days` kunda."""
    snap = Snapshot(conn, now, scope=scope, dept=dept)
    today, since = snap.today, _ts(snap.today - timedelta(days=days - 1))
    S = settings.load(conn)

    def row(x):
        a = _d(x["created_at"])
        end = _d(x["resolved_at"]) if x["resolved_at"] else today
        return {"id": x["id"], "project_id": x["project_id"], "project": snap.project_names.get(x["project_id"]),
                "text": x["text"], "kind": x.get("kind") or "muammo", "author": x["author"], "created_at": x["created_at"],
                "resolved_at": x["resolved_at"], "age": (end - a).days,
                "risk": not x["resolved_at"] and (today - a).days >= S["blocker_high_days"]}
    open_ = sorted((row(x) for x in snap.blockers if not x["resolved_at"]), key=lambda r: (-r["age"], r["project"] or ""))
    done = sorted((row(x) for x in snap.blockers if x["resolved_at"] and x["resolved_at"] >= since),
                  key=lambda r: r["resolved_at"], reverse=True)
    return {"open": open_, "resolved": done, "days": days, "high_days": S["blocker_high_days"]}


def feed(conn: sqlite3.Connection, chat_id: int | None = None, now: datetime | None = None, limit: int = 30,
         scope: set[int] | None = None, dept: str | None = None) -> list[dict]:
    now = now or config.now()
    sql = ("SELECT m.id, m.date, m.text, m.kind, m.source, m.items, m.project_id, p.name AS project, pe.name AS author, "
           "pe.department AS department, c.title AS chat, c.demo AS demo FROM messages m "
           "LEFT JOIN projects p ON p.id = m.project_id LEFT JOIN people pe ON pe.id = m.user_id "
           "LEFT JOIN chats c ON c.id = m.chat_id WHERE m.kind != 'none' AND m.date <= ?")
    args: list = [now.strftime(FMT)]
    if chat_id:
        sql += " AND m.chat_id = ?"; args.append(chat_id)
    if scope is not None:
        sql += " AND m.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
    if dept:
        sql += " AND coalesce(pe.department, 'Belgilanmagan') = ?"; args.append(dept)
    sql += " ORDER BY m.date DESC, m.id DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in conn.execute(sql, args):
        d = dict(r)
        d["text"] = (d["text"] or "")[:240]
        out.append(d)
    return out


def timeline_bounds(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT min(date) AS a FROM messages").fetchone()
    first = _d(row["a"]) if row and row["a"] else config.now().date()
    return {"first": first.isoformat(), "today": config.now().date().isoformat()}


def digest_text(conn: sqlite3.Connection, now: datetime | None = None, chat_id: int | None = None, morning: bool = False) -> str:
    """Telegram uchun qisqa brifing (emoji yo'q, faqat kerakli fakt)."""
    now = now or config.now()
    data = compute(conn, "day" if not morning else "week", chat_id=chat_id, now=now)
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
    if chat_id is None:  # guruhdagi /hisobot buyrug'ida emas: murojaatlar faqat rahbar brifingida
        from . import appeals
        ap = appeals.digest_line(conn, now)
        if ap:
            lines.append(_esc(ap))
    dec =[d for d in data["decisions"] if d["level"] >= 3][:4]
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
