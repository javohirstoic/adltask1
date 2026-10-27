"""Rahbar yordamchisi — agent: savolga javob aniq bo'lguncha qadamma-qadam ma'lumot yig'adi.

Har qadamda model bitta asbob tanlaydi (jamoa, kunlik hisobot, xodim tarixi, vazifalar, loyihalar, qidiruv ...),
natijasini o'qiydi va keyingi qadamni hal qiladi; ma'lumot yetarli bo'lgach javob yozadi. Bir martalik "savol-javob"dan
farqi: kerakli kesim (masalan, kechagi hisobot) oldindan berilmagan bo'lsa ham agent o'zi topib keladi.

Model-agnostik: maxsus function-calling emas, oddiy JSON javob — ertaga o'z serverimizdagi model ham ishlata oladi.
Yozish amallari (eslatma yuborish, vazifa o'tkazish, muddat) hech qachon o'zi bajarilmaydi: agent faqat taklif qiladi,
rahbar tugmani bosib, oldindan ko'rib tasdiqlaydi (actions.preview / execute).
"""
import inspect
import json
import logging
import re
import time
from datetime import date, timedelta

from . import ai, analytics, config, db, quality, sqlro

log = logging.getLogger("puls.agent")
MAX_STEPS = 6          # asbob chaqiruvi bosqichlari (har birida 3 tagacha); shundan keyin bor ma'lumot bilan javob
RESULT_CHARS = 22000   # bitta asbob natijasi modelga shuncha belgigacha beriladi (qolgani kesiladi, bu aytiladi)
WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"]


class ToolError(Exception):
    """Asbob ishlatilmadi (ism topilmadi, sana noto'g'ri ...): sababi modelga qaytariladi, u tuzatib qayta urinadi."""


def fold(text: str) -> str:
    return re.sub(r"[ʻ’‘`´]", "'", (text or "").lower()).strip()


class Ctx:
    """Bitta savol davomidagi holat: doira (menejer loyihalari, bo'lim), hisoblangan jamoa kesimi, takliflar."""

    def __init__(self, scope: set[int] | None, dept: str | None):
        self.scope, self.dept = scope, dept
        self.today = config.now().date()
        self.proposals: list[dict] = []
        self.sql = False
        self._data = None

    @property
    def data(self) -> dict:
        if self._data is None:
            with db.session() as conn:
                self._data = analytics.compute(conn, "week", scope=self.scope, dept=self.dept)
        return self._data

    def person(self, ism: str) -> dict:
        """To'liq ism, ism yoki familiya bo'yicha topadi. Bir nechta odam mos kelsa — qaysi biri ekanini so'raydi."""
        q = fold(ism)
        if not q:
            raise ToolError("ism berilmadi")
        ppl = self.data["people"]
        exact = [p for p in ppl if fold(p["name"]) == q]
        if exact:
            return exact[0]
        words = q.split()
        hits = [p for p in ppl if all(any(w2.startswith(w) for w2 in fold(p["name"]).split()) for w in words)]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ToolError("«%s» ismli xodim topilmadi. Bor xodimlar: %s" % (ism, ", ".join(p["name"] for p in ppl[:60])))
        raise ToolError("«%s» bir nechta xodimga mos: %s. Aniq ismni bering." % (ism, ", ".join(p["name"] for p in hits)))

    def day(self, sana: str | None) -> date:
        t = fold(sana or "")
        if not t or t == "bugun":
            return self.today
        if t == "kecha":
            return self.today - timedelta(days=1)
        if t in ("o'tgan kun", "avvalgi kun", "kechagi oldingi kun"):
            return self.today - timedelta(days=2)
        for i, w in enumerate(WEEKDAYS):
            if t.startswith(w):  # eng yaqin o'tgan shu hafta kuni (bugun ham bo'lishi mumkin)
                return self.today - timedelta(days=(self.today.weekday() - i) % 7)
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})$", t)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$", t)
        if m:
            y = int(m.group(3)) + (2000 if m.group(3) and len(m.group(3)) == 2 else 0) if m.group(3) else self.today.year
            return date(y, int(m.group(2)), int(m.group(1)))
        m = re.match(r"(\d{1,2})[\s\-]*([a-z']+)", t)
        if m:
            for k, name in enumerate(MONTHS):
                if m.group(2).startswith(name[:4]):
                    d = date(self.today.year, k + 1, int(m.group(1)))
                    return d if d <= self.today else date(self.today.year - 1, k + 1, int(m.group(1)))
        raise ToolError("sana tushunilmadi: «%s». YYYY-MM-DD ko'rinishida bering" % sana)


def _uz(d: date) -> str:
    return "%d-%s, %s" % (d.day, MONTHS[d.month - 1], WEEKDAYS[d.weekday()])


def _item(i: dict) -> str:
    s = "%s (og'irlik %s)" % (i["title"][:110], i.get("weight") or "?")
    if i.get("dup_kind") in ("takror", "nusxa"):
        when = (i.get("old_done_at") or "")[:10]
        s += " [ESKI ISH QAYTA YOZILGAN: %s%s]" % (when, ", %sning ishi" % i["old_assignee"] if i["dup_kind"] == "nusxa" and i.get("old_assignee") else "")
    if i.get("deleted_at"):
        s += " [hisobot xabari o'chirilgan]"
    return s


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, [], "", {})}


# ---------------- asboblar (faqat o'qiydi) ----------------

