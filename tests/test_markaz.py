"""Boshqaruv sahifasi ma'lumotlari: reja bajarilishi, jarayondagi foiz, murojaat, kechikkan hisobot, holat, loyiha holati."""
from datetime import datetime

import pytest

from puls import ai, analytics, config, db
from puls.ingest import Incoming, ingest
from puls.parser import Item, Parsed

CHAT = -100555
AZIZ, BOBUR = (7, "Azizbek"), (8, "Bobur")


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 1)
    db.init()
    c = db.connect()
    yield c
    c.close()


@pytest.fixture()
def model(monkeypatch):
    answers = {}
    monkeypatch.setattr(config, "ai_enabled", lambda: True)
    monkeypatch.setattr(ai, "extract", lambda text, *a, **k: answers.get(text, Parsed("none", source="ai")))
    return answers


def say(conn, who, mid, text, when):
    return ingest(conn, Incoming(CHAT, "SmartOffice SI - Ishlar", mid, who[0], who[1], None, when, text), use_ai=True)


REPORT_1 = """#smartoffice_si #ai
Sana: 22.10.2026
Holat: Sariq
Bajarildi:
1. Yig'ilish xatlari uchun yangi profil qo'shildi
Jarayonda:
1. azizbek/yigilish branchidagi o'zgarishlarni commit va review'ga tayyorlash — 90%
Ertangi reja:
1. Savollarga javob olish
2. O'zgarishlarni commit qilish va review'ga berish"""


def test_plan_progress_status_and_late_report(conn, model):
    say(conn, AZIZ, 1, REPORT_1, datetime(2026, 10, 22, 19, 30))  # muddat 18:00 — kechikkan
    rows = {r["title"]: dict(r) for r in conn.execute("SELECT title, status, stage, progress, plan_day FROM tasks")}
    doing = rows["Azizbek/yigilish branchidagi o'zgarishlarni commit va review'ga tayyorlash"]
    assert doing["progress"] == 90 and doing["stage"] == "jarayon" and doing["plan_day"] == "2026-10-23"  # rejadagi takror shu vazifa
    assert rows["Savollarga javob olish"]["plan_day"] == "2026-10-23"
    assert len(rows) == 3  # bajarilgan 1 + jarayondagi 1 (rejadagi takror qo'shilmadi) + reja 1
    m = conn.execute("SELECT holat, report_day FROM messages").fetchone()
    assert (m["holat"], m["report_day"]) == ("sariq", "2026-10-22")
    say(conn, AZIZ, 2, "#smartoffice_si\nSana: 23.10.2026\nBajarildi:\n1. Savollarga javob olish", datetime(2026, 10, 23, 17, 0))
    conn.commit()
    d = analytics.compute(conn, "day", now=datetime(2026, 10, 23, 18, 30))
    p = d["projects"][0]
    assert (p["plan_total"], p["plan_done"]) == (2, 1)
    assert p["late_reports"] == [] and p["holat"] == {}  # 23-oktyabr hisoboti vaqtida, holat yozilmagan
    d22 = analytics.compute(conn, "day", now=datetime(2026, 10, 22, 23, 0))
    assert d22["projects"][0]["late_reports"] == ["Azizbek"] and d22["projects"][0]["holat"] == {"Azizbek": "sariq"}
    who = {x["name"]: x for x in d["people"]}
    assert (who["Azizbek"]["plan_total"], who["Azizbek"]["plan_done"], who["Azizbek"]["report_at"]) == (2, 1, "17:00")


