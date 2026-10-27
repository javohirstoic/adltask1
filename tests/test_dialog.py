"""Guruhdagi jonli yozishma (23.10 sinovi): reply bilan muammoni hal qilish, kechki hisobot va hamkasb ishini o'ziniki qilish."""
from datetime import date, datetime

import pytest

from puls import ai, config, db, quality
from puls.ingest import Incoming, ingest
from puls.parser import Item, Parsed

CHAT = -100777
MARK, ELON = (7, "Mark Zuckerberg", "mark"), (8, "Elon Musk", "elon")


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 1)
    db.init()
    c = db.connect()
    c.execute("INSERT INTO projects(key, name, chat_id, created_at) VALUES('kabinet', 'Kabinet', ?, '2026-10-01 09:00:00')", (CHAT,))
    yield c
    c.close()


@pytest.fixture()
def model(monkeypatch):
    """Til modeli o'rnida: matn -> javob. Model ko'rgan kontekst ham yoziladi."""
    answers, seen = {}, {}
    monkeypatch.setattr(config, "ai_enabled", lambda: True)

    def extract(text, author, projects, today, retries=1, context=None, lead=False):
        seen[text] = context or {}
        return answers.get(text, Parsed("none", source="ai"))
    monkeypatch.setattr(ai, "extract", extract)
    return answers, seen


def say(conn, who, mid, text, hm, reply=None):
    uid, name, username = who
    when = datetime(2026, 10, 23, *map(int, hm.split(":")))
    return ingest(conn, Incoming(CHAT, "Kabinet guruhi", mid, uid, name, username, when, text, reply), use_ai=True)


def done(conn, who):
    return [r["title"] for r in conn.execute("SELECT title FROM tasks WHERE assignee = ? AND status = 'done' ORDER BY id", (who[1],))]


def test_model_can_point_only_at_ids_it_was_shown():
    p = ai._normalize({"kind": "done", "items": [{"title": "Login", "same_as": 99}, {"title": "API", "same_as": 4}],
                       "solves": [5, 77]}, [], set(), {4}, {5})
    assert [i.same_as for i in p.items] == [None, 4] and p.solves == [5]
    p = ai._normalize({"kind": "task", "items": [{"title": "SMS", "same_as": 4}], "solves": [5]}, [], set(), {4}, {5})
    assert p.items[0].same_as is None and p.solves == []


def test_fixing_a_colleagues_problem_by_reply_closes_it_and_never_an_unrelated_task(conn, model):
    answers, _ = model
    bug = "kabinetda pdf yuklab bolmayapti 5mb dan kattasini tashlasa 413 beryapti"
    answers[bug] = Parsed("blocker", items=[Item("Kabinetda katta pdf yuklab bo'lmayapti")], source="ai")
    sms = "sms xabarnomani siz davom ettira olasizmi? men boshlab qoygandim feature/sms branchida turibdi"
    answers[sms] = Parsed("task", items=[Item("Sms xabarnoma", "@elon")], source="ai")
    say(conn, ELON, 30, bug, "12:39")
    say(conn, MARK, 35, sms, "12:40")
    sms_id = conn.execute("SELECT id FROM tasks WHERE title = 'Sms xabarnoma'").fetchone()["id"]
    fix = "pdf ham boldi, nginxda limit 2mb turgan ekan 20 qildim"
    # Model adashib boshqa odamning SMS vazifasini ko'rsatdi (prod'da aynan shunday bo'lgan)
    answers[fix] = Parsed("done", items=[Item("PDF yuklash limitini oshirish")], source="ai", refs=[sms_id])
    say(conn, MARK, 37, fix, "12:41", reply=30)
    assert conn.execute("SELECT status FROM tasks WHERE id = ?", (sms_id,)).fetchone()["status"] == "open"
    assert conn.execute("SELECT resolved_at FROM blockers").fetchone()["resolved_at"] is not None
    assert done(conn, MARK) == ["PDF yuklash limitini oshirish"]  # boshqaning muammosini hal qilish — uning ishi