def t_jamoa(ctx: Ctx, sana: str | None = None, bolim: str | None = None, faqat: str | None = None) -> dict:
    day = ctx.day(sana)
    wrote: dict[str, dict] = {}
    if day != ctx.today:
        with db.session() as conn:
            wrote = {p["name"]: p for p in quality.day_report(conn, day.isoformat(), ctx.scope, ctx.dept)}
    rows = []
    for p in ctx.data["people"]:
        if bolim and fold(p["department"]) != fold(bolim):
            continue
        n = wrote[p["name"]]["count"] if day != ctx.today and p["name"] in wrote else p["today"]["items"] if day == ctx.today else 0
        reps = wrote[p["name"]]["repeats"] if p["name"] in wrote else p["today"]["repeats"] if day == ctx.today else 0
        q = p["q28"]
        row = {"ism": p["name"], "bolim": p["department"], "orin": p.get("rank"), "reyting": p["score"], "holat": p["state_label"],
               "shu_kuni_yozgan_ishlar": n, "shu_kuni_qayta_yozilgan": reps, "qayta_yozilgan_4hafta": q["repeats"],
               "mayda_ulushi_4hafta": round(100 * q["small"] / q["rated"]) if q["rated"] else None,
               "ortacha_ogirlik": q["avg_weight"], "kunlik_ish_hajmi_jamoaga_nisbatan": p.get("pace_ratio"),
               "haftada_orin_ozgarishi": p.get("move"), "yangi_xodim": p.get("new") or None,
               "hozir": p["current"]["title"] if p.get("current") else None, "jim_ish_kunlari": p.get("silent_days"),
               "osish_2hafta": "%s: %s" % (p["growth"]["label"], "; ".join(p["growth"]["why"])) if p.get("growth") else None}
        if faqat == "yozmaganlar" and (n or not day.weekday() < 5):
            continue
        if faqat == "takror" and not (q["repeats"] or reps):
            continue
        if faqat == "mayda" and not (row["mayda_ulushi_4hafta"] or 0) >= 50:
            continue
        if faqat == "yangi" and not p.get("new"):
            continue
        if faqat == "muammoli" and p["state"] not in ("overloaded", "silent", "stuck") and not q["repeats"]:
            continue
        if faqat == "osganlar" and (p.get("growth") or {}).get("verdict") not in ("ancha_osdi", "osdi"):
            continue
        if faqat == "pasayganlar" and (p.get("growth") or {}).get("verdict") != "pasaydi":
            continue
        rows.append(_compact(row))
    rows.sort(key=lambda r: (r.get("orin") or 10 ** 6, r["ism"]))
    return {"sana": _uz(day), "xodimlar_soni": len(rows), "xodimlar": rows}


def t_kun_hisoboti(ctx: Ctx, sana: str | None = None) -> dict:
    day = ctx.day(sana)
    with db.session() as conn:
        rep = quality.day_report(conn, day.isoformat(), ctx.scope, ctx.dept)
        miss = quality.missing(conn, day.isoformat(), {p["name"] for p in rep}, ctx.scope, ctx.dept)
    return {"sana": _uz(day), "ish_kuni": day.weekday() < 5,
            "hisobot_yozganlar": [{"kim": p["name"], "bolim": p["department"], "ishlar": [_item(i) for i in p["items"][:12]]}
                                  for p in rep],
            "hisobot_yozmaganlar": [m["name"] for m in miss],
            "eski_ishni_qayta_yozganlar": [{"kim": p["name"], "nechta": p["repeats"]} for p in rep if p["repeats"]],
            "izoh": "hisobot_yozmaganlar: oxirgi 14 kunda ishlagan, lekin shu kuni hech narsa yozmagan xodimlar"}


def t_xodim(ctx: Ctx, ism: str) -> dict:
    p = ctx.person(ism)
    q = p["q28"]
    ex = q.get("example")
    return _compact({
        "ism": p["name"], "bolim": p["department"], "holat": "%s: %s" % (p["state_label"], p["fact"]),
        "orin": "%s / %s" % (p["rank"], p["rank_of"]) if p.get("rank") else None, "reyting_100": p["score"],
        "bolimdagi_orin": "%s / %s" % (p["dept_rank"], p["dept_rank_of"]) if p.get("dept_rank") else None,
        "haftada_orin_ozgarishi": p.get("move"), "yangi_xodim_ish_kunlari": p["evidence"] if p.get("new") else None,
        "kunlik_ish_hajmi_jamoaga_nisbatan": p.get("pace_ratio"), "ish_hajmi_ozgarishi_foiz_oldingi_4haftaga": p.get("trend"),
        "vazifani_bajarish_foiz": p.get("completion"), "muntazam_hisobot_foiz": p.get("regular"),
        "hisobot_4hafta": {"ishlar": q["items"], "baholangan": q["rated"], "mayda": q["small"], "ortacha_ogirlik_5dan": q["avg_weight"],
                           "eski_ishni_qayta_yozgan": q["repeats"], "boshqaning_ishini_yozgan": q["copies"]},
        "oxirgi_qayta_yozilgan_misol": ("«%s» (%s), asli %s" % (ex["title"], ex["at"][:10], (ex["old_at"] or "?")[:10])) if ex else None,
        "bugun": p["today"], "hozir": p.get("current"),
        "ochiq_vazifalar": [_compact({"vazifa": t["title"], "loyiha": t["project"], "kun": t["age"], "bosqich": t.get("stage"),
                                      "muddat": t.get("due_label"), "kechikdi": t.get("due_in") is not None and t["due_in"] < 0})
                            for t in p["open_tasks"][:15]],
        "belgilar": [t["label"] for t in p.get("traits", [])],
        "osish_2hafta": p.get("growth"), "bu_hafta_ishlar": p.get("week_items"), "odatdagi_haftalik_ishlar": p.get("usual_week"),
        "oxirgi_faollik": p.get("last_activity"), "jim_ish_kunlari": p.get("silent_days"),
    })


def t_xodim_kunlari(ctx: Ctx, ism: str, kunlar: int = 14) -> dict:
    p = ctx.person(ism)
    with db.session() as conn:
        days = quality.person_days(conn, p["name"], ctx.today.isoformat(), max(1, min(int(kunlar or 14), 60)), ctx.scope)
    out = []
    for d in days:
        if not d["count"] and not d["workday"]:
            continue
        out.append(_compact({"sana": _uz(date.fromisoformat(d["day"])), "ishlar": [_item(i) for i in d["items"][:12]],
                             "hisobot_yozmagan": (not d["count"] and d["workday"]) or None}))
    return {"ism": p["name"], "kunlar": out}