def test_requests_make_a_project_critical_and_fix_closes_them(conn, model):
    for i, text in enumerate(["kabinetda arizalar bo'sh chiqyapti, to'g'rilab bering",
                              "pdf yuklab bo'lmayapti 5mb dan kattasida 413 beryapti",
                              "statistika sahifasi ochilmayapti, xato chiqyapti"], 1):
        model[text] = Parsed("request", items=[Item(text[:40])], source="ai")
        say(conn, BOBUR, i, text, datetime(2026, 10, 21, 10, i))
    say(conn, AZIZ, 9, "#smartoffice_si\nBajarildi:\n1. Profil sahifasi", datetime(2026, 10, 23, 12, 0))
    conn.commit()
    p = analytics.compute(conn, "day", now=datetime(2026, 10, 23, 15, 0))["projects"][0]
    assert p["requests_open"] == 3 and p["requests_oldest"] == 2 and p["pstate"] == "kritik"
    assert {x["kind"] for x in p["blocker_list"]} == {"murojaat"} and p["problems_open"] == 0
    bid = conn.execute("SELECT id FROM blockers ORDER BY id").fetchone()["id"]
    fix = "arizalar ro'yxatidagi filtr xatosini tuzatdim"
    model[fix] = Parsed("done", items=[Item("Arizalar filtri tuzatildi")], source="ai", solves=[bid])
    say(conn, AZIZ, 10, fix, datetime(2026, 10, 23, 15, 30))
    conn.commit()
    p = analytics.compute(conn, "day", now=datetime(2026, 10, 23, 16, 0))["projects"][0]
    assert p["requests_open"] == 2 and p["requests_closed"] == 1


def test_project_feed_shows_what_the_bot_took_from_each_message(conn, model):
    say(conn, AZIZ, 1, REPORT_1, datetime(2026, 10, 22, 19, 30))
    fix = "kabinetda arizalar bo'sh chiqyapti, to'g'rilab bering"
    model[fix] = Parsed("request", items=[Item("Kabinetda arizalar bo'sh chiqyapti")], source="ai")
    say(conn, BOBUR, 2, fix, datetime(2026, 10, 23, 10, 0))
    conn.commit()
    pid = conn.execute("SELECT id FROM projects").fetchone()["id"]
    feed = analytics.project_feed(conn, pid, datetime(2026, 10, 23).date(), 10)
    assert [m["author"] for m in feed] == ["Bobur", "Azizbek"]  # eng yangisi birinchi
    rep = feed[1]
    assert rep["late"] and rep["holat"] == "sariq" and rep["day"] == "2026-10-22"
    assert [len(rep["sections"][k]) for k in ("done", "doing", "plan")] == [1, 1, 2]
    assert rep["sections"]["doing"][0]["progress"] == 90
    assert feed[0]["requests"] == 1 and feed[0]["sections"]["blocker"][0]["title"].startswith("Kabinetda")


def test_blockers_list_and_report_times(conn, model):
    for i, text in enumerate(["pdf yuklab bo'lmayapti 5mb dan kattasida", "statistika sahifasi ochilmayapti"], 1):
        model[text] = Parsed("request", items=[Item(text[:30])], source="ai")
        say(conn, BOBUR, i, text, datetime(2026, 10, 20, 10, i))
    bid = conn.execute("SELECT id FROM blockers ORDER BY id").fetchone()["id"]
    fix = "pdf yuklash xatosini tuzatdim"
    model[fix] = Parsed("done", items=[Item("PDF yuklash tuzatildi")], source="ai", solves=[bid])
    say(conn, AZIZ, 5, fix, datetime(2026, 10, 22, 11, 0))
    say(conn, AZIZ, 6, "#smartoffice_si\nSana: 23.10.2026\nBajarildi:\n1. Profil", datetime(2026, 10, 23, 18, 40))
    conn.commit()
    b = analytics.blockers_list(conn, datetime(2026, 10, 23, 19, 0))
    assert len(b["open"]) == 1 and b["open"][0]["age"] == 3 and b["open"][0]["risk"] and b["open"][0]["kind"] == "murojaat"
    assert len(b["resolved"]) == 1 and b["resolved"][0]["age"] == 2
    p = analytics.compute(conn, "day", now=datetime(2026, 10, 23, 19, 0))["projects"][0]
    assert p["report_times"] == [{"name": "Azizbek", "at": "18:40", "on": "2026-10-23", "late": True}]