def test_taking_a_module_over_does_not_close_the_colleagues_task(conn, model):
    answers, _ = model
    sms = "sms xabarnomani siz davom ettira olasizmi? men boshlab qoygandim feature/sms branchida turibdi"
    answers[sms] = Parsed("task", items=[Item("SMS xabarnoma", "@elon")], source="ai")
    say(conn, MARK, 35, sms, "12:40")
    sms_id = conn.execute("SELECT id FROM tasks").fetchone()["id"]
    took = "mayli olaman seshanbagacha bitkazaman"
    answers[took] = Parsed("reassign", items=[Item("SMS xabarnoma", "@elon", date(2026, 10, 27))], source="ai", refs=[sms_id])
    say(conn, ELON, 36, took, "12:41", reply=35)
    assert conn.execute("SELECT deadline FROM tasks").fetchone()["deadline"] == "2026-10-27"
    evening = "bugun qilganlarim\n1) sms modulini oldim, kodini korib chiqdim"
    answers[evening] = Parsed("done", items=[Item("SMS modulini ko'rib chiqish")], source="ai", refs=[sms_id])
    say(conn, MARK, 38, evening, "18:05")
    assert conn.execute("SELECT status, assignee FROM tasks WHERE id = ?", (sms_id,)).fetchone()["status"] == "open"
    assert done(conn, MARK) == ["SMS modulini ko'rib chiqish"]


def test_accepting_a_request_by_reply_updates_it_instead_of_a_second_task(conn, model):
    answers, _ = model
    sms = "sms xabarnomani siz davom ettira olasizmi? men boshlab qoygandim feature/sms branchida turibdi"
    answers[sms] = Parsed("task", items=[Item("SMS xabarnoma")], source="ai")  # "siz" kimligini model bilmadi
    say(conn, MARK, 35, sms, "12:40")
    took = "mayli olaman seshanbagacha bitkazaman"
    answers[took] = Parsed("task", items=[Item("SMS xabarnoma", None, date(2026, 10, 27))], source="ai")
    say(conn, ELON, 36, took, "12:41", reply=35)
    rows = [tuple(r) for r in conn.execute("SELECT title, assignee, deadline, status FROM tasks")]
    assert rows == [("SMS xabarnoma", "Elon Musk", "2026-10-27", "open")]


def test_order_from_the_lead_goes_to_the_team_not_to_the_lead(conn, model):
    """Feruzbek (guruh admini) guruhga "Dashboard da bu yerdagi tasklarni bot tortsin" yozdi: bu uning o'z ishi emas."""
    from puls.ingest import Incoming as Inc
    answers, _ = model
    order = "Dashboard da bu yerdagi tasklarni bot tortsin"
    answers[order] = Parsed("task", items=[Item("Dashboardga guruhdagi tasklarni tortish")], source="ai")
    boss = Inc(CHAT, "Kabinet guruhi", 44, 50, "Feruzbek Jurayev", "fjurayev", datetime(2026, 10, 23, 12, 59), order, admin=True)
    ingest(conn, boss, use_ai=True)
    t = conn.execute("SELECT assignee, status FROM tasks").fetchone()
    assert (t["assignee"], t["status"]) == (None, "open")  # jamoaga: kim olishi ochiq
    assert conn.execute("SELECT role FROM people WHERE id = 50").fetchone()["role"] == "rahbar"
    took = "men qilaman bugun kechgacha bitkazaman"
    answers[took] = Parsed("task", items=[Item("Dashboardga guruhdagi tasklarni tortish", None, date(2026, 10, 23))], source="ai")
    say(conn, MARK, 45, took, "13:05", reply=44)
    rows = [tuple(r) for r in conn.execute("SELECT assignee, deadline FROM tasks")]
    assert rows == [("Mark Zuckerberg", "2026-10-23")]