def t_qayta_yozilganlar(ctx: Ctx, kunlar: int = 30, ism: str | None = None) -> dict:
    name = ctx.person(ism)["name"] if ism else None
    since = (ctx.today - timedelta(days=max(1, min(int(kunlar or 30), 365)))).strftime("%Y-%m-%d 00:00:00")
    with db.session() as conn:
        rows = quality.suspicious(conn, since, ctx.scope, ctx.dept)
    rows = [r for r in rows if not name or r["assignee"] == name]
    return {"davr_kun": kunlar, "soni": len(rows), "holatlar": [_compact({
        "kim": r["assignee"], "sana": r["done_at"][:10], "yozgan_ishi": r["title"][:120], "asl_yozuv": r["old_title"][:120],
        "asl_sana": (r["old_done_at"] or "")[:10], "asl_muallif": r["old_assignee"] if r["dup_kind"] == "nusxa" else None,
        "necha_kun_oldin": r.get("gap_days")}) for r in rows[:40]]}


def t_vazifalar(ctx: Ctx, ism: str | None = None, loyiha: str | None = None, holat: str = "ochiq", kunlar: int = 30) -> dict:
    sql = ("SELECT t.id, t.title, t.assignee, t.status, t.stage, t.deadline, t.created_at, t.done_at, p.name AS project "
           "FROM tasks t JOIN projects p ON p.id = t.project_id WHERE t.status != 'taklif'")
    args: list = []
    if ism:
        sql += " AND t.assignee = ?"; args.append(ctx.person(ism)["name"])
    if loyiha:
        sql += " AND lower(p.name) LIKE ?"; args.append("%" + fold(loyiha) + "%")
    if ctx.scope is not None:
        sql += " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in ctx.scope) or "NULL")
    today = ctx.today.isoformat()
    if holat == "bajarilgan":
        sql += " AND t.status = 'done' AND t.done_at >= ?"
        args.append((ctx.today - timedelta(days=max(1, min(int(kunlar or 30), 365)))).isoformat())
    elif holat == "muddati_otgan":
        sql += " AND t.status = 'open' AND t.deadline IS NOT NULL AND t.deadline < ?"; args.append(today)
    else:
        sql += " AND t.status = 'open'"
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY coalesce(t.done_at, t.created_at) DESC LIMIT 80", args)]
    return {"soni": len(rows), "vazifalar": [_compact({
        "id": r["id"], "vazifa": r["title"][:110], "kim": r["assignee"], "loyiha": r["project"], "bosqich": r["stage"],
        "muddat": r["deadline"], "berilgan": r["created_at"][:10], "bajarilgan": (r["done_at"] or "")[:10] or None,
        "ochiq_kun": (ctx.today - date.fromisoformat(r["created_at"][:10])).days if r["status"] == "open" else None})
        for r in rows]}


def t_loyihalar(ctx: Ctx) -> dict:
    return {"loyihalar": [_compact({
        "nomi": r["name"], "holat": r["status"], "bajarilgan_foiz": r["progress"], "ochiq": r["open_total"],
        "muddat": r.get("deadline_label"), "qolgan_kun": r.get("days_left"), "prognoz": r.get("eta_label"),
        "kechikish_kun": r.get("late_days") or None, "sabablar": [x["text"] for x in r["risks"][:3]],
        "odamlar": r["people"][:8]}) for r in ctx.data["projects"]]}


def t_loyiha(ctx: Ctx, nomi: str) -> dict:
    q = fold(nomi)
    pr = [r for r in ctx.data["projects"] if q in fold(r["name"])]
    if not pr:
        raise ToolError("«%s» loyihasi topilmadi. Bor loyihalar: %s" % (nomi, ", ".join(r["name"] for r in ctx.data["projects"])))
    r = pr[0]
    with db.session() as conn:
        d = analytics.project_detail(conn, r["id"])
    return _compact({"nomi": r["name"], "id": r["id"], "holat": r["status"], "bajarilgan_foiz": r["progress"],
                     "muddat": r.get("deadline_label"), "prognoz": r.get("eta_label"), "sabablar": [x["text"] for x in r["risks"]],
                     "muammolar": [b["text"] for b in r["blocker_list"]],
                     "jamoa": [{"kim": t["name"], "ochiq": t["open"], "bajardi": t["done"]} for t in (d or {}).get("team", [])[:15]],
                     "ochiq_vazifalar": [_compact({"id": t["id"], "vazifa": t["title"][:100], "kim": t["assignee"], "kun": t["age"],
                                                   "muddat": t.get("due_label")}) for t in (d or {}).get("open_tasks", [])[:25]]})


def t_bolimlar(ctx: Ctx) -> dict:
    return {"bolimlar": [_compact({
        "nomi": d["name"], "orin": d.get("rank"), "xodimlar": d["count"], "reyting": d["score"],
        "kunlik_ish_hajmi_1_xodimga_jamoaga_nisbatan": d.get("pace_ratio"), "ortacha_ogirlik": d.get("avg_weight"),
        "mayda_ulushi": d.get("small_share"), "qayta_yozilgan_4hafta": d.get("repeats30"), "osish_foiz": d.get("trend"),
        "eng_kuchli": d["best"]["name"] if d.get("best") else None}) for d in sorted(ctx.data["departments"], key=lambda d: d.get("rank") or 99)]}