def test_parse_test_endpoint_reads_report_without_saving(tmp_path, monkeypatch):
    from puls import web
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "w.db")
    monkeypatch.setattr(config, "ai_enabled", lambda: False)
    db.init()
    j = web.parse_test(web.ParseTest(text=REPORT_1))
    assert j["kind"] == "done" and j["holat"] == "sariq" and j["sections"]["doing"][0]["progress"] == 90
    with db.session() as conn:
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_one_group_is_one_project(conn, model):
    from puls.ingest import ensure_group_projects
    say(conn, AZIZ, 1, "#smartoffice_si\nBajarildi:\n1. A ish", datetime(2026, 10, 21, 17, 0))
    say(conn, BOBUR, 2, "#shajara\nBajarildi:\n1. B ish", datetime(2026, 10, 21, 17, 30))  # boshqa teg — baribir shu guruh loyihasi
    assert conn.execute("SELECT count(*) FROM projects").fetchone()[0] == 1
    # teg rejimidan qolgan ortiqcha loyiha: birlashtiriladi, ishlari asosiy loyihaga o'tadi
    keep = conn.execute("SELECT id FROM projects").fetchone()["id"]
    conn.execute("INSERT INTO projects(key, name, chat_id, created_at, deadline) VALUES('eski', 'Eski teg', ?, '2026-10-20 10:00:00', '2026-11-01')", (CHAT,))
    old = conn.execute("SELECT id FROM projects WHERE key = 'eski'").fetchone()["id"]
    conn.execute("UPDATE tasks SET project_id = ? WHERE title = 'B ish'", (old,))
    conn.execute("INSERT INTO blockers(project_id, text, author, created_at, kind) VALUES(?, 'server yo''q', 'Bobur', '2026-10-21 10:00:00', 'muammo')", (old,))
    ensure_group_projects(conn)
    conn.commit()
    rows = conn.execute("SELECT id, deadline, aliases FROM projects").fetchall()
    assert [r["id"] for r in rows] == [keep] and rows[0]["deadline"] == "2026-11-01" and "Eski teg" in rows[0]["aliases"]
    assert {r["project_id"] for r in conn.execute("SELECT project_id FROM tasks UNION SELECT project_id FROM blockers")} == {keep}


def test_report_day_only_for_reports_and_backfill(conn, model):
    from puls.ingest import backfill_report_days
    q = "kabinetda arizalar bo'sh chiqyapti"
    model[q] = Parsed("request", items=[Item(q)], source="ai")
    say(conn, BOBUR, 1, q, datetime(2026, 10, 22, 10, 0))  # murojaat — hisobot emas
    say(conn, AZIZ, 2, REPORT_1, datetime(2026, 10, 22, 19, 30))
    days = [r["report_day"] for r in conn.execute("SELECT report_day FROM messages ORDER BY id")]
    assert days == [None, "2026-10-22"]
    # ustun qo'shilishidan oldingi hisobot: bir marta qayta o'qiladi, ikkinchi chaqiruv hech narsa qilmaydi
    conn.execute("UPDATE messages SET report_day = NULL, holat = NULL")
    assert backfill_report_days(conn) == 1 and backfill_report_days(conn) == 0
    assert tuple(conn.execute("SELECT report_day, holat FROM messages WHERE msg_id = 2").fetchone()) == ("2026-10-22", "sariq")


def test_repeat_proof_shows_both_original_messages(conn, model):
    from puls import quality
    say(conn, AZIZ, 1, "#smartoffice_si\nBajarildi:\n1. Kirim xatlarini test qilishda topilgan kamchiliklar tahlil qilindi", datetime(2026, 10, 20, 17, 0))
    say(conn, AZIZ, 2, "#smartoffice_si\nSana: 23.10.2026\nBajarildi:\n1. Kirim xatlarini test qilishda aniqlangan kamchiliklar tahlil qilindi",
        datetime(2026, 10, 23, 17, 5))
    a, b = [r["id"] for r in conn.execute("SELECT id FROM tasks ORDER BY id")]
    conn.execute("UPDATE tasks SET dup_of = ?, dup_kind = 'takror', dup_score = 0.93 WHERE id = ?", (a, b))
    pr = quality.repeat_proof(conn, b)
    assert pr["old"]["done_at"].startswith("2026-10-20") and pr["now"]["done_at"].startswith("2026-10-23")
    assert "topilgan kamchiliklar" in pr["old"]["text"] and "Sana: 23.10.2026" in pr["now"]["text"]
    assert pr["kind"] == "takror" and pr["old"]["assignee"] == "Azizbek"
    assert quality.repeat_proof(conn, a) is None  # asl ish takror emas
    assert quality.repeat_proof(conn, b, scope=set()) is None  # menejerga biriktirilmagan loyiha


