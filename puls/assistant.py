"""Rahbar yordamchisi: panel raqamlaridan "bugun nimani bilishingiz kerak" xulosalari va savolga javob.

Model faqat shu yerda yig'ilgan faktlarni ko'radi (xodimlar o'rni va reytingi, o'sish yoki pasayish, qayta yozilgan ishlar,
mayda ishlar, jim qolganlar, xavfli loyihalar, bugungi hisobotlar) va faqat ular asosida yozadi: o'zidan fakt to'qimaydi.
Jamoa katta bo'lsa (1000 xodim) modelga hammasi emas, eng yuqori, eng past va diqqat talab qiladiganlar beriladi.
Xulosalar bir soat keshlanadi; "Yangilash" bosilsa qayta yoziladi. Loyiha menejeri faqat o'z loyihalari doirasini ko'radi.
"""
import json
import logging
import sqlite3
from datetime import timedelta

from . import ai, analytics, config, quality

log = logging.getLogger("puls.assistant")
CACHE_MIN = 60

BRIEF_PROMPT = """You are the personal analyst of the head of an IT center at the Ministry of Justice of Uzbekistan. The head does
not watch the panel all day: he looks once and must immediately understand what is going on. From the facts below write
5 to 8 short insights he must know now, the most important first.

Look for: employees who report old work again (qayta yozilgan), days padded with trivial items (mayda ishlar), who
really carries the team (high daily work volume relative to the team, heavy items), who climbed or dropped in the ranking
this week, who is falling (trend down) or silent, projects at risk and why, who did not report today. Compare people with the
team, not with fixed grades. The ranking is a level, not accumulated points: never talk about points ("ball"). A new employee
(yangi_xodim_ish_kunlari) has a provisional rank: do not judge him by it.

Rules: Uzbek, Latin script, plain words a senior official understands, no English or jargon. Every insight has concrete names
and numbers taken from the facts. Never invent a fact, a name or a number. Do not give generic advice.
title: at most 70 characters. text: one or two sentences. level: 3 critical, 2 needs attention, 1 information, 0 good news.
person / project: the exact name from the facts the insight is about, or null.

Facts (JSON):
{facts}"""

BRIEF_SCHEMA = {
    "type": "OBJECT",
    "properties": {"items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "title": {"type": "STRING"}, "text": {"type": "STRING"}, "level": {"type": "INTEGER"},
        "person": {"type": "STRING", "nullable": True}, "project": {"type": "STRING", "nullable": True}},
        "required": ["title", "text", "level"]}}},
    "required": ["items"],
}

ASK_PROMPT = """You are the personal analyst of the head of an IT center at the Ministry of Justice of Uzbekistan. Answer his
question using only the facts below. Uzbek, Latin script, short (at most 120 words), concrete names and numbers. If the facts
are not enough to answer, say exactly what is missing. Never invent anything.

Answer exactly what was asked, nothing else first. Days: "bugun" is facts.bugun, "kecha" is facts.kecha, a weekday or a date
means that day in facts.kunlar. These are DIFFERENT things, never mix them:
- did not write / did not report / "yozmadi", "hisobot bermadi", "vazifasini yozmadi" = kunlar[day].hisobot_bermaganlar
- wrote old work again / copied / "qayta yozdi", "takror", "eski ishni yozdi" = kunlar[day].qayta_yozganlar
- reported = kunlar[day].hisobot_berganlar
If that day has no entry in facts.kunlar or it is a weekend, say there is no data for that day.

answer: one or two sentences with the counts (for example "22-oktyabr kuni 3 kishi hisobot yozmagan.").
groups: the people lists, each with a short title, for example [{{"title": "Hisobot yozmaganlar, 22-oktyabr", "people": [...]}}].
The group that answers the question comes first. You may add one more clearly titled group if it is directly useful
(for example who wrote old work again on the same day), never under the wrong title. Exact names from the facts only.
projects: exact project names your answer is about, if any.

Question: {question}

Facts (JSON):
{facts}"""

ASK_SCHEMA = {
    "type": "OBJECT",
    "properties": {"answer": {"type": "STRING"},
                   "groups": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                       "title": {"type": "STRING"}, "people": {"type": "ARRAY", "items": {"type": "STRING"}}},
                       "required": ["title", "people"]}},
                   "projects": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["answer"],
}
WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]