def t_qidir(ctx: Ctx, matn: str, kunlar: int = 365) -> dict:
    ws = [w for w in re.findall(r"[^\W_]+", fold(matn)) if len(w) >= 3][:6]
    if not ws:
        raise ToolError("qidirish uchun kamida bitta 3 harfli so'z kerak")
    since = (ctx.today - timedelta(days=max(1, min(int(kunlar or 365), 730)))).isoformat()
    sc = "" if ctx.scope is None else " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in ctx.scope) or "NULL")
    hit = " + ".join("CASE WHEN lower(t.title) LIKE ? THEN 1 ELSE 0 END" for _ in ws)
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT t.title, t.assignee, t.status, t.created_at, t.done_at, t.dup_kind, p.name AS project, (%s) AS score "
            "FROM tasks t JOIN projects p ON p.id = t.project_id WHERE t.created_at >= ?%s AND (%s) > 0 "
            "ORDER BY score DESC, coalesce(t.done_at, t.created_at) DESC LIMIT 30" % (hit, sc, hit),
            ["%" + w[:6] + "%" for w in ws] + [since] + ["%" + w[:6] + "%" for w in ws])]
    return {"topildi": len(rows), "ishlar": [_compact({
        "ish": r["title"][:110], "kim": r["assignee"], "loyiha": r["project"], "holat": "bajarilgan" if r["status"] == "done" else "ochiq",
        "sana": (r["done_at"] or r["created_at"])[:10], "qayta_yozilgan": r["dup_kind"] in ("takror", "nusxa") or None}) for r in rows]}


# ---------------- taklif (yozish amali: faqat tayyorlanadi, rahbar tasdiqlaydi) ----------------

def t_taklif(ctx: Ctx, tur: str, ism: str | None = None, matn: str | None = None, kimga: str | None = None,
             vazifa_idlari: list | None = None, loyiha: str | None = None, sana: str | None = None) -> dict:
    tur = fold(tur)
    ism = ism or (kimga if tur in ("eslatma", "rahmat") else None)  # model ba'zan ismni "kimga" ga yozadi
    if tur == "eslatma":
        p = ctx.person(ism or "")
        action = {"type": "ping_person", "name": p["name"], "text": (matn or "").strip()[:600]}
        label = "%sga eslatma yuborish" % p["name"].split()[0]
    elif tur == "vazifa_otkazish":
        src, dst = ctx.person(ism or ""), ctx.person(kimga or "")
        ids = [int(i) for i in vazifa_idlari or [] if str(i).isdigit()]
        own = {t["id"] for t in src["open_tasks"]}
        ids = [i for i in ids if i in own] or [t["id"] for t in src["open_tasks"][:1]]
        if not ids:
            raise ToolError("%sda ochiq vazifa yo'q" % src["name"])
        action = {"type": "reassign", "from": src["name"], "to": dst["name"], "task_ids": ids}
        label = "%d ta vazifani %sga o'tkazish" % (len(ids), dst["name"].split()[0])
    elif tur == "rahmat":
        p = ctx.person(ism or "")
        action = {"type": "thank_person", "name": p["name"], "text": (matn or "").strip()[:600]}
        label = "%sga rahmat aytish" % p["name"].split()[0]
    elif tur == "muddat":
        pr = [r for r in ctx.data["projects"] if fold(loyiha or "") in fold(r["name"])]
        if not pr or not loyiha:
            raise ToolError("loyiha topilmadi")
        d = _future(ctx, sana or "")
        if d is None:
            raise ToolError("muddat sanasi tushunilmadi: «%s»" % sana)
        action = {"type": "deadline", "project_id": pr[0]["id"], "date": d.isoformat()}
        label = "%s muddatini %s qilish" % (pr[0]["name"], _uz(d).split(",")[0])
    elif tur == "loyihadan_holat":
        pr = [r for r in ctx.data["projects"] if fold(loyiha or "") in fold(r["name"])]
        if not pr or not loyiha:
            raise ToolError("loyiha topilmadi")
        action = {"type": "ping_project", "project_id": pr[0]["id"]}
        label = "%s jamoasidan holat so'rash" % pr[0]["name"]
    else:
        raise ToolError("tur: eslatma | rahmat | vazifa_otkazish | muddat | loyihadan_holat")
    ctx.proposals.append({"label": label, "action": action})
    return {"tayyor": label, "eslatma": "Bu amal hali bajarilmadi: rahbar javobdagi tugmani bosib tasdiqlaydi."}


def _future(ctx: Ctx, sana: str) -> date | None:
    """Muddat uchun sana: kelajakka qarab ("juma" — kelasi juma, "ertaga", "3 kun", "25-oktyabr", "25.10", ISO)."""
    from .parser import parse_date
    t = fold(sana)
    for i, w in enumerate(WEEKDAYS):
        if t.startswith(w):
            return ctx.today + timedelta(days=(i - ctx.today.weekday()) % 7 or 7)
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})$", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return parse_date(t, ctx.today)


def t_osish(ctx: Ctx, ism: str, kunlar: int = 90) -> dict:
    p = ctx.person(ism)
    with db.session() as conn:
        g = quality.person_growth(conn, p["name"], ctx.today.isoformat(), max(14, min(int(kunlar or 90), 730)), ctx.scope)
    g["hozirgi_xulosa_2hafta"] = p.get("growth")
    return g


def t_sql(ctx: Ctx, sorov: str, maqsad: str | None = None) -> dict:
    if not ctx.sql:
        raise ToolError("SQL faqat rahbar va admin uchun")
    try:
        return sqlro.query(sorov)
    except ValueError as e:
        raise ToolError(str(e))