def test_add_person_by_hand_then_link_joins_telegram_account(conn, model):
    from puls import actions, bot
    say(conn, (555, "Dilshod"), 1, "#smartoffice_si\nBajarildi:\n1. Login sahifasi", datetime(2026, 10, 22, 17, 0))
    conn.commit()
    a = actions.add_person("Dilshod Karimov", "Backend")
    assert "start=" in a["link"] and a["id"] < 0 and not a["linked"]
    b = actions.add_person("Sardor Aliyev")
    with pytest.raises(ValueError):
        actions.add_person("Sardor Aliyev")  # bir xil ism ikki marta qo'shilmaydi
    # havolani guruhga avval yozgan akkaunt bosdi: ikki yozuv bitta xodimga birlashadi
    assert bot._link_person(a["link"].split("start=")[1], 555) == "Dilshod Karimov"
    rows = {r["id"]: dict(r) for r in conn.execute("SELECT id, name, department, status, dm_chat_id FROM people")}
    assert rows[555]["name"] == "Dilshod Karimov" and rows[555]["department"] == "Backend" and rows[555]["dm_chat_id"] == 555
    assert not any(k < 0 and v["name"] == "Dilshod Karimov" for k, v in rows.items())
    assert conn.execute("SELECT assignee FROM tasks").fetchone()["assignee"] == "Dilshod Karimov"
    # hali hech narsa yozmagan akkaunt: vaqtinchalik id haqiqiysiga almashadi
    bot._link_person(b["link"].split("start=")[1], 777)
    assert conn.execute("SELECT name, status FROM people WHERE id = 777").fetchone()["name"] == "Sardor Aliyev"


KOMIL = """#hisobot #shajara #backend

Bajarildi:
1. RSEM tizimi DNK arizasini natijasini yuborishi uchun integratsiya API ishlab chiqildi.
2. DNK arizalariga natijalarni biriktirish imkoniyati qo'shildi.
3. BHM yaratishdagi xatolik tuzatildi."""


def test_copied_report_of_colleague_is_marked_and_not_counted_twice(conn, model):
    say(conn, AZIZ, 1, KOMIL, datetime(2026, 10, 23, 17, 7))
    say(conn, BOBUR, 2, KOMIL, datetime(2026, 10, 23, 19, 26))  # boshqa odam aynan shu hisobotni joyladi
    rows = conn.execute("SELECT title, assignee, dup_kind FROM tasks ORDER BY id").fetchall()
    assert [r["dup_kind"] for r in rows if r["assignee"] == "Azizbek"] == [None, None, None]
    bob = [r["dup_kind"] for r in rows if r["assignee"] == "Bobur"]
    assert bob[:2] == ["nusxa", "nusxa"] and bob[2] in ("nusxa", None)  # qisqa bandni ("BHM ... tuzatildi") tasodif deb qoldirishi mumkin
    conn.commit()
    p = analytics.compute(conn, "day", now=datetime(2026, 10, 23, 20, 0))["projects"][0]
    assert p["done"] == 3 + bob.count(None) and p["repeats"] == bob.count("nusxa")


