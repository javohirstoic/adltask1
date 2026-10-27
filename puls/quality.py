"""Hisobot sifati: xodim yozgan har ish qanchalik og'ir va u haqiqatan yangi ishmi.

1. Baho. Har vazifa nomini til modeli o'qib 1-5 darajali og'irlik, taxminiy mehnat soati, turi va bir qatorli izoh
   beradi. Bir xil nom (bo'lim bilan) bir marta baholanib keshlanadi. Analitika vazifalar soniga emas, og'irligiga
   qaraydi: ikki katta ish yettita mayda ishdan ustun.
2. Takror. Xodim yozgan bajarilgan ish uning oldingi kunlardagi ishiga yoki shu loyihadagi hamkasbining ishiga ma'no
   bo'yicha juda yaqin bo'lsa (embedding), model ikkalasini sanasi bilan solishtiradi: aynan o'sha ish qayta
   yozilganmi (takror), davomimi, har kungi muntazam ishmi yoki boshqa ish. Faqat "takror" shubhali hisoblanadi;
   rahbar asl yozuvni sanasi bilan ko'radi va o'zi xulosa qiladi.
Model ishlamasa (internet, kvota) vazifa keyingi safar qayta uriniladi: noto'g'ri baho bilan qolib ketmaydi.
"""
import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timedelta

from . import ai, analytics, config, db, memory

log = logging.getLogger("puls.quality")
FMT = "%Y-%m-%d %H:%M:%S"
WEIGHTS = {1: "Mayda", 2: "Kichik", 3: "O'rta", 4: "Katta", 5: "Juda katta"}
CATS = {"yangi": "Yangi imkoniyat", "tuzatish": "Xato tuzatish", "kichik": "Kichik o'zgarish", "dizayn": "Dizayn",
        "test": "Test", "hujjat": "Hujjat", "tadqiqot": "Tahlil va tadqiqot", "infra": "Server va infratuzilma",
        "uchrashuv": "Uchrashuv", "muntazam": "Muntazam ish", "boshqa": "Boshqa"}
VERDICTS = ("takror", "davomi", "muntazam", "boshqa")
SIM = 0.86          # embedding o'xshashligi shundan yuqori bo'lsa model hakamlik qiladi
EVAL_BATCH = 30
JUDGE_BATCH = 20
MODEL_TAG = "v1"     # baho mezoni o'zgarsa oshiriladi: eski keshlar qayta baholanadi

EVAL_PROMPT = """You assess work items that employees of an Uzbek government IT center (Ministry of Justice) report in their
daily work chats. For each item estimate how much real work it represents, so the head can compare people fairly:
two big pieces of work must count more than seven trivial ones. Do not inflate; judge only by what is written.

weight:
1 trivial: changing a color, a text or a font, moving or resizing an element, renaming, a one-line setting; minutes of work.
2 small: a small fix or tweak inside one screen or function, a short check, a routine call; under about two hours.
3 medium: a new component, endpoint, report or form, a real bug fix that needed investigation; half a day to a day.
4 large: a module, an integration with another system, a complex feature, a data migration script; several days.
5 very large: architecture, a whole subsystem, a release of a product, a large migration; a week or more.
Vague items without an object ("ishladim", "davom ettirdim", "tahlil qildim") get weight 1 or 2 and the reason says so.
Meetings and routine checks get 1 or 2 unless the text shows substantial work.
hours: realistic effort for a competent specialist, one number from 0.25 to 80.
category: one of {cats}.
reason: why, in Uzbek (Latin script), at most 90 characters, words a manager understands, no jargon.

Items (number | employee's department | project | title):
{items}

Return {{"results": [...]}} with one object per item, same order, "i" = item number."""

EVAL_SCHEMA = {
    "type": "OBJECT",
    "properties": {"results": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "i": {"type": "INTEGER"}, "weight": {"type": "INTEGER"}, "hours": {"type": "NUMBER"},
        "category": {"type": "STRING", "enum": list(CATS)}, "reason": {"type": "STRING"}},
        "required": ["i", "weight", "hours", "category", "reason"]}}},
    "required": ["results"],
}

JUDGE_PROMPT = """The head of an Uzbek government IT center checks whether employees report old work again as if it were new
(to look busier). For each pair decide what the NEW report is relative to the EARLIER one:
- "takror": the same piece of work reported again, copied or reworded, with no sign of new progress or a new stage.
- "davomi": a next stage or continuation of the same work (part 2, more endpoints, further fixes): real new work.
- "muntazam": work that is naturally repeated (daily backup check, code review, a weekly meeting, monitoring).
- "boshqa": actually different work that only sounds similar.
Be fair: say "takror" only when the new text gives no hint of new work. reason: Uzbek (Latin), at most 100 characters.
When EARLIER is by another person on the same day, "takror" means the new person presents the colleague's result as
their own; reviewing, testing or helping with it is their own part: "boshqa". When the original chat messages are given,
judge by them, not by the titles: the messages show who reported the problem, who fixed it and who only looked at it.

Pairs (number | NEW: who, date, title | EARLIER: who, date, title):
{pairs}

Return {{"results": [...]}}, one object per pair, "i" = pair number."""

JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"results": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "i": {"type": "INTEGER"}, "verdict": {"type": "STRING", "enum": list(VERDICTS)}, "reason": {"type": "STRING"}},
        "required": ["i", "verdict", "reason"]}}},
    "required": ["results"],
}

# Model ishlamaydigan joy (AI o'chiq) uchun: aniq mayda ishlar
TRIVIAL_RE = re.compile(r"\b(rang|rangi|rangini|shrift|matnini|matnni|joyini|o'lchami|kattalashtir|kichraytir|ikonka|"
                        r"padding|margin|nomini o'zgartir|цвет|шрифт|текст)\w*", re.I)


def norm(title: str) -> str:
    return " ".join(re.findall(r"[\w']+", (title or "").lower()))


def key(dept: str | None, title: str) -> str:
    return "%s|%s|%s" % (MODEL_TAG, (dept or "").lower(), norm(title))


def _model() -> str:
    return config.GEMINI_EVAL_MODEL or config.GEMINI_MODEL


def _ask(prompt: str, schema: dict) -> dict | None:
    """Baholash fonda ishlaydi, shuning uchun kuchliroq model; band bo'lsa umumiy yo'l (asosiy va zaxira model)."""
    if _model() != config.GEMINI_MODEL:
        try:
            return ai._call_model(_model(), prompt, schema, 0, 120)
        except Exception as e:  # noqa: BLE001 — zaxira yo'lga o'tamiz
            log.info("%s ishlamadi (%s), asosiy modelga o'tiladi", _model(), e)
    return ai._ask(prompt, 3, schema)


# ---------- 1. og'irlik bahosi ----------

def evaluate(conn: sqlite3.Connection, limit: int = 90) -> int:
    """Bahosi yo'q vazifalarni baholaydi. Qaytaradi: nechta vazifaga baho yozildi."""
    rows = conn.execute(
        "SELECT t.id, t.title, t.note, p.name AS project, pe.department FROM tasks t JOIN projects p ON p.id = t.project_id "
        "LEFT JOIN people pe ON pe.name = t.assignee WHERE t.weight IS NULL AND t.status != 'taklif' "
        "ORDER BY t.id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        return 0
    keys = {r["id"]: key(r["department"], r["title"]) for r in rows}
    cached = {}
    uniq = sorted(set(keys.values()))
    for i in range(0, len(uniq), 500):
        part = uniq[i:i + 500]
        for c in conn.execute("SELECT * FROM work_eval WHERE key IN (%s)" % ",".join("?" * len(part)), part):
            cached[c["key"]] = dict(c)
    todo = []
    seen = set()
    for r in rows:
        k = keys[r["id"]]
        if k not in cached and k not in seen:
            seen.add(k)
            todo.append(r)
    if todo and config.ai_enabled():
        for i in range(0, len(todo), EVAL_BATCH):
            part = todo[i:i + EVAL_BATCH]
            text = "\n".join("%d | %s | %s | %s%s" % (n + 1, r["department"] or "-", r["project"] or "-", r["title"][:200],
                                                       " (%s)" % r["note"][:240] if r["note"] else "")
                             for n, r in enumerate(part))
            raw = _ask(EVAL_PROMPT.format(cats=", ".join(CATS), items=text), EVAL_SCHEMA)
            for res in (raw or {}).get("results") or []:
                n = res.get("i")
                if not isinstance(n, int) or not 1 <= n <= len(part):
                    continue
                r = part[n - 1]
                ev = {"key": keys[r["id"]], "weight": max(1, min(5, int(res.get("weight") or 2))),
                      "hours": round(max(0.25, min(80.0, float(res.get("hours") or 1))), 2),
                      "category": res.get("category") if res.get("category") in CATS else "boshqa",
                      "reason": (res.get("reason") or "").strip()[:140], "model": _model()}
                conn.execute("INSERT INTO work_eval(key, weight, hours, category, reason, model, at) VALUES(?, ?, ?, ?, ?, ?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET weight = excluded.weight, hours = excluded.hours, category = excluded.category, "
                             "reason = excluded.reason, model = excluded.model, at = excluded.at",
                             (ev["key"], ev["weight"], ev["hours"], ev["category"], ev["reason"], ev["model"], _now()))
                cached[ev["key"]] = ev
            conn.commit()  # keyingi so'rov paytida bazani band qilib turmaymiz
    elif todo:  # AI o'chiq: kalit so'z bo'yicha oddiy taxmin (keshga yozilmaydi)
        for r in todo:
            trivial = bool(TRIVIAL_RE.search(r["title"]))
            cached[keys[r["id"]]] = {"weight": 1 if trivial else 2, "hours": 0.5 if trivial else 2, "category": "kichik" if trivial else "boshqa",
                                     "reason": "Kalit so'z bo'yicha taxmin (AI o'chiq)"}
    n = 0
    for r in rows:
        ev = cached.get(keys[r["id"]])
        if ev:
            conn.execute("UPDATE tasks SET weight = ?, hours = ?, wcat = ?, wnote = ? WHERE id = ?",
                         (ev["weight"], ev["hours"], ev["category"], ev["reason"], r["id"]))
            n += 1
    if n:
        db.bump_version(conn)
    return n


# ---------- 2. takror tekshiruvi ----------

def _now() -> str:
    return config.now().strftime(FMT)


def _days_before(day: str, n: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=n)).strftime(FMT)