# nomi: (funksiya, modelga tavsif, qadam yorlig'i — rahbar ko'radigan tabiiy gap)
TOOLS = {
    "jamoa": (t_jamoa, "Butun jamoa bir qarashda: har xodim o'rni, reytingi, holati, shu kuni nechta ish yozgani, 4 haftada qayta "
              "yozganlari, mayda ishlar ulushi, oxirgi 2 haftadagi o'sishi (sababi bilan), hozir nima qilyapti. args: sana "
              "(bugun|kecha|YYYY-MM-DD), bolim, faqat (yozmaganlar|takror|mayda|yangi|muammoli|osganlar|pasayganlar)",
              "Jamoani ko'zdan kechiryapman"),
    "kun_hisoboti": (t_kun_hisoboti, "Bir kunlik hisobotlar: kim nima yozdi (har ish og'irligi va takror belgisi bilan), kim "
                     "yozmadi, kim eski ishni qayta yozdi. args: sana (bugun|kecha|hafta kuni|YYYY-MM-DD)", "{sana} hisobotlarini o'qiyapman"),
    "xodim": (t_xodim, "Bitta xodim haqida hammasi: o'rni, reytingi, holati, 4 haftalik hisobot sifati, o'sishi, ochiq vazifalari, "
              "hozirgi ishi. args: ism", "{ism} haqidagi ma'lumotni ochyapman"),
    "xodim_kunlari": (t_xodim_kunlari, "Xodimning kunma-kun yozgan ishlari (yozmagan ish kunlari ham ko'rinadi). args: ism, kunlar "
                      "(standart 14, ko'pi 60)", "{ism}ning kunlik hisobotlarini o'qiyapman"),
    "osish": (t_osish, "Xodim vaqt o'tib qanday o'zgargani: davrma-davr (3 oygacha haftalik, uzoqrog'i oylik) ish hajmi, og'irlik, "
              "mayda ishlar, qayta yozilgan ishlar, muntazamlik, birinchi va ikkinchi yarim solishtirmasi. 'Oldin yolg'on yozardi, endi "
              "halol' kabi savollar uchun. args: ism, kunlar (30|60|90|180|365)", "{ism}ning o'sishini davrma-davr tahlil qilyapman"),
    "qayta_yozilganlar": (t_qayta_yozilganlar, "Eski ishni yangi deb qayta yozish (yoki boshqaning ishini yozish) holatlari, asl "
                          "yozuv sanasi bilan. args: kunlar (standart 30), ism (ixtiyoriy)", "Qayta yozilgan ishlarni tekshiryapman"),
    "vazifalar": (t_vazifalar, "Vazifalar ro'yxati (id bilan). args: ism, loyiha, holat (ochiq|muddati_otgan|bajarilgan), "
                  "kunlar (bajarilganlar uchun)", "Vazifalarni ko'ryapman"),
    "loyihalar": (t_loyihalar, "Hamma loyihalar: bajarilgan foiz, muddat, kutilgan tugash, kechikish va sabablari. args: yo'q",
                  "Loyihalarni ko'ryapman"),
    "loyiha": (t_loyiha, "Bitta loyiha batafsil: jamoasi, ochiq vazifalari, muammolari. args: nomi", "{nomi} loyihasini ochyapman"),
    "bolimlar": (t_bolimlar, "Bo'limlar reytingi va har bo'lim ko'rsatkichlari. args: yo'q", "Bo'limlarni solishtiryapman"),
    "qidir": (t_qidir, "Ish nomlari ichidan qidirish: kim qachon shunga o'xshash ish qilgan. args: matn, kunlar (standart 365)",
              "«{matn}» bo'yicha ishlarni qidiryapman"),
    "sql": (t_sql, "O'zingiz yozgan bitta faqat-o'qish SQL so'rovi: boshqa asboblar yetmasa — istalgan kesim, top-N, oyma-oy, "
            "solishtirish, xabar matnlari ichidan qidirish. args: sorov (SQL), maqsad (rahbarga ko'rinadigan qisqa o'zbekcha gap: "
            "nima hisoblayapsiz). Ko'rinishlar:\n{sql_doc}", "Bazadan kerakli ma'lumotni hisoblayapman"),
    "taklif": (t_taklif, "Amalni TAYYORLASH (bajarmaydi, rahbar tasdiqlaydi). args: tur (eslatma|vazifa_otkazish|muddat|"
               "loyihadan_holat|rahmat); eslatma: ism, matn; rahmat: ism, matn (nima uchun); vazifa_otkazish: ism (kimdan), kimga, "
               "vazifa_idlari; muddat: loyiha, sana; loyihadan_holat: loyiha", "Amalni tayyorlayapman"),
}

SYSTEM = """You are the personal assistant of the head of an IT center at the Ministry of Justice of Uzbekistan, inside his
team-monitoring panel. You work like an agent (like Claude Code): step by step you call tools to collect exactly the data the
question needs, read the results, and only when the answer is certain you write it. The boss wants to finish his work fast.

Now: {today} {time}, {weekday}, Tashkent time (UTC+5). "kecha" = {yesterday}. Reports of a day are final after 18:00.{scope}
{resolved}
Tools:
{tools}

Rules:
- Each step: type "call" with 1-3 independent calls (run together), or type "final" with the answer, or type "ask" when the
  question is ambiguous (two people match, unclear period) — then "ask" holds a short question and "options" the choices.
- Prefer the specific tools; when they cannot answer (top-N of anything, custom periods, monthly series, counts, comparisons,
  searching message texts), write SQL with tool "sql". If SQL fails, read the error and fix the query.
- Answer exactly what was asked. Never invent a name, number, date or fact: every one must come from a result below.
- Different things, never mix: "hisobot yozmagan / yozmadi" = did not report (kun_hisoboti.hisobot_yozmaganlar);
  "eski ishni qayta yozgan / takror / nusxa" = re-posted old work (qayta_yozilganlar, ESKI ISH QAYTA YOZILGAN marks,
  ishlar.takror_turi IN ('takror','nusxa')).
- Growth / improvement questions ("o'sdimi", "yaxshilandimi", "oldin yolg'on yozardi") → tool "osish" (or jamoa faqat=osganlar).
  Name what improved with the numbers (before → after). Improvement in honesty is important: say it clearly and kindly.
- Do not repeat a call with the same arguments. If the data cannot answer the question, say exactly what is missing.
- To DO something (reminder, thanks, move tasks, deadline, ask a project team) use tool "taklif"; it is not executed — say the
  button below the answer sends it after the boss confirms. After "taklif" returned "tayyor", do not call it again.
- Final answer: Uzbek Latin, plain everyday words, no English, no jargon, no markdown. At most 120 words; lead with the direct
  answer (counts, names). People lists go into "groups" (short title each); if more than 5 people, the text gives only the count.
  To show a table from a result (for example an SQL result), put its ref number into "tables" with a short title; do not retype
  the rows in the text.
- thought: one short sentence in plain Uzbek — what you will do next and why (the boss sees it). No English words
  (not "tool", "SQL", "query"): say "jamoa ro'yxatidan", "bazadan hisoblayman".
- follow_ups: 2-3 short natural next questions (Uzbek), only when useful.

Respond with JSON only."""

