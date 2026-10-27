"""Hisobot sifati: ish og'irligi (til modeli), eski ishni qayta yozish, tahrir va o'chirish izi."""
from datetime import datetime

import pytest

from puls import analytics, config, db, ingest, quality
from puls.ingest import Incoming

CHAT = -100555


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 0)
    monkeypatch.setattr(config, "AI_PROVIDER", "off")  # testlar internetga chiqmaydi: model kerak joyda soxta javob
    db.init()
    c = db.connect()
    c.execute("INSERT INTO people(id, name, username, department) VALUES(2, 'Sardor Tursunov', 'demo_sardor', 'Backend'), "
              "(3, 'Elyor Hasanov', 'demo_elyor', 'Backend')")
    yield c
    c.close()


def report(conn, uid, name, msg_id, when, text):
    return ingest.ingest(conn, Incoming(CHAT, "G", msg_id, uid, name, None, when, text), use_ai=False)


def done(conn, title):
    return conn.execute("SELECT * FROM tasks WHERE title = ? ORDER BY id DESC", (title,)).fetchone()


def test_same_work_reported_weeks_later_is_flagged(conn):
    report(conn, 2, "Sardor Tursunov", 1, datetime(2026, 9, 1, 17), "#done #Portal Login sahifasi")
    report(conn, 2, "Sardor Tursunov", 2, datetime(2026, 10, 20, 17), "#done #Portal Login sahifasi")
    report(conn, 2, "Sardor Tursunov", 3, datetime(2026, 10, 20, 17, 5), "#done #Portal Hisobot eksporti")
    quality.check_repeats(conn)
    new = conn.execute("SELECT * FROM tasks WHERE title = 'Login sahifasi' ORDER BY done_at DESC").fetchone()
    assert new["dup_kind"] == "takror" and "2026-09-01" in new["dup_note"]
    assert done(conn, "Hisobot eksporti")["dup_kind"] is None and done(conn, "Hisobot eksporti")["dup_at"]
    rows = quality.suspicious(conn, "2026-10-01 00:00:00")
    assert [(r["assignee"], r["gap_days"]) for r in rows] == [("Sardor Tursunov", 49)]


def test_colleagues_work_is_a_copy_and_same_day_double_post_is_a_repeat(conn):
    report(conn, 3, "Elyor Hasanov", 1, datetime(2026, 10, 1, 17), "#done #Portal Server monitoringi sozlandi")
    report(conn, 2, "Sardor Tursunov", 2, datetime(2026, 10, 20, 12), "#done #Portal Server monitoringi sozlandi")
    report(conn, 2, "Sardor Tursunov", 3, datetime(2026, 10, 20, 12), "#done #Portal Kesh qatlami")
    report(conn, 2, "Sardor Tursunov", 4, datetime(2026, 10, 20, 18), "#done #Portal Kesh qatlami")
    quality.check_repeats(conn)
    kinds = [r["dup_kind"] for r in conn.execute("SELECT dup_kind FROM tasks WHERE assignee = 'Sardor Tursunov' ORDER BY id")]
    assert kinds == ["nusxa", None, "takror"]  # bir kunda ikkinchi marta yozilgan ish ham ikki marta hisoblanmaydi


def test_model_weights_are_cached_and_drive_points(conn, monkeypatch):
    calls = []

    def fake(prompt, schema):
        calls.append(prompt)
        lines = [ln for ln in prompt.splitlines() if ln[:1].isdigit() and " | " in ln]
        return {"results": [{"i": n + 1, "weight": 5 if "Integratsiya" in ln else 1, "hours": 30 if "Integratsiya" in ln else 0.2,
                             "category": "yangi" if "Integratsiya" in ln else "kichik", "reason": "test"}
                            for n, ln in enumerate(lines)]}
    monkeypatch.setattr(config, "ai_enabled", lambda: True)
    monkeypatch.setattr(quality, "_ask", fake)
    when = datetime(2026, 10, 20, 17)
    report(conn, 2, "Sardor Tursunov", 1, when, "#done #Portal Integratsiya MVD bilan")
    for i, t in enumerate(("Tugma rangi", "Tugma matni", "Ikonka joyi", "Shrift o'lchami", "Logo kattaligi", "Tugma soyasi", "Menyu rangi")):
        report(conn, 3, "Elyor Hasanov", 10 + i, when, "#done #Portal " + t)
    assert quality.evaluate(conn) == 8 and len(calls) == 1
    report(conn, 3, "Elyor Hasanov", 30, datetime(2026, 10, 21, 17), "#done #Portal Tugma rangi")
    assert quality.evaluate(conn) == 1 and len(calls) == 1  # bir xil nom qayta baholanmaydi
    data = analytics.compute(conn, "custom", "2026-10-20", "2026-10-20", now=datetime(2026, 10, 21, 18))
    pts = {p["name"]: p["points"] for p in data["people"]}
    # 7 ta mayda ish (3 tasi to'liq, qolgani chorak) bitta katta ishdan kam: ro'yxatni uzaytirish reytingni oshirmaydi
    assert pts == {"Sardor Tursunov": 5, "Elyor Hasanov": 4}
    day = quality.day_report(conn, "2026-10-20")
    elyor = next(p for p in day if p["name"] == "Elyor Hasanov")
    assert elyor["small"] == 7 and any("mayda" in f for f in elyor["flags"])