def check_repeats(conn: sqlite3.Connection, limit: int = 60) -> int:
    """Hali tekshirilmagan bajarilgan ishlarni oldingi kunlardagi ishlar bilan solishtiradi."""
    new = conn.execute(
        "SELECT t.id, t.title, t.assignee, t.project_id, t.done_at, t.dup_of FROM tasks t WHERE t.status = 'done' AND t.done_at IS NOT NULL "
        "AND t.dup_at IS NULL AND t.assignee IS NOT NULL ORDER BY t.done_at LIMIT ?", (limit,)).fetchall()
    if not new:
        return 0
    pairs = []          # (yangi, eski, o'xshashlik)
    done_ids = []
    for t in new:
        day = t["done_at"][:10]
        if t["dup_of"]:
            # Xabarni o'qigan AI ishora qoldirgan: hamkasb bugun yozgan ishni o'ziniki qilib yozgan bo'lishi mumkin — hakam hal qiladi
            old = conn.execute("SELECT id, title, assignee, done_at FROM tasks WHERE id = ?", (t["dup_of"],)).fetchone()
            if old is not None and old["assignee"] != t["assignee"]:
                # Hakam faqat nomni emas, ikkala asl xabarni ham ko'radi: kim nima qilganini o'z so'zi bilan aytgan
                pairs.append((dict(t, said=_said(conn, t["id"])), dict(old, said=_said(conn, old["id"])), 0.9))
                continue
        # Faqat oldingi kunlar: bitta kunda bir ishni ikki marta yozish (xabarni qayta yuborish) takror emas.
        # Nomzodlar: xodimning o'z ishlari (butun tarix) va shu loyihadagi hamkasblarining yarim yillik ishlari
        cands = [dict(r) for r in conn.execute(
            "SELECT id, title, assignee, done_at FROM tasks WHERE status = 'done' AND done_at < ? AND id != ? AND assignee = ? "
            "ORDER BY done_at DESC LIMIT 2000", (day + " 00:00:00", t["id"], t["assignee"]))]
        cands += [dict(r) for r in conn.execute(
            "SELECT id, title, assignee, done_at FROM tasks WHERE status = 'done' AND done_at < ? AND done_at >= ? "
            "AND project_id = ? AND assignee != ? ORDER BY done_at DESC LIMIT 1500",
            (day + " 00:00:00", _days_before(day, 183), t["project_id"], t["assignee"]))]
        if not cands:
            done_ids.append(t["id"])
            continue
        n = norm(t["title"])
        exact = next((c for c in cands if norm(c["title"]) == n and c["assignee"] == t["assignee"]), None) \
            or next((c for c in cands if norm(c["title"]) == n), None)
        if exact:
            pairs.append((dict(t), exact, 1.0))
            continue
        if not config.ai_enabled():
            done_ids.append(t["id"])
            continue
        vecs = memory.vectors(conn, [t["title"]] + [c["title"] for c in cands], patient=True)
        conn.commit()  # yangi vektorlar saqlansin; uzoq yozish qulfi botni kuttirmasin
        q = vecs.get(t["title"])
        if q is None:
            break  # embedding ishlamadi: shu joydan keyingi safar davom etiladi
        best, score = None, 0.0
        have = [c for c in cands if c["title"] in vecs]
        if have and db.PG:
            # pgvector: o'xshashlik baza ichida (<=> kosinus masofa, HNSW indeks), Python'ga faqat eng yaqin 5 tasi keladi
            for r in conn.execute(
                    "SELECT t.id, t.title, t.assignee, t.done_at, 1 - (v.vec <=> ?) AS sim FROM tasks t JOIN vec_cache v ON v.text = t.title "
                    "WHERE t.status = 'done' AND t.done_at < ? AND t.id != ? AND (t.assignee = ? OR (t.project_id = ? AND t.assignee != ? "
                    "AND t.done_at >= ?)) ORDER BY v.vec <=> ? LIMIT 5",
                    (q, day + " 00:00:00", t["id"], t["assignee"], t["project_id"], t["assignee"], _days_before(day, 183), q)):
                s = float(r["sim"]) + (0.02 if r["assignee"] == t["assignee"] else 0)
                if s > score:
                    best, score = {k: r[k] for k in ("id", "title", "assignee", "done_at")}, s
        elif have:
            sims = memory.matrix([vecs[c["title"]] for c in have]) @ memory.np.frombuffer(q, dtype=memory.np.float32)
            sims = sims + memory.np.array([0.02 if c["assignee"] == t["assignee"] else 0.0 for c in have], dtype=memory.np.float32)
            i = int(sims.argmax())
            best, score = have[i], float(sims[i])
        if best is not None and score >= SIM:
            pairs.append((dict(t), best, min(1.0, score)))
        else:
            done_ids.append(t["id"])
    verdicts = _judge(conn, pairs) if pairs else {}
    marked = 0
    for i, (t, old, score) in enumerate(pairs):
        v = verdicts.get(i)
        if v is None:
            if score >= 0.999:  # aynan bir xil matn: model javob bermasa ham takror deb belgilanadi
                v = ("takror", "Aynan shu matn %s da ham yozilgan" % old["done_at"][:10])
            else:
                continue  # model javob bermadi: keyinroq qayta tekshiriladi
        verdict, reason = v
        kind = verdict
        if verdict == "takror" and old["assignee"] != t["assignee"]:
            kind = "nusxa"  # boshqa xodimning ishi o'ziniki qilib yozilgan
        conn.execute("UPDATE tasks SET dup_of = ?, dup_score = ?, dup_kind = ?, dup_note = ?, dup_at = ? WHERE id = ?",
                     (old["id"], round(score, 3), kind, reason[:160], _now(), t["id"]))
        marked += 1
    for tid in done_ids:
        conn.execute("UPDATE tasks SET dup_at = ? WHERE id = ?", (_now(), tid))
    if marked:
        db.bump_version(conn)
    conn.commit()
    return marked + len(done_ids)