# Hamma asboblar uchun bitta argumentlar lug'ati (har asbob o'ziga keragini oladi): model JSON ichida JSON yozmaydi, adashmaydi
ARG_PROPS = {k: {"type": t} for k, t in (
    ("sana", "STRING"), ("ism", "STRING"), ("bolim", "STRING"), ("faqat", "STRING"), ("kunlar", "INTEGER"), ("holat", "STRING"),
    ("loyiha", "STRING"), ("nomi", "STRING"), ("matn", "STRING"), ("sorov", "STRING"), ("maqsad", "STRING"), ("tur", "STRING"),
    ("kimga", "STRING"))}
ARG_PROPS["vazifa_idlari"] = {"type": "ARRAY", "items": {"type": "INTEGER"}}

STEP_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "thought": {"type": "STRING"},
        "type": {"type": "STRING", "enum": ["call", "final", "ask"]},
        "calls": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "tool": {"type": "STRING", "enum": list(TOOLS)}, "args": {"type": "OBJECT", "properties": ARG_PROPS}},
            "required": ["tool", "args"]}},
        "answer": {"type": "STRING"},
        "groups": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "title": {"type": "STRING"}, "people": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["title", "people"]}},
        "tables": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "ref": {"type": "INTEGER"}, "title": {"type": "STRING"}}, "required": ["ref", "title"]}},
        "ask": {"type": "STRING"},
        "options": {"type": "ARRAY", "items": {"type": "STRING"}},
        "follow_ups": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["thought", "type"],
}

# Savol turi -> qaysi natija bo'lishi shart (kod tekshiradi; bo'lmasa model bir marta tuzatadi)
INTENTS = [
    (re.compile(r"yozma|yozmagan|yozmadi|hisobot berma|topshirma|hisobotsiz", re.I), {"kun_hisoboti", "jamoa", "xodim_kunlari", "sql", "osish"},
     "Savol hisobot YOZMAGANLAR haqida: kun_hisoboti (hisobot_yozmaganlar) yoki jamoa faqat=yozmaganlar natijasidan javob bering."),
    (re.compile(r"qayta yoz|takror|eski ish|nusxa|yolg'on|aldash|ko'chir", re.I),
     {"qayta_yozilganlar", "kun_hisoboti", "xodim", "xodim_kunlari", "jamoa", "sql", "osish"},
     "Savol eski ishni QAYTA YOZISH haqida: qayta_yozilganlar natijasidan javob bering."),
    (re.compile(r"o'sdi|o'sgan|o'sish|yaxshila|rivojla|ilgariga qaraganda|avvalgiga|pasay", re.I), {"osish", "jamoa", "sql", "xodim"},
     "Savol o'sish haqida: bitta xodim bo'lsa osish, hammadan qidirilsa jamoa faqat=osganlar natijasidan javob bering."),
]


def _resolve(ctx: Ctx, question: str) -> str:
    """Kod oldindan aniqlaydi: savoldagi ismlar va kunlar. Model qidirib o'tirmaydi, adashmaydi."""
    q = fold(question)
    words = set(re.findall(r"[a-z']{3,}", q))
    found = []
    for p in ctx.data["people"]:
        parts = [w for w in fold(p["name"]).split() if len(w) >= 3]
        if any(any(w.startswith(x[:max(4, len(x) - 3)]) and len(x) >= 4 for w in words) for x in parts):
            found.append(p["name"])
    lines = []
    if 0 < len(found) <= 6:
        lines.append("ANIQLANGAN XODIMLAR (savolda tilga olingan bo'lishi mumkin): " + ", ".join(found))
    days = []
    for w in ("bugun", "kecha"):
        if w in q:
            days.append("%s = %s" % (w, ctx.day(w).isoformat()))
    for wd in WEEKDAYS:
        if wd in q:
            days.append("%s = %s" % (wd, ctx.day(wd).isoformat()))
    if days:
        lines.append("ANIQLANGAN KUNLAR: " + "; ".join(days))
    return ("\n".join(lines) + "\n") if lines else ""


def _prompt(ctx: Ctx, question: str, history: list[dict], steps: list[dict], notes: list[str], force: bool) -> str:
    tools = "\n".join("- %s: %s" % (k, v[1].replace("{sql_doc}", sqlro.DOC.format(dialect=sqlro.dialect())))
                      for k, v in TOOLS.items() if k != "sql" or ctx.sql)
    scope = (" Only the department «%s» is in view." % ctx.dept) if ctx.dept else ""
    parts = [SYSTEM.format(today=ctx.today.isoformat(), time=config.now().strftime("%H:%M"), weekday=WEEKDAYS[ctx.today.weekday()],
                           yesterday=(ctx.today - timedelta(days=1)).isoformat(), tools=tools, scope=scope,
                           resolved=_resolve(ctx, question))]
    if history:
        parts.append("Earlier in this conversation:\n" + "\n".join(
            "Boss: %s\nYou: %s" % (h.get("q", "")[:300], h.get("a", "")[:600]) for h in history[-4:]))
    parts.append("Boss's question: " + question)
    for s in steps:
        parts.append("r%d = %s %s\n%s" % (s["ref"], s["tool"], json.dumps(s["args"], ensure_ascii=False), s["result"]))
    for n in notes:
        parts.append("TEKSHIRUV: " + n)
    if force:
        parts.append("No more tool calls are allowed. Give type \"final\" now from the results above; if something is still "
                     "unknown, say so.")
    return "\n\n".join(parts)