def test_admin_marked_as_employee_in_panel_stays_an_employee(conn, model):
    answers, _ = model
    plan = "ertaga swagger hujjatini yangilab chiqaman albatta"
    answers[plan] = Parsed("task", items=[Item("Swagger hujjatini yangilash")], source="ai")
    conn.execute("INSERT INTO people(id, name, username, role) VALUES(7, 'Mark Zuckerberg', 'mark', '')")  # panel: rahbar emas
    from puls.ingest import Incoming as Inc
    ingest(conn, Inc(CHAT, "Kabinet guruhi", 46, 7, "Mark Zuckerberg", "mark", datetime(2026, 10, 23, 18, 0), plan, admin=True), use_ai=True)
    assert conn.execute("SELECT assignee FROM tasks").fetchone()["assignee"] == "Mark Zuckerberg"
    assert conn.execute("SELECT role FROM people WHERE id = 7").fetchone()["role"] == ""


def test_member_who_joined_but_never_wrote_is_seen_as_not_writing(conn, model):
    """Abduaziz guruhga qo'shildi, lekin yozmadi: u jamoada "hali yozmagan", loyihada "yozmadi" bo'lib turadi; chiqib ketsa yo'qoladi."""
    from puls import analytics
    from puls import ingest as ing
    answers, _ = model
    fix = "pdf ham boldi, nginxda limit 2mb turgan ekan 20 qildim"
    answers[fix] = Parsed("done", items=[Item("PDF yuklash limitini oshirish")], source="ai")
    say(conn, MARK, 37, fix, "12:41")
    ing.member_joined(conn, CHAT, "Kabinet guruhi", 77, "Abduaziz", "abduaz1z", "2026-10-23 15:03:00")
    ing.member_joined(conn, CHAT, "Kabinet guruhi", 50, "Feruzbek Jurayev", "fjurayev", "2026-10-23 15:03:00")
    conn.execute("UPDATE people SET role = 'rahbar' WHERE id = 50")
    conn.commit()
    now = datetime(2026, 10, 23, 18, 0)
    data = analytics.compute(conn, "day", now=now)
    who = {p["name"]: p for p in data["people"]}
    assert who["Abduaziz"]["state"] == "silent" and "Feruzbek Jurayev" not in who
    proj = next(p for p in data["projects"] if p["chat_id"] == CHAT)
    assert proj["people"] == ["Mark Zuckerberg"] and proj["absent"] == ["Abduaziz"]
    ing.member_left(conn, CHAT, 77, "2026-10-23 17:00:00")
    conn.commit()
    data = analytics.compute(conn, "day", now=now)
    assert "Abduaziz" not in {p["name"] for p in data["people"]}


def test_own_problem_solved_by_others_is_not_work(conn, model):
    answers, _ = model
    answers["aka test bazaga dostup yoq ekan, ishlay olmayapman"] = Parsed("blocker", items=[Item("Test bazaga dostup yo'q")], source="ai")
    answers["dostup berishdi hammasi joyida endi rahmat"] = Parsed("done", items=[Item("Test bazaga dostup olindi")], source="ai")
    say(conn, MARK, 32, "aka test bazaga dostup yoq ekan, ishlay olmayapman", "12:39")
    say(conn, MARK, 40, "dostup berishdi hammasi joyida endi rahmat", "13:10", reply=32)
    assert conn.execute("SELECT resolved_at FROM blockers").fetchone()["resolved_at"] is not None
    assert done(conn, MARK) == []


def test_fix_written_without_reply_closes_the_problem_a_colleague_reported(conn, model):
    answers, seen = model
    bug = "kabinetda arizalar hali ham bo'sh chiqyapti, kecha ham shunaqa edi"
    answers[bug] = Parsed("blocker", items=[Item("Kabinetda arizalar bo'sh chiqishi")], source="ai")
    say(conn, ELON, 25, bug, "12:37")
    bid = conn.execute("SELECT id FROM blockers").fetchone()["id"]
    fix = "api ni togriladim, filtr notogri ekan statusga emas sanaga qarab olyotgan edi"
    answers[fix] = Parsed("done", items=[Item("API filtr xatosini tuzatish")], source="ai", solves=[bid])
    say(conn, MARK, 33, fix, "12:39")
    assert [b["id"] for b in seen[fix]["problems"]] == [bid]
    assert conn.execute("SELECT resolved_at FROM blockers").fetchone()["resolved_at"] is not None
    assert done(conn, MARK) == ["API filtr xatosini tuzatish"]