def test_edited_and_deleted_reports_keep_their_history(conn):
    when = datetime(2026, 10, 20, 17)
    report(conn, 2, "Sardor Tursunov", 1, when, "#done #Portal Tahlil natijalari")
    inc = Incoming(CHAT, "G", 1, 2, "Sardor Tursunov", None, when, "#done #Portal Tahlil hisoboti tayyorlandi", edited=True)
    ingest.ingest(conn, inc, use_ai=False)
    m = conn.execute("SELECT * FROM messages WHERE msg_id = 1").fetchone()
    edits = conn.execute("SELECT * FROM message_edits WHERE message_id = ?", (m["id"],)).fetchall()
    assert m["edited_at"] and [e["old_text"] for e in edits] == ["#done #Portal Tahlil natijalari"]
    assert ingest.deleted(conn, CHAT, [1]) == 1
    day = quality.day_report(conn, "2026-10-20")[0]
    assert day["edited"] == 1 and day["points"] == 0 and len(day["items"][0]["versions"]) == 2


def test_missing_reporters_are_listed(conn):
    report(conn, 2, "Sardor Tursunov", 1, datetime(2026, 10, 19, 17), "#done #Portal Kesh qatlami")
    report(conn, 3, "Elyor Hasanov", 2, datetime(2026, 10, 20, 17), "#done #Portal Monitoring")
    day = quality.day_report(conn, "2026-10-20")
    assert [m["name"] for m in quality.missing(conn, "2026-10-20", {p["name"] for p in day})] == ["Sardor Tursunov"]


def test_rank_is_relative_and_unique_for_large_teams():
    rows = [{"name": "X%04d" % i, "score": 50 + (i % 40), "pace": i / 10, "avg_weight": 1 + (i % 5), "rated": 10,
             "small": i % 7, "trend": (i % 90) - 45, "repeats30": int(i % 97 == 0)} for i in range(1000)]
    analytics.rank_people(rows)
    assert sorted(r["rank"] for r in rows) == list(range(1, 1001))  # 1000 xodimda ham har biri o'z o'rnida
    best = min(rows, key=lambda r: r["rank"])
    assert best["score"] == 89 and best["grade"] == "Eng yaxshi 1% ichida"
    assert max(rows, key=lambda r: r["rank"])["grade"] == "Eng past 1% ichida"
    assert any(t["key"] == "repeat" for t in rows[0]["traits"]) and any(t["key"] == "down" for t in rows[1]["traits"])


def test_reworded_old_work_is_found_by_meaning(conn, monkeypatch):
    """Embedding yo'li (PostgreSQL'da pgvector, SQLite'da numpy): so'zlari boshqa, ma'nosi bir xil eski ish topiladi."""
    from puls import memory
    words = {"login": 0, "kirish": 0, "sahifa": 1, "oyna": 1, "eksport": 2, "hisobot": 3}

    def fake_embed(texts, task_type, patient=False):
        out = []
        for t in texts:
            v = [0.0] * memory.DIM
            for w in t.lower().split():
                v[next((i for k, i in words.items() if w.startswith(k)), 10 + len(w))] += 1
            out.append(v)
        return out
    monkeypatch.setattr(config, "ai_enabled", lambda: True)
    monkeypatch.setattr(memory, "_embed", fake_embed)
    monkeypatch.setattr(quality, "_judge", lambda conn, pairs: {i: ("takror", "bir xil ish") for i in range(len(pairs))})
    report(conn, 2, "Sardor Tursunov", 1, datetime(2026, 9, 10, 17), "#done #Portal Login sahifasi")
    report(conn, 2, "Sardor Tursunov", 2, datetime(2026, 9, 11, 17), "#done #Portal Hisobot eksporti")
    report(conn, 2, "Sardor Tursunov", 3, datetime(2026, 10, 20, 17), "#done #Portal Kirish oynasi")
    quality.check_repeats(conn)
    t = conn.execute("SELECT * FROM tasks WHERE title = 'Kirish oynasi'").fetchone()
    old = conn.execute("SELECT title FROM tasks WHERE id = ?", (t["dup_of"],)).fetchone()
    assert t["dup_kind"] == "takror" and old["title"] == "Login sahifasi"