def _label(tool: str, args: dict) -> str:
    if tool == "sql" and (args.get("maqsad") or "").strip():
        return args["maqsad"].strip()[:90]
    tpl = TOOLS[tool][2]
    if any(k != "sana" and not str(args.get(k) or "").strip() for k in re.findall(r"{(\w+)}", tpl)):
        return "Ma'lumot yig'yapman"  # shablonga kerakli nom berilmagan: yarim gap chiqmasin
    vals = {"sana": "Bugungi", "ism": "", "nomi": "", "matn": ""}
    vals.update({k: v for k, v in args.items() if isinstance(v, str)})
    if "sana" in args:
        s = fold(args.get("sana") or "")
        vals["sana"] = "Bugungi" if s in ("", "bugun") else "Kechagi" if s == "kecha" else args["sana"]
    try:
        return tpl.format(**vals)
    except (KeyError, IndexError, ValueError):
        return tpl.split("{")[0].strip() or "Ma'lumot yig'yapman"


def _known_people() -> set[str]:
    with db.session() as conn:
        return {r["name"] for r in conn.execute("SELECT name FROM people WHERE name IS NOT NULL")}


def _call(ctx: Ctx, tool: str, args: dict) -> tuple[str, str, dict | None]:
    fn = TOOLS[tool][0]
    try:
        params = set(inspect.signature(fn).parameters) - {"ctx"}
        data = fn(ctx, **{k: v for k, v in args.items() if k in params})
        result = json.dumps(data, ensure_ascii=False, default=str)
        if len(result) > RESULT_CHARS:
            result = result[:RESULT_CHARS] + " ... [natija kesildi: torroq so'rang]"
        return result, _summary(tool, data), data
    except ToolError as e:
        return json.dumps({"xato": str(e)}, ensure_ascii=False), str(e)[:140], None
    except Exception as e:  # noqa: BLE001 — asbob xatosi butun javobni yiqitmasin
        log.exception("agent asbobi: %s", tool)
        return json.dumps({"xato": "ichki xato: %s" % e}, ensure_ascii=False), "Ma'lumotni olib bo'lmadi", None


def _check(question: str, raw: dict, steps: list[dict]) -> list[str]:
    """Javobni kod bilan tekshirish (ikkinchi model so'rovisiz): savol turiga mos natija bormi, ro'yxatdagi ismlar
    natijalarda bormi. Muammo bo'lsa izoh qaytadi va model bir marta tuzatadi."""
    used = {s["tool"] for s in steps if not s["result"].startswith('{"xato"')}
    notes = []
    for rx, tools, note in INTENTS:
        if rx.search(question) and not used & tools:
            notes.append(note)
            break
    blob = "\n".join(s["result"] for s in steps)
    missing = [n for g in raw.get("groups") or [] for n in g.get("people") or [] if n not in blob]
    if missing:
        notes.append("Bu ismlar natijalarda yo'q, ularni olib tashlang yoki tekshiring: %s" % ", ".join(missing[:8]))
    answer = (raw.get("answer") or "").strip()
    if not answer:
        notes.append("Javob matni bo'sh.")
    # ma'lumot olinmagan bo'lsa javobda raqam, ro'yxat yoki jadval bo'lishi mumkin emas: bu to'qilgan bo'ladi
    if not used and (re.search(r"\d", answer) or re.search(r"jadval|ro'yxat|quyidagi", answer, re.I) or raw.get("groups")):
        notes.append("Siz hali birorta asbob chaqirmadingiz. Avval kerakli ma'lumotni oling (masalan sql), keyin faqat natijadan yozing.")
    tabular = {s["ref"] for s in steps if '"ustunlar"' in s["result"][:40]}
    if re.search(r"jadval", answer, re.I) and not any(t.get("ref") in tabular for t in raw.get("tables") or []):
        notes.append("Javobda jadval deyilgan, lekin tables bo'sh: natija ref raqamini tables ga qo'ying.")
    return notes