def _person(p: dict) -> dict:
    return {k: v for k, v in {
        "ism": p["name"], "bolim": p["department"], "holat": p["state_label"], "fakt": p["fact"],
        "orin": "%s / %s" % (p.get("rank"), p.get("rank_of")) if p.get("rank") else None, "reyting_100": p["score"],
        "bolimdagi_orin": "%s / %s" % (p.get("dept_rank"), p.get("dept_rank_of")) if p.get("dept_rank") else None,
        "haftada_orin_ozgarishi": p.get("move"), "yangi_xodim_ish_kunlari": p["evidence"] if p.get("new") else None,
        "kunlik_ish_hajmi_jamoa_ortachasiga_nisbatan": p.get("pace_ratio"),
        "ish_hajmi_ozgarishi_foiz": p.get("trend"), "taxminiy_soat_7kun": p["hours"], "ortacha_ogirlik_5dan": p["avg_weight"],
        "mayda_ishlar": p["small"], "baholangan_ishlar": p["rated"], "qayta_yozilgan_4hafta": p["repeats30"],
        "ochiq_vazifa": p["open"], "muddati_otgan": p["overdue"], "jim_ish_kunlari": p["silent_days"],
        "belgilar": [t["label"] for t in p.get("traits", [])],
    }.items() if v not in (None, [], "")}


def facts(conn: sqlite3.Connection, scope: set[int] | None = None, extra_people: list[str] | None = None,
          dept: str | None = None) -> dict:
    """Modelga beriladigan faktlar: ixcham, lekin aniq. Katta jamoada ham hajmi cheklangan."""
    data = analytics.compute(conn, "week", scope=scope, dept=dept)
    people = data["people"]
    ranked = sorted((p for p in people if p.get("rank")), key=lambda p: p["rank"])
    pick = {p["name"]: p for p in ranked[:20] + ranked[-15:]}
    for p in people:
        if p["state"] in ("silent", "overloaded", "stuck") or p["repeats30"] or any(t["tone"] != "ok" for t in p.get("traits", [])):
            pick.setdefault(p["name"], p)
    for name in extra_people or []:
        for p in people:
            if p["name"] == name:
                pick.setdefault(name, p)
    chosen = list(pick.values())[:90]
    now = config.now()
    today = now.date().isoformat()
    day = quality.day_report(conn, today, scope, dept)
    since = (now - timedelta(days=14)).strftime("%Y-%m-%d 00:00:00")
    # Oxirgi 7 kun, har kun alohida: kim hisobot yozdi, kim yozmadi, kim eski ishni qayta yozdi.
    # "Kecha kim yozmadi?" kabi savolga model taxmin qilmasin, shu ro'yxatdan javob bersin.
    days = []
    for i in range(7):
        d = (now - timedelta(days=i)).date()
        rep = day if i == 0 else quality.day_report(conn, d.isoformat(), scope, dept)
        miss = quality.missing(conn, d.isoformat(), {p["name"] for p in rep}, scope, dept)
        if not rep and not miss:
            continue
        days.append({"sana": d.isoformat(), "hafta_kuni": WEEKDAYS[d.weekday()],
                     "hisobot_berganlar_soni": len(rep), "hisobot_bermaganlar_soni": len(miss),
                     "hisobot_berganlar": [{"kim": p["name"], "ishlar": p["count"]} for p in rep][:80],
                     "hisobot_bermaganlar": [m["name"] for m in miss][:80],
                     "qayta_yozganlar": [{"kim": p["name"], "nechta_ish": p["repeats"]} for p in rep if p["repeats"]][:80]})
    return {
        "bugun": today, "kecha": (now - timedelta(days=1)).date().isoformat(), "bugun_hafta_kuni": WEEKDAYS[now.weekday()],
        "davr": data["period"]["range_label"],
        "jamoa": {"xodimlar": len(people), "baholangan": len(ranked), "ishi_kop": data["kpi"]["overloaded"],
                  "jim": data["kpi"]["silent"], "bosh": data["kpi"]["idle"], "chozilgan": data["kpi"]["stuck"]},
        "xodimlar": [_person(p) for p in chosen],
        "loyihalar": [{k: v for k, v in {
            "nomi": r["name"], "xavf_darajasi_0_4": r["level"], "bajarilgan_foiz": r["progress"], "ochiq": r["open_total"],
            "muddat": r.get("deadline_label"), "prognoz": r.get("eta_label"),
            "sabablar": [x["text"] for x in r["risks"][:3]]}.items() if v not in (None, [], "")}
            for r in sorted(data["projects"], key=lambda r: -r["level"])[:25]],
        "qayta_yozilgan_ishlar_14kun": [{"kim": x["assignee"], "sana": x["done_at"][:10], "ish": x["title"][:120],
                                         "asl_yozuv": x["old_title"][:120], "necha_kun_oldin": x["gap_days"],
                                         "boshqa_xodimniki": x["dup_kind"] == "nusxa", "izoh": x["dup_note"]}
                                        for x in quality.suspicious(conn, since, scope, dept)[:20]],
        "bugungi_hisobotlar": [{"kim": p["name"], "ishlar": p["count"], "soat": p["hours"],
                                "mayda": p["small"], "belgilar": p["flags"],
                                "ishlar_royxati": [i["title"][:90] + " (%s)" % (i["weight"] or "?") for i in p["items"][:6]]}
                               for p in day[:25]],
        "kunlar": days,
        **({"bolim": dept} if dept else {}),
    }