def _seed(conn, uid, name, days, per_day, weight, start=1):
    """Xodim har ish kuni per_day ta ish yozadi (og'irligi weight). days: necha ish kuni, start: oktyabrning qaysi kunidan."""
    from datetime import date, timedelta
    d, n, mid = date(2026, 10, start), 0, uid * 100000 + start * 1000
    while n < days:
        if d.weekday() < 5:
            for i in range(per_day):
                mid += 1
                report(conn, uid, name, mid, datetime(d.year, d.month, d.day, 17, i), "#done #Portal %s ishi %d-%d" % (name.split()[0], d.day, i))
            n += 1
        d += timedelta(days=1)
    conn.execute("UPDATE tasks SET weight = ? WHERE assignee = ?", (weight, name))


def test_new_employee_is_compared_per_day_not_by_total(conn):
    """Yangi xodim yig'indida faxriydan ancha kam, lekin kuniga ko'proq va og'irroq ish qilsa — reytingda ustun."""
    conn.execute("INSERT INTO people(id, name, username, department) VALUES(4, 'Nodir Yangi', 'demo_nodir', 'Backend')")
    _seed(conn, 2, "Sardor Tursunov", 18, 2, 2)              # 1-oktyabrdan beri, kuniga 2 ta o'rtacha ish
    _seed(conn, 3, "Elyor Hasanov", 18, 2, 2)
    _seed(conn, 4, "Nodir Yangi", 11, 2, 4, start=9)         # 9-oktyabrda kelgan, kuniga 2 ta og'ir ish
    data = analytics.compute(conn, "week", now=datetime(2026, 10, 23, 18))
    p = {x["name"]: x for x in data["people"]}
    new, old = p["Nodir Yangi"], p["Sardor Tursunov"]
    assert new["points"] <= old["points"] * 2 and new["pace"] > old["pace"] * 1.5
    assert new["rank"] == 1 and not new["new"] and new["evidence"] >= 10


def test_first_days_are_provisional_and_pulled_to_team_middle(conn):
    """Ikki kunlik ma'lumot bilan yangi xodim birinchi o'ringa otilib chiqmaydi: reytingi jamoa o'rtachasiga yaqin, "Yangi" belgisi bor."""
    conn.execute("INSERT INTO people(id, name, username, department) VALUES(4, 'Nodir Yangi', 'demo_nodir', 'Backend')")
    _seed(conn, 2, "Sardor Tursunov", 17, 3, 4)
    _seed(conn, 3, "Elyor Hasanov", 17, 2, 2)
    _seed(conn, 4, "Nodir Yangi", 2, 3, 5, start=22)
    data = analytics.compute(conn, "week", now=datetime(2026, 10, 23, 18))
    p = {x["name"]: x for x in data["people"]}
    new = p["Nodir Yangi"]
    assert new["new"] and new["evidence"] == 2 and any(t["key"] == "new" for t in new["traits"])
    assert p["Elyor Hasanov"]["score"] < new["score"] < p["Sardor Tursunov"]["score"]


def test_weekly_rank_move_is_reported(conn):
    """Bir hafta oldin oxirgi bo'lgan, keyin kuchaygan xodimning o'rni ko'tarilgani ko'rinadi."""
    _seed(conn, 2, "Sardor Tursunov", 17, 2, 3)
    _seed(conn, 3, "Elyor Hasanov", 12, 1, 1)
    _seed(conn, 3, "Elyor Hasanov", 5, 4, 5, start=17)
    conn.execute("UPDATE tasks SET weight = 1 WHERE assignee = 'Elyor Hasanov' AND done_at < '2026-10-16'")
    data = analytics.compute(conn, "week", now=datetime(2026, 10, 23, 18))
    p = {x["name"]: x for x in data["people"]}
    assert p["Elyor Hasanov"]["move"] == 1 and p["Sardor Tursunov"]["move"] == -1


def test_panel_shows_who_repeats_old_work_with_example(conn):
    """Bot xodimga hech narsa demaydi, lekin panel kim, nechta va qaysi eski ishni qayta yozganini ko'rsatadi."""
    report(conn, 2, "Sardor Tursunov", 1, datetime(2026, 10, 1, 17), "#done #Portal Login sahifasi")
    report(conn, 2, "Sardor Tursunov", 2, datetime(2026, 10, 20, 17), "#done #Portal Login sahifasi")
    report(conn, 3, "Elyor Hasanov", 3, datetime(2026, 10, 20, 17), "#done #Portal Kesh qatlami")
    data = analytics.compute(conn, "week", now=datetime(2026, 10, 21, 18))
    q = {p["name"]: p["q28"] for p in data["people"]}
    ex = q["Sardor Tursunov"]["example"]
    assert q["Sardor Tursunov"]["repeats"] == 1 and ex["title"] == "Login sahifasi" and ex["old_at"].startswith("2026-10-01")
    assert q["Elyor Hasanov"]["repeats"] == 0 and q["Elyor Hasanov"]["example"] is None