def run(question: str, history: list[dict] | None = None, scope: set[int] | None = None, dept: str | None = None,
        allow_sql: bool = False):
    """Generator: Claude Code kabi ko'rinadigan jarayon — "think" (agent fikri), "step" (qaysi asbob, nima bilan),
    "done" (natija qisqasi va ko'rinishi), "check" (javob tekshiruvi), oxirida "answer" yoki "ask" / "error"."""
    question = " ".join((question or "").split())[:600]
    if len(question) < 2:
        yield {"type": "error", "text": "Savolni yozing"}
        return
    if not config.ai_enabled():
        yield {"type": "error", "text": "Yordamchi hozir o'chiq"}
        return
    ctx = Ctx(scope, dept)
    ctx.sql = allow_sql and scope is None
    steps: list[dict] = []
    datas: dict[int, dict] = {}
    seen: set[str] = set()
    notes: list[str] = []
    repaired = False
    raw = None
    rounds = 0
    t0 = time.monotonic()
    while True:
        force = rounds >= MAX_STEPS
        raw = ai._ask(_prompt(ctx, question, history or [], steps, notes, force), 3, STEP_SCHEMA, first_timeout=12)
        if not raw:
            yield {"type": "error", "text": "Yordamchi hozir javob bermadi, birozdan keyin qayta urinib ko'ring"}
            return
        kind = raw.get("type")
        if (raw.get("thought") or "").strip():
            yield {"type": "think", "text": raw["thought"].strip()[:240]}
        if kind == "ask" and (raw.get("ask") or "").strip() and not force:
            yield {"type": "ask", "text": raw["ask"].strip()[:200], "options": [o.strip()[:80] for o in raw.get("options") or [] if o.strip()][:6]}
            return
        calls = [c for c in raw.get("calls") or [] if c.get("tool") in TOOLS][:3]
        if kind == "final" or not calls or force:
            if repaired or force:
                break
            yield {"type": "check", "text": "Javobni natijalar bilan solishtiryapman"}
            problems = _check(question, raw, steps)
            if problems:
                yield {"type": "check", "text": "Kamchilik topildi, tuzatyapman", "bad": True}
                repaired, notes = True, problems
                rounds += 1
                continue
            break
        rounds += 1
        for c in calls:
            args = c.get("args") if isinstance(c.get("args"), dict) else {}
            params = set(inspect.signature(TOOLS[c["tool"]][0]).parameters) - {"ctx"}  # boshqa asbobning bo'sh maydonlari tushib qoladi
            args = {k: v for k, v in args.items() if k in params and v not in (None, "", [])}
            ref = len(steps) + 1
            key = c["tool"] + json.dumps(args, sort_keys=True, ensure_ascii=False)
            if key in seen:  # takroriy chaqiruv rahbarga ko'rsatilmaydi, model esa natija yuqorida ekanini biladi
                steps.append({"ref": ref, "tool": c["tool"], "args": args,
                              "result": '{"xato": "bu chaqiruv allaqachon bajarilgan, natijasi yuqorida: javob yozing"}'})
                continue
            seen.add(key)
            yield {"type": "step", "n": ref, "label": _label(c["tool"], args), "tool": c["tool"], "detail": _detail(c["tool"], args)}
            result, short, data = _call(ctx, c["tool"], args)
            if data is not None:
                datas[ref] = data
            steps.append({"ref": ref, "tool": c["tool"], "args": args, "result": result})
            yield {"type": "done", "n": ref, "summary": short, "ok": data is not None, "preview": _preview(data)}
    if not steps and any("asbob chaqirmadingiz" in n for n in _check(question, raw or {}, steps)):
        # tuzatishdan keyin ham ma'lumotsiz raqam yoki ro'yxat: to'qilgan gap rahbarga chiqmaydi
        raw = {"answer": "Bu savolga aniq javob uchun ma'lumot yig'a olmadim. Savolni boshqacha yoki aniqroq bering.",
               "follow_ups": (raw or {}).get("follow_ups") or []}
    blob = "\n".join(s["result"] for s in steps)
    known = _known_people()
    groups = []
    for g in (raw or {}).get("groups") or []:
        names = list(dict.fromkeys(x for x in g.get("people") or [] if x in known and x in blob))
        if names and (g.get("title") or "").strip():
            groups.append({"title": g["title"].strip()[:80], "people": names[:80]})
    tables = []
    for t in (raw or {}).get("tables") or []:
        d = datas.get(t.get("ref"))
        if d and d.get("ustunlar") and d.get("qatorlar"):
            tables.append({"title": (t.get("title") or "").strip()[:80], "columns": d["ustunlar"], "rows": d["qatorlar"][:200],
                           "more": d.get("kesildi", False)})
    if not tables and re.search(r"jadval", (raw or {}).get("answer") or "", re.I):
        # javob jadvalni aytgan-u, raqamini bermagan: oxirgi jadvalli natija ko'rsatiladi
        last = next((datas[r] for r in sorted(datas, reverse=True) if datas[r].get("ustunlar") and datas[r].get("qatorlar")), None)
        if last:
            tables.append({"title": "", "columns": last["ustunlar"], "rows": last["qatorlar"][:200], "more": last.get("kesildi", False)})
    yield {"type": "answer", "text": ((raw or {}).get("answer") or "").strip() or "Javobni tuzib bo'lmadi, savolni boshqacha bering.",
           "groups": groups[:4], "tables": tables[:2], "actions": ctx.proposals[:4],
           "follow_ups": [f.strip()[:90] for f in (raw or {}).get("follow_ups") or [] if f.strip()][:3],
           "steps": len(steps), "seconds": round(time.monotonic() - t0, 1)}


def _detail(tool: str, args: dict) -> str:
    """Qadam yonida ko'rinadigan argumentlar (Claude Code'dagi kabi): SQL to'liq, qolganlari qisqa."""
    if tool == "sql":
        return (args.get("sorov") or "").strip()[:1200]
    return ", ".join("%s: %s" % (k, v) for k, v in args.items() if k != "maqsad")[:200]


def _preview(data: dict | None) -> dict | None:
    """Ochib ko'riladigan natija: jadval bo'lsa birinchi qatorlari, bo'lmasa qisqa matn."""
    if not data:
        return None
    if data.get("ustunlar"):
        return {"columns": data["ustunlar"], "rows": data["qatorlar"][:12], "total": data.get("soni")}
    for k in ("xodimlar", "hisobot_yozganlar", "holatlar", "vazifalar", "loyihalar", "bolimlar", "ishlar", "kunlar", "davrlar"):
        rows = data.get(k)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            cols = list(dict.fromkeys(c for r in rows[:12] for c in r))[:6]
            return {"columns": cols, "rows": [[r.get(c) if not isinstance(r.get(c), (list, dict)) else
                                               json.dumps(r.get(c), ensure_ascii=False)[:80] for c in cols] for r in rows[:12]],
                    "total": len(rows)}
    return {"text": json.dumps(data, ensure_ascii=False, default=str)[:600]}


def _summary(tool: str, data: dict) -> str:
    """Qadam tugaganda rahbarga ko'rinadigan qisqa natija."""
    if tool == "jamoa":
        return "%d xodim" % data["xodimlar_soni"]
    if tool == "kun_hisoboti":
        return "%d kishi yozgan, %d kishi yozmagan" % (len(data["hisobot_yozganlar"]), len(data["hisobot_yozmaganlar"]))
    if tool == "xodim":
        return data.get("ism", "")
    if tool == "xodim_kunlari":
        return "%d kun" % len(data["kunlar"])
    if tool == "qayta_yozilganlar":
        return "%d ta holat" % data["soni"]
    if tool == "vazifalar":
        return "%d ta vazifa" % data["soni"]
    if tool == "loyihalar":
        return "%d ta loyiha" % len(data["loyihalar"])
    if tool == "bolimlar":
        return "%d ta bo'lim" % len(data["bolimlar"])
    if tool == "qidir":
        return "%d ta ish topildi" % data["topildi"]
    if tool == "taklif":
        return data["tayyor"]
    if tool == "sql":
        return "%d qator%s (%d ms)" % (data["soni"], ", kesildi" if data.get("kesildi") else "", data.get("vaqt_ms", 0))
    if tool == "osish":
        return "%d ta %s" % (len(data["davrlar"]), "hafta" if data["davr_turi"] == "hafta" else "oy")
    return data.get("nomi", "") if isinstance(data, dict) else ""