def _said(conn: sqlite3.Connection, task_id: int) -> str:
    """Ish yozilgan asl xabar (javob bo'lsa, nimaga javobligi bilan)."""
    r = conn.execute("SELECT m.text, p.text AS parent FROM tasks t JOIN messages m ON m.id = t.done_msg "
                     "LEFT JOIN messages p ON p.chat_id = m.chat_id AND p.msg_id = m.reply_to WHERE t.id = ?", (task_id,)).fetchone()
    if r is None or not r["text"]:
        return ""
    return " ".join(r["text"].split())[:300] + (' (reply to: "%s")' % " ".join(r["parent"].split())[:160] if r["parent"] else "")


def _jkey(t: dict, o: dict) -> str:
    said = t.get("said") or o.get("said")
    return "%s|%s|%s|%d%s%s" % (MODEL_TAG, norm(t["title"]), norm(o["title"]), t["assignee"] == o["assignee"],
                                "|kun" if t["done_at"][:10] == o["done_at"][:10] else "",
                                "|" + hashlib.sha1(((t.get("said") or "") + "|" + (o.get("said") or "")).encode()).hexdigest()[:12] if said else "")


def _judge(conn: sqlite3.Connection, pairs: list[tuple[dict, dict, float]]) -> dict[int, tuple[str, str]]:
    """Model hakamligi; bir juftlik (matn bo'yicha) bir marta baholanadi va keshlanadi."""
    out: dict[int, tuple[str, str]] = {}
    ask = []
    for i, (t, o, _) in enumerate(pairs):
        c = conn.execute("SELECT verdict, reason FROM judge_cache WHERE key = ?", (_jkey(t, o),)).fetchone()
        if c:
            out[i] = (c["verdict"], c["reason"])
        else:
            ask.append(i)
    if not ask or not config.ai_enabled():
        return out
    for start in range(0, len(ask), JUDGE_BATCH):
        idx = ask[start:start + JUDGE_BATCH]
        part = [pairs[i] for i in idx]
        text = "\n".join("%d | NEW: %s, %s, %s | EARLIER: %s, %s, %s%s" % (
            n + 1, t["assignee"], t["done_at"][:10], t["title"][:160], o["assignee"], o["done_at"][:10], o["title"][:160],
            ' | NEW message: "%s" | EARLIER message: "%s"' % (t["said"], o["said"]) if t.get("said") or o.get("said") else "")
            for n, (t, o, _) in enumerate(part))
        raw = _ask(JUDGE_PROMPT.format(pairs=text), JUDGE_SCHEMA)
        for res in (raw or {}).get("results") or []:
            n = res.get("i")
            if isinstance(n, int) and 1 <= n <= len(part) and res.get("verdict") in VERDICTS:
                t, o, _ = part[n - 1]
                out[idx[n - 1]] = (res["verdict"], (res.get("reason") or "").strip()[:160])
                conn.execute("INSERT INTO judge_cache(key, verdict, reason, at) VALUES(?, ?, ?, ?) ON CONFLICT(key) DO UPDATE "
                             "SET verdict = excluded.verdict, reason = excluded.reason, at = excluded.at",
                             (_jkey(t, o), res["verdict"], out[idx[n - 1]][1], _now()))
        conn.commit()
    return out