def test_evening_summary_counts_work_already_written_in_chat_once(conn, model):
    answers, seen = model
    noon = "api ni togriladim, filtr notogri ekan statusga emas sanaga qarab olyotgan edi. bir korib qoying"
    answers[noon] = Parsed("done", items=[Item("API filtr xatosini tuzatish")], source="ai")
    say(conn, MARK, 33, noon, "12:39")
    api_id = conn.execute("SELECT id FROM tasks WHERE title = 'API filtr xatosini tuzatish'").fetchone()["id"]
    evening = ("bugun qilganlarim\n1) kabinetda arizalar bo'sh chiqayotgan edi tuzatdim\n"
               "2) sms modulini oldim, kodini korib chiqdim")
    answers[evening] = Parsed("done", source="ai", items=[
        Item("Kabinetda arizalar bo'sh chiqishini tuzatish", same_as=api_id), Item("SMS modulini ko'rib chiqish")])
    say(conn, MARK, 38, evening, "18:05")
    assert [t["id"] for t in seen[evening]["today"]] == [api_id]  # model kun ichida yozilganni ko'rdi
    assert done(conn, MARK) == ["API filtr xatosini tuzatish", "SMS modulini ko'rib chiqish"]


def test_colleagues_result_written_as_own_goes_to_the_judge(conn, model, monkeypatch):
    answers, _ = model
    fix = "pdf ham boldi, nginxda limit 2mb turgan ekan 20 qildim"
    answers[fix] = Parsed("done", items=[Item("PDF yuklashdagi 413 xatoni tuzatish")], source="ai")
    say(conn, MARK, 37, fix, "12:41")
    mark_id = conn.execute("SELECT id FROM tasks").fetchone()["id"]
    claim = "bugun notarius bilan otirdim. pdf yuklash xatosini ham tuzatdim"
    answers[claim] = Parsed("done", source="ai", items=[Item("Notarius endpointlari"), Item("PDF yuklash xatosini tuzatish", same_as=mark_id)])
    say(conn, ELON, 39, claim, "18:10")
    assert done(conn, ELON) == ["Notarius endpointlari", "PDF yuklash xatosini tuzatish"]  # ish yoziladi, hukm hakamniki
    asked = []

    def judge(prompt, schema):
        asked.append(prompt)
        return {"results": [{"i": 1, "verdict": "takror", "reason": "Markning tuzatgan ishi o'ziniki qilib yozilgan"}]}
    monkeypatch.setattr(quality, "_ask", judge)
    monkeypatch.setattr(quality.memory, "vectors", lambda *a, **k: {})
    quality.check_repeats(conn)
    row = conn.execute("SELECT dup_kind, dup_of FROM tasks WHERE title = 'PDF yuklash xatosini tuzatish'").fetchone()
    assert (row["dup_kind"], row["dup_of"]) == ("nusxa", mark_id)
    assert fix in asked[0] and claim in asked[0]  # hakam ikkala asl xabarni ko'rdi


def test_lead_posting_a_sample_report_is_not_counted_as_an_employee(conn, model):
    """Feruzbek (rahbar) guruhga boshqaning hisobotini namuna qilib tashladi: u xodimlar qatoriga va "yozdi"ga kirmaydi."""
    from puls import analytics
    from puls.ingest import Incoming as Inc
    ingest(conn, Inc(CHAT, "Kabinet guruhi", 51, 50, "Feruzbek Jurayev", "fjurayev", datetime(2026, 10, 23, 15, 3),
                     "#hisobot\nBajarildi:\n1. 2000 ta xat pipeline dan o'tkazildi", admin=True), use_ai=True)
    say(conn, MARK, 52, "#hisobot\nBajarildi:\n1. PDF yuklash limiti oshirildi", "15:10")
    conn.commit()
    data = analytics.compute(conn, "day", now=datetime(2026, 10, 23, 18, 0))
    assert {p["name"] for p in data["people"]} == {"Mark Zuckerberg"}
    assert next(p for p in data["projects"] if p["chat_id"] == CHAT)["people"] == ["Mark Zuckerberg"]