def test_ongoing_item_under_done_and_fix_closes_related_task(conn, model):
    say(conn, AZIZ, 1, "#smartoffice_si\nBajarildi:\n1. Xalqaro hujjatlar testi natijalari o'rganildi\n2. Hozirgi pipeline ishlash jarayoni batafsilroq o'rganib chiqilmoqda",
        datetime(2026, 10, 23, 18, 0))
    st = {r["title"]: (r["status"], r["stage"]) for r in conn.execute("SELECT title, status, stage FROM tasks")}
    assert st["Hozirgi pipeline ishlash jarayoni batafsilroq o'rganib chiqilmoqda"] == ("open", "jarayon")
    assert st["Xalqaro hujjatlar testi natijalari o'rganildi"][0] == "done"
    q = "kabinetda arizalar hali ham bo'sh chiqyapti"
    model[q] = Parsed("request", items=[Item("Kabinetda arizalar bo'sh chiqishi")], source="ai")
    say(conn, BOBUR, 2, q, datetime(2026, 10, 23, 12, 37))
    t = "tushgacha qarab beraman"
    model[t] = Parsed("task", items=[Item("Kabinetdagi arizalarni tekshirish")], source="ai")
    say(conn, AZIZ, 3, t, datetime(2026, 10, 23, 12, 38))
    bid = conn.execute("SELECT id FROM blockers").fetchone()["id"]
    f = "api ni togriladim, filtr notogri ekan"
    model[f] = Parsed("done", items=[Item("API filtrini to'g'rilash")], source="ai", solves=[bid])
    say(conn, AZIZ, 4, f, datetime(2026, 10, 23, 12, 40))
    assert conn.execute("SELECT status FROM tasks WHERE title = 'Kabinetdagi arizalarni tekshirish'").fetchone()["status"] == "done"


def test_backfill_audit_fixes_old_records_once(conn, model):
    from puls.ingest import backfill_audit
    say(conn, AZIZ, 1, KOMIL, datetime(2026, 10, 23, 17, 7))
    say(conn, BOBUR, 2, KOMIL, datetime(2026, 10, 23, 19, 26))
    say(conn, AZIZ, 3, "#smartoffice_si\nBajarildi:\n1. Pipeline jarayoni batafsilroq o'rganib chiqilmoqda", datetime(2026, 10, 23, 21, 0))
    # eski kod holati: nusxa belgisi yo'q, davom etayotgan ish "bajarildi", hisobot kuni ishdan keyingi kun
    conn.execute("UPDATE tasks SET dup_kind = NULL, dup_of = NULL")
    conn.execute("UPDATE tasks SET status = 'done', stage = NULL, done_at = created_at, done_msg = created_msg WHERE title LIKE 'Pipeline%'")
    conn.execute("UPDATE messages SET report_day = '2026-10-24' WHERE msg_id = 1")
    st = backfill_audit(conn)
    assert st["kun"] == 1 and st["jarayon"] == 1 and st["nusxa"] >= 2
    assert backfill_audit(conn) == {}  # ikkinchi marta hech narsa qilmaydi
    assert conn.execute("SELECT report_day FROM messages WHERE msg_id = 1").fetchone()["report_day"] == "2026-10-23"


def test_real_person_with_id_in_old_demo_range_is_listed(conn, model):
    from puls import actions
    say(conn, (900686339, "A_D"), 1, "#smartoffice_si\nBajarildi:\n1. Pipeline natijalari o'rganildi", datetime(2026, 10, 23, 21, 53))
    conn.commit()
    assert "A_D" in [x["name"] for x in actions.invites()]  # oldin namuna oralig'i deb yashirilardi
    assert not db.is_demo_person(900686339) and db.is_demo_person(db.DEMO_LO + 5)


def test_matrix_shows_who_wrote_each_workday(conn, model):
    say(conn, AZIZ, 1, "#smartoffice_si\nBajarildi:\n1. A ish", datetime(2026, 10, 21, 17, 0))
    say(conn, BOBUR, 2, "#smartoffice_si\nBajarildi:\n1. B ish", datetime(2026, 10, 21, 17, 30))
    say(conn, AZIZ, 3, "#smartoffice_si\nBajarildi:\n1. C ish", datetime(2026, 10, 23, 17, 0))
    conn.commit()
    p = analytics.compute(conn, "day", now=datetime(2026, 10, 23, 18, 0))["projects"][0]
    m = {d: (w, e) for d, w, e in p["days10"]}
    assert len(p["days10"]) == 10 and m["2026-10-21"] == (2, 2) and m["2026-10-22"] == (0, 2) and m["2026-10-23"] == (1, 2)
    assert "2026-10-18" not in m  # yakshanba ish kuni emas