def run(conn: sqlite3.Connection) -> tuple[int, int]:
    return evaluate(conn), check_repeats(conn)


def tick() -> tuple[int, int]:
    """Fon ishchisi uchun: o'z ulanishi bilan bitta qadam."""
    with db.session() as conn:
        return run(conn)


# ---------- rahbar uchun ko'rinish ----------

def _no_outsiders(alias: str = "t") -> str:
    """Rahbar "begona" degan odamning ishlari hisobotlarda ko'rinmaydi."""
    return " AND NOT EXISTS (SELECT 1 FROM people bg WHERE bg.name = %s.assignee AND bg.status = 'begona')" % alias


def _dept_sql(dept: str | None, alias: str = "t") -> str:
    return (" AND coalesce((SELECT department FROM people WHERE name = %s.assignee LIMIT 1), 'Belgilanmagan') = ?" % alias) if dept else ""


# Dalil: takror yonida ikkala xabarga (oldingi va hozirgi) Telegram havolasi — bosilsa guruhdagi aynan o'sha xabar ochiladi
LINK_COLS = ("m.chat_id AS msg_chat, m.msg_id AS msg_tg, mc.demo AS msg_demo, om.chat_id AS old_chat, om.msg_id AS old_tg, "
             "oc.demo AS old_demo ")
LINK_JOIN = ("LEFT JOIN chats mc ON mc.id = m.chat_id LEFT JOIN messages om ON om.id = o.done_msg "
             "LEFT JOIN chats oc ON oc.id = om.chat_id ")


def tg_link(chat_id, msg_id, demo=0) -> str | None:
    """Telegram xabariga havola. Superguruhda (id -100... bilan) t.me/c/<guruh>/<xabar>: guruh a'zosiga Telegram'da
    aynan o'sha xabar ochiladi. Oddiy guruh va namuna guruhlarda havola bo'lmaydi."""
    if not chat_id or not msg_id or demo or not str(chat_id).startswith("-100"):
        return None
    return "https://t.me/c/%s/%d" % (str(chat_id)[4:], int(msg_id))


def links(d: dict) -> dict:
    d["link"] = tg_link(d.pop("msg_chat", None), d.pop("msg_tg", None), d.pop("msg_demo", 0))
    d["old_link"] = tg_link(d.pop("old_chat", None), d.pop("old_tg", None), d.pop("old_demo", 0))
    return d