def _key(scope: set[int] | None, dept: str | None = None) -> str:
    return "assistant:brief:" + (",".join(map(str, sorted(scope))) if scope is not None else "all") + (":" + dept if dept else "")


def brief(conn: sqlite3.Connection, scope: set[int] | None = None, refresh: bool = False, dept: str | None = None) -> dict:
    key = _key(scope, dept)
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    cached = json.loads(row["value"]) if row else None
    now = config.now()
    if cached and not refresh and cached.get("at", "") >= (now - timedelta(minutes=CACHE_MIN)).strftime("%Y-%m-%d %H:%M:%S"):
        return cached
    if not config.ai_enabled():
        return cached or {"at": None, "items": [], "error": "AI o'chiq"}
    f = facts(conn, scope, dept=dept)
    raw = ai._ask(BRIEF_PROMPT.format(facts=json.dumps(f, ensure_ascii=False)), 3, BRIEF_SCHEMA)
    if not raw:
        return cached or {"at": None, "items": [], "error": "Yordamchi hozir javob bermadi, birozdan keyin qayta urinib ko'ring"}
    names = {p["ism"] for p in f["xodimlar"]} | {x["kim"] for x in f["bugungi_hisobotlar"]}
    projects = {p["nomi"] for p in f["loyihalar"]}
    items = []
    for it in raw.get("items") or []:
        items.append({"title": (it.get("title") or "").strip()[:90], "text": (it.get("text") or "").strip()[:400],
                      "level": max(0, min(3, int(it.get("level") or 1))),
                      "person": it.get("person") if it.get("person") in names else None,
                      "project": it.get("project") if it.get("project") in projects else None})
    out = {"at": now.strftime("%Y-%m-%d %H:%M:%S"), "items": [i for i in items if i["title"]][:8]}
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(out, ensure_ascii=False)))
    return out


def ask(conn: sqlite3.Connection, question: str, scope: set[int] | None = None, dept: str | None = None) -> dict:
    question = " ".join((question or "").split())[:500]
    if len(question) < 3:
        raise ValueError("Savolni yozing")
    if not config.ai_enabled():
        raise ValueError("AI o'chiq")
    # Savolda tilga olingan xodim bo'lsa, uning oxirgi 14 kundagi ishlari ham beriladi
    low = question.lower()
    named = [r["name"] for r in conn.execute("SELECT name FROM people WHERE name IS NOT NULL")
             if any(len(w) >= 3 and w.lower() in low for w in r["name"].split())]
    f = facts(conn, scope, named[:5], dept)
    if named:
        since = (config.now() - timedelta(days=14)).strftime("%Y-%m-%d 00:00:00")
        sc = "" if scope is None else " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
        f["tilga_olingan_xodimlar_ishlari_14kun"] = {n: [
            {"sana": r["done_at"][:10], "ish": r["title"][:120], "ogirlik_5dan": r["weight"], "soat": r["hours"], "takror": r["dup_kind"]}
            for r in conn.execute("SELECT t.title, t.done_at, t.weight, t.hours, t.dup_kind FROM tasks t WHERE t.assignee = ? "
                                  "AND t.status = 'done' AND t.done_at >= ?" + sc + " ORDER BY t.done_at DESC LIMIT 40", (n, since))]
            for n in named[:5]}
    raw = ai._ask(ASK_PROMPT.format(question=question, facts=json.dumps(f, ensure_ascii=False)), 3, ASK_SCHEMA)
    if not raw:
        raise ValueError("Yordamchi hozir javob bermadi, birozdan keyin qayta urinib ko'ring")
    # faqat bazada bor ismlar qoladi: model ism to'qib qo'shsa ham panelga chiqmaydi
    known = {r["name"] for r in conn.execute("SELECT name FROM people WHERE name IS NOT NULL")}
    projects = {p["nomi"] for p in f["loyihalar"]}
    groups = []
    for g in raw.get("groups") or []:
        names = list(dict.fromkeys(n for n in g.get("people") or [] if n in known))
        if names and (g.get("title") or "").strip():
            groups.append({"title": g["title"].strip()[:80], "people": names[:80]})
    return {"answer": (raw.get("answer") or "").strip(), "groups": groups[:3],
            "projects": [p for p in raw.get("projects") or [] if p in projects][:5]}