def repeat_proof(conn: sqlite3.Connection, task_id: int, scope: set[int] | None = None) -> dict | None:
    """Qayta yozilgan ishning dalili: hozirgi va oldingi ish yonma-yon — har biri qaysi kuni, kim, qaysi guruhda va qaysi
    xabarda yozilgani (xabarning to'liq matni va Telegram havolasi). Rahbar AI belgisiga emas, xabarlarning o'ziga qaraydi."""
    def one(tid):
        r = conn.execute(
            "SELECT t.id, t.title, t.assignee, t.done_at, t.created_at, t.project_id, p.name AS project, "
            "coalesce(dm.text, cm.text) AS text, coalesce(dm.date, cm.date) AS msg_date, coalesce(dm.chat_id, cm.chat_id) AS chat, "
            "coalesce(dm.msg_id, cm.msg_id) AS tg, coalesce(dm.deleted_at, cm.deleted_at) AS deleted_at, c.title AS chat_title, c.demo "
            "FROM tasks t JOIN projects p ON p.id = t.project_id LEFT JOIN messages dm ON dm.id = t.done_msg "
            "LEFT JOIN messages cm ON cm.id = t.created_msg LEFT JOIN chats c ON c.id = coalesce(dm.chat_id, cm.chat_id) WHERE t.id = ?",
            (tid,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["link"] = tg_link(d.pop("chat"), d.pop("tg"), d.pop("demo") or 0)
        d["text"] = (d["text"] or "")[:4000]
        return d
    row = conn.execute("SELECT dup_of, dup_kind, dup_score, dup_note, dup_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None or row["dup_of"] is None:
        return None
    now, old = one(task_id), one(row["dup_of"])
    if now is None or (scope is not None and now["project_id"] not in scope):
        return None
    return {"now": now, "old": old, "kind": row["dup_kind"], "score": row["dup_score"], "note": row["dup_note"], "checked_at": row["dup_at"]}


def suspicious(conn: sqlite3.Connection, since: str, scope: set[int] | None = None, dept: str | None = None) -> list[dict]:
    """Shubhali hisobotlar: takror yoki boshqaning ishi. Har birida asl yozuv sanasi bilan."""
    sql = ("SELECT t.id, t.title, t.assignee, t.done_at, t.dup_kind, t.dup_note, t.dup_score, p.name AS project, "
           "o.title AS old_title, o.assignee AS old_assignee, o.done_at AS old_done_at, " + LINK_COLS +
           "FROM tasks t JOIN projects p ON p.id = t.project_id JOIN tasks o ON o.id = t.dup_of "
           "LEFT JOIN messages m ON m.id = t.done_msg " + LINK_JOIN +
           "WHERE t.dup_kind IN ('takror', 'nusxa') AND t.done_at >= ?")
    args: list = [since]
    if scope is not None:
        sql += " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
    sql += _dept_sql(dept)
    args += [dept] if dept else []
    out = []
    for r in conn.execute(sql + " ORDER BY t.done_at DESC", args):
        d = links(dict(r))
        d["gap_days"] = (datetime.strptime(d["done_at"], FMT) - datetime.strptime(d["old_done_at"], FMT)).days
        out.append(d)
    return out


def day_report(conn: sqlite3.Connection, day: str, scope: set[int] | None = None, dept: str | None = None) -> list[dict]:
    """Bir kunlik hisobot: har xodim nima qildi, har ish og'irligi va belgilari, kunlik ish hajmi va taxminiy soat."""
    a, b = day + " 00:00:00", day + " 23:59:59"
    sql = ("SELECT t.id, t.title, t.assignee, t.done_at, t.done_msg, t.weight, t.hours, t.wcat, t.wnote, t.dup_kind, t.dup_note, "
           "t.dup_of, "
           "p.name AS project, p.id AS project_id, m.text AS msg_text, m.edited_at, m.deleted_at, "
           "o.title AS old_title, o.done_at AS old_done_at, o.assignee AS old_assignee, " + LINK_COLS +
           "FROM tasks t JOIN projects p ON p.id = t.project_id LEFT JOIN messages m ON m.id = t.done_msg "
           "LEFT JOIN tasks o ON o.id = t.dup_of " + LINK_JOIN + "WHERE t.status = 'done' AND t.done_at BETWEEN ? AND ?" + _no_outsiders())
    args: list = [a, b]
    if scope is not None:
        sql += " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
    sql += _dept_sql(dept)
    args += [dept] if dept else []
    people: dict[str, dict] = {}
    info = {r["name"]: dict(r) for r in conn.execute("SELECT name, department, username FROM people")}
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY t.done_at", args)]
    versions: dict[int, list] = {}
    mids = sorted({r["done_msg"] for r in rows if r["done_msg"]})
    for i in range(0, len(mids), 500):
        part = mids[i:i + 500]
        for e in conn.execute("SELECT message_id, at, kind, old_text FROM message_edits WHERE message_id IN (%s) ORDER BY at"
                              % ",".join("?" * len(part)), part):
            versions.setdefault(e["message_id"], []).append({"at": e["at"], "kind": e["kind"], "text": e["old_text"]})
    for d in rows:
        links(d)
        d["versions"] = versions.get(d["done_msg"], [])
        p = people.setdefault(d["assignee"], {"name": d["assignee"], "department": (info.get(d["assignee"]) or {}).get("department")
                                              or "Belgilanmagan", "items": []})
        p["items"].append(d)
    out = []
    for p in people.values():
        real = [i for i in p["items"] if i["dup_kind"] not in ("takror", "nusxa") and not i["deleted_at"]]
        p["count"] = len(p["items"])
        p["points"] = analytics._day_value([i["weight"] or 2 for i in real])  # reytingdagi kabi: mayda ishlar cheklovi bilan
        p["hours"] = round(sum(i["hours"] or 0 for i in real), 1)
        p["small"] = sum(1 for i in p["items"] if i["weight"] == 1)
        p["repeats"] = sum(1 for i in p["items"] if i["dup_kind"] in ("takror", "nusxa"))
        p["pending"] = sum(1 for i in p["items"] if i["weight"] is None)
        p["edited"] = sum(1 for i in p["items"] if i["edited_at"] or i["deleted_at"])
        p["flags"] = []
        if p["repeats"]:
            p["flags"].append("%d ta ish oldin ham yozilgan" % p["repeats"])
        if p["count"] >= 5 and p["small"] / p["count"] >= 0.6:
            p["flags"].append("Ko'pi mayda ish: %d tadan %d tasi" % (p["count"], p["small"]))
        if p["edited"]:
            p["flags"].append("Hisobot keyin o'zgartirilgan yoki o'chirilgan")
        out.append(p)
    out.sort(key=lambda p: (-p["points"], p["name"]))
    return out



def missing(conn: sqlite3.Connection, day: str, reported: set[str], scope: set[int] | None = None,
            dept: str | None = None) -> list[dict]:
    """Shu kuni hisobot bermaganlar: oxirgi 14 kunda ishlagan, lekin shu kuni bitta ham bajarilgan ish yozmagan xodimlar."""
    if datetime.strptime(day, "%Y-%m-%d").weekday() >= 5:
        return []
    sql = ("SELECT t.assignee AS name, max(t.done_at) AS last, count(*) AS n FROM tasks t WHERE t.status = 'done' "
           "AND t.done_at >= ? AND t.done_at < ? AND t.assignee IS NOT NULL" + _no_outsiders())
    args: list = [_days_before(day, 14), day + " 00:00:00"]
    if scope is not None:
        sql += " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
    sql += _dept_sql(dept)
    args += [dept] if dept else []
    head = conn.execute("SELECT name FROM people WHERE id = ?", (config.OWNER_ID,)).fetchone() if config.OWNER_ID else None
    out = [dict(r) for r in conn.execute(sql + " GROUP BY t.assignee", args)
           if r["name"] not in reported and (head is None or r["name"] != head["name"])]
    return sorted(out, key=lambda r: r["last"])


def days(conn: sqlite3.Connection, until: str, n: int = 14, scope: set[int] | None = None, dept: str | None = None) -> list[dict]:
    """Oxirgi n kun: har kunning ish hajmi va takrorlar soni (kunlar tasmasi uchun)."""
    sql = ("SELECT substr(done_at, 1, 10) AS day, count(*) AS items, "
           "sum(CASE WHEN dup_kind IN ('takror', 'nusxa') THEN 0 ELSE coalesce(weight, 2) END) AS points, "
           "sum(CASE WHEN dup_kind IN ('takror', 'nusxa') THEN 1 ELSE 0 END) AS repeats "
           "FROM tasks WHERE status = 'done' AND done_at >= ? AND done_at <= ?")
    args: list = [_days_before(until, n - 1), until + " 23:59:59"]
    if scope is not None:
        sql += " AND project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
    sql += _dept_sql(dept, "tasks")
    args += [dept] if dept else []
    got = {r["day"]: dict(r) for r in conn.execute(sql + " GROUP BY day", args)}
    start = datetime.strptime(until, "%Y-%m-%d")
    return [got.get(d, {"day": d, "items": 0, "points": 0, "repeats": 0})
            for d in ((start - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1))]


WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
REPEATS = ("takror", "nusxa")


def person_days(conn: sqlite3.Connection, name: str, until: str, n: int = 30, scope: set[int] | None = None) -> list[dict]:
    """Xodimning kunma-kun hisobotlari (eng yangisi birinchi): har kun yozgan ishlari og'irligi, taxminiy soati va
    takror belgisi (asl yozuv sanasi bilan). Ish kuni hech narsa yozmagan bo'lsa ham kun ro'yxatda qoladi: bo'shliq ko'rinsin."""
    sql = ("SELECT t.id, t.title, t.done_at, t.weight, t.hours, t.wnote, t.dup_kind, t.dup_note, p.name AS project, "
           "o.title AS old_title, o.done_at AS old_done_at, o.assignee AS old_assignee, m.edited_at, m.deleted_at, " + LINK_COLS +
           "FROM tasks t JOIN projects p ON p.id = t.project_id LEFT JOIN tasks o ON o.id = t.dup_of "
           "LEFT JOIN messages m ON m.id = t.done_msg " + LINK_JOIN +
           "WHERE t.assignee = ? AND t.status = 'done' AND t.done_at >= ? AND t.done_at <= ?")
    args: list = [name, _days_before(until, n - 1), until + " 23:59:59"]
    if scope is not None:
        sql += " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
    by_day: dict[str, list] = {}
    for r in conn.execute(sql + " ORDER BY t.done_at", args):
        by_day.setdefault(r["done_at"][:10], []).append(links(dict(r)))
    first = conn.execute("SELECT min(done_at) FROM tasks WHERE assignee = ?", (name,)).fetchone()[0]
    end = datetime.strptime(until, "%Y-%m-%d")
    out = []
    for i in range(n):
        d = end - timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        if first and key < first[:10]:
            break  # xodim kelishidan oldingi kunlar ko'rsatilmaydi
        items = by_day.get(key, [])
        real = [x for x in items if x["dup_kind"] not in ("takror", "nusxa") and not x["deleted_at"]]
        out.append({"day": key, "weekday": WEEKDAYS[d.weekday()], "workday": d.weekday() < 5, "items": items,
                    "count": len(items), "hours": round(sum(x["hours"] or 0 for x in real), 1),
                    "repeats": sum(1 for x in items if x["dup_kind"] in ("takror", "nusxa")),
                    "small": sum(1 for x in real if x["weight"] == 1)})
    return out


def person_growth(conn: sqlite3.Connection, name: str, until: str, days: int = 90, scope: set[int] | None = None) -> dict:
    """Xodim qanday o'zgargani: davrma-davr (3 oygacha haftalik, undan uzog'i oylik) ish hajmi, og'irlik, mayda ishlar,
    qayta yozilgan ishlar va muntazamlik. Rahbar "oldin eski ishni qayta yozardi, endi halol va og'irroq ishlayapti"
    kabi o'zgarishni raqam bilan ko'radi; oxirida birinchi va oxirgi yarmi solishtiriladi."""
    from . import analytics
    end = datetime.strptime(until, "%Y-%m-%d").date()
    start = end - timedelta(days=max(14, days) - 1)
    sql = ("SELECT t.done_at, t.weight, t.dup_kind, m.deleted_at FROM tasks t LEFT JOIN messages m ON m.id = t.done_msg "
           "WHERE t.assignee = ? AND t.status = 'done' AND t.done_at >= ? AND t.done_at <= ?")
    args: list = [name, start.isoformat(), until + " 23:59:59"]
    if scope is not None:
        sql += " AND t.project_id IN (%s)" % (",".join(str(int(x)) for x in scope) or "NULL")
    rows = [dict(r) for r in conn.execute(sql, args)]
    first = conn.execute("SELECT min(created_at) FROM tasks WHERE assignee = ?", (name,)).fetchone()[0]
    joined = max(start, datetime.strptime(first[:10], "%Y-%m-%d").date()) if first else end
    weekly = days <= 92

    def key(d):
        return (d - timedelta(days=d.weekday())).isoformat() if weekly else d.strftime("%Y-%m")
    buckets: dict[str, dict] = {}
    d = joined
    while d <= end:  # davrning ish kunlari (xodim kelganidan keyin)
        b = buckets.setdefault(key(d), {"davr": key(d), "ish_kunlari": 0, "kunlar": {}, "items": []})
        b["ish_kunlari"] += d.weekday() < 5
        d += timedelta(days=1)
    for r in rows:
        day = datetime.strptime(r["done_at"][:10], "%Y-%m-%d").date()
        b = buckets.get(key(day))
        if b is not None:
            b["items"].append(r)
            if r["dup_kind"] not in REPEATS and not r["deleted_at"]:
                b["kunlar"].setdefault(day.isoformat(), []).append(r["weight"] or 2)
    out = []
    for b in buckets.values():
        real = [x for x in b["items"] if x["dup_kind"] not in REPEATS and not x["deleted_at"]]
        rated = [x["weight"] for x in real if x["weight"]]
        wd = max(1, b["ish_kunlari"])
        vol = sum(analytics._day_value(ws) for ws in b["kunlar"].values())
        out.append({"davr": b["davr"], "ish_kunlari": b["ish_kunlari"],
                    "yozgan_kunlari": sum(1 for k in b["kunlar"] if datetime.strptime(k, "%Y-%m-%d").weekday() < 5),
                    "ishlar": len(real), "kunlik_hajm": round(vol / wd, 2),
                    "ortacha_ogirlik": round(sum(rated) / len(rated), 1) if rated else None,
                    "mayda_foiz": round(100 * sum(1 for w in rated if w == 1) / len(rated)) if rated else None,
                    "qayta_yozilgan": sum(1 for x in b["items"] if x["dup_kind"] in REPEATS)})
    half = len(out) // 2

    def avg(part, k):
        v = [x[k] for x in part if x[k] is not None]
        return round(sum(v) / len(v), 2) if v else None
    a, b = out[:half], out[half:]
    summary = {k: {"oldin": avg(a, k), "keyin": avg(b, k)} for k in ("kunlik_hajm", "ortacha_ogirlik", "mayda_foiz")} if half else {}
    if half:
        summary["qayta_yozilgan"] = {"oldin": sum(x["qayta_yozilgan"] for x in a), "keyin": sum(x["qayta_yozilgan"] for x in b)}
        summary["muntazamlik_foiz"] = {
            "oldin": round(100 * sum(x["yozgan_kunlari"] for x in a) / max(1, sum(x["ish_kunlari"] for x in a))),
            "keyin": round(100 * sum(x["yozgan_kunlari"] for x in b) / max(1, sum(x["ish_kunlari"] for x in b)))}
    return {"ism": name, "davr_turi": "hafta" if weekly else "oy", "boshlangan": joined.isoformat(), "davrlar": out,
            "solishtirish_birinchi_va_ikkinchi_yarmi": summary}
