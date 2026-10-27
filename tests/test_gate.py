"""Hisobot qabul qilish: faqat botga ulangan xodimdan; oddiy suhbat AI'ga yuborilmaydi; #hisobot tegi AI'siz o'qiladi."""
from datetime import datetime

import pytest

from puls import ai, config, db, settings
from puls.ingest import Incoming, ingest

CHAT = -100888
T0 = datetime(2026, 10, 22, 17, 0)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 1)
    db.init()
    c = db.connect()
    c.execute("INSERT INTO projects(key, name, chat_id, created_at) VALUES('portal', 'Portal', ?, '2026-10-01 09:00:00')", (CHAT,))
    yield c
    c.close()


@pytest.fixture()
def calls(monkeypatch):
    """AI yoqilgan, lekin har chaqiruv yoziladi: qaysi xabar AI'ga borganini tekshiramiz."""
    seen = []
    monkeypatch.setattr(config, "ai_enabled", lambda: True)
    monkeypatch.setattr(ai, "extract", lambda text, *a, **k: seen.append(text))
    return seen


def say(conn, mid, uid, name, text, when=T0):
    return ingest(conn, Incoming(CHAT, "Ish guruhi", mid, uid, name, None, when, text), use_ai=True)


def done_titles(conn, who):
    return [r["title"] for r in conn.execute("SELECT title FROM tasks WHERE assignee = ? AND status = 'done' ORDER BY id", (who,))]


def test_report_from_unlinked_employee_is_kept_but_not_accepted(conn, calls):
    settings.save(conn, {"report_from": "ulangan"})
    r = say(conn, 1, 7, "Aziz Karimov", "#hisobot #Portal\nBajarildi:\n1. Login sahifasi\n2. API ulandi")
    assert r.skipped and done_titles(conn, "Aziz Karimov") == [] and calls == []
    m = conn.execute("SELECT kind, source FROM messages WHERE msg_id = 1").fetchone()
    assert tuple(m) == ("none", "ulanmagan")
    assert conn.execute("SELECT name FROM people WHERE id = 7").fetchone()["name"] == "Aziz Karimov"  # rahbar havola yubora oladi
    conn.execute("UPDATE people SET dm_chat_id = 7 WHERE id = 7")  # shaxsiy havola orqali botga ulandi
    r = say(conn, 2, 7, "Aziz Karimov", "#hisobot #Portal\nBajarildi:\n1. Hisobot eksporti")
    assert not r.skipped and done_titles(conn, "Aziz Karimov") == ["Hisobot eksporti"]


def test_owner_is_accepted_without_linking(conn, calls):
    settings.save(conn, {"report_from": "ulangan"})
    r = say(conn, 1, 1, "Javohir Jumaboyev", "#hisobot #Portal\nBajarildi:\n1. Panel ko'rib chiqildi")
    assert not r.skipped and done_titles(conn, "Javohir Jumaboyev") == ["Panel ko'rib chiqildi"]


def test_chatter_never_reaches_the_model(conn, calls):
    for i, text in enumerate(("marojna yedim", "ok", "rahmat", "tushlikka boramizmi?", "Assalomu alaykum")):
        assert say(conn, i + 1, 7, "Aziz Karimov", text).kind == "none"
    assert calls == []
    say(conn, 10, 7, "Aziz Karimov", "slaydlar bitdi")  # qisqa, lekin ish belgisi bor: AI o'qiydi
    assert calls == ["slaydlar bitdi"]


def test_hisobot_tag_without_section_header_is_read_by_rules(conn, calls):
    r = say(conn, 1, 7, "Aziz Karimov", "#hisobot\n1. Login sahifasi API ga ulandi\n2. Hisobot eksporti tayyorlandi")
    assert calls == [] and r.kind == "done"
    assert done_titles(conn, "Aziz Karimov") == ["Login sahifasi API ga ulandi", "Hisobot eksporti tayyorlandi"]
    assert conn.execute("SELECT count(*) FROM projects WHERE key = 'hisobot'").fetchone()[0] == 0  # teg loyiha emas


def test_tag_only_mode_uses_no_model_at_all(conn, calls):
    settings.save(conn, {"ai_read": "teg"})
    r = say(conn, 1, 7, "Aziz Karimov", "Bugun login sahifasini tugatdim va API bilan ulab testga berdim")
    assert calls == [] and r.kind == "none"
    r = say(conn, 2, 7, "Aziz Karimov", "#done #Portal Login sahifasi")
    assert r.kind == "done" and calls == []


def test_admin_approves_person_and_earlier_reports_are_counted(conn, calls, monkeypatch):
    from puls import ingest as ing
    settings.save(conn, {"report_from": "ulangan"})
    conn.commit()
    r = say(conn, 1, 7, "Aziz Karimov", "#hisobot #Portal\nBajarildi:\n1. Login sahifasi")
    assert r.skipped
    conn.execute("UPDATE people SET status = 'xodim' WHERE id = 7")
    conn.commit()
    monkeypatch.setattr(ing, "process", lambda inc, use_ai=True: ing.ingest(conn, inc, use_ai=False))
    assert ing.welcome_back(7, days=3650) == 1
    assert done_titles(conn, "Aziz Karimov") == ["Login sahifasi"]
    conn.execute("UPDATE people SET status = 'begona' WHERE id = 7")
    assert say(conn, 2, 7, "Aziz Karimov", "#hisobot #Portal\nBajarildi:\n1. Hisobot eksporti").skipped


def test_group_name_gives_department_and_default_project(conn, calls):
    from puls.ingest import Incoming as Inc
    r = ingest(conn, Inc(-100999, "Backend jamoasi", 1, 8, "Bobur Aliyev", None, T0, "#hisobot\n1. API ulandi"), use_ai=True)
    assert r.kind == "done" and r.project == "Backend jamoasi" and not r.missing_project
    assert conn.execute("SELECT department FROM people WHERE id = 8").fetchone()["department"] == "Backend"


def test_by_default_everyone_counts_and_outsider_is_removed_everywhere(conn, calls):
    from puls import analytics, quality
    say(conn, 1, 7, "Aziz Karimov", "#hisobot #Portal\nBajarildi:\n1. Login sahifasi")       # tasdiqlanmagan, lekin qabul
    say(conn, 2, 9, "Mehmon Odam", "#hisobot #Portal\nBajarildi:\n1. Tashqi ish")
    assert done_titles(conn, "Aziz Karimov") == ["Login sahifasi"] and done_titles(conn, "Mehmon Odam") == ["Tashqi ish"]
    conn.execute("UPDATE people SET status = 'begona' WHERE id = 9")  # rahbar: bu xodim emas
    conn.commit()
    names = {p["name"] for p in analytics.compute(conn, "week", now=T0)["people"]}
    assert "Mehmon Odam" not in names and "Aziz Karimov" in names
    assert [p["name"] for p in quality.day_report(conn, T0.date().isoformat())] == ["Aziz Karimov"]


def test_every_group_is_one_project(conn, calls):
    """Rahbar: "o'nta guruh — o'nta loyiha". Teg boshqa loyiha ochmaydi, o'xshash nomli boshqa guruh loyihasi olinmaydi."""
    from puls.ingest import Incoming as Inc, ensure_group_projects
    say(conn, 1, 7, "Aziz Karimov", "#hisobot #Arxiv\n1. Skaner moduli")  # guruhning loyihasi bor: Portal
    assert conn.execute("SELECT name FROM projects ORDER BY id").fetchall()[-1]["name"] == "Portal"
    assert [r["project_id"] for r in conn.execute("SELECT project_id FROM tasks")] == [
        conn.execute("SELECT id FROM projects WHERE key = 'portal'").fetchone()["id"]]
    ingest(conn, Inc(-100555, "Portal - Ishlar", 1, 8, "Bobur Aliyev", None, T0, "#hisobot\n1. API ulandi"), use_ai=True)
    assert conn.execute("SELECT name FROM projects WHERE chat_id = -100555").fetchone()["name"] == "Portal - Ishlar"
    conn.execute("INSERT INTO chats(id, title, demo, added_at) VALUES(-100666, 'Shajara - Ishlar', 0, '2026-10-23 11:57:00')")
    assert ensure_group_projects(conn) == 1  # bot qo'shilgan, hali hisobot yo'q: loyiha baribir ko'rinadi
    assert conn.execute("SELECT name FROM projects WHERE chat_id = -100666").fetchone()["name"] == "Shajara - Ishlar"


def test_projects_today_show_who_wrote_and_who_did_not(conn, calls):
    from datetime import timedelta
    from puls import analytics
    say(conn, 1, 7, "Aziz Karimov", "#hisobot #Portal\n1. Login sahifasi", T0 - timedelta(days=1))
    say(conn, 2, 8, "Bobur Aliyev", "#hisobot #Portal\n1. API ulandi", T0 - timedelta(days=1))
    say(conn, 3, 8, "Bobur Aliyev", "#hisobot #Portal\n1. Hisobot eksporti", T0)
    conn.commit()
    p = next(x for x in analytics.compute(conn, "day", now=T0)["projects"] if x["key"] == "portal")
    assert p["people"] == ["Bobur Aliyev"] and p["absent"] == ["Aziz Karimov"]


def test_real_report_format_with_bloker_line(conn, calls):
    """23.10 Ahrorbek: "Bloker: ..." reja bandiga yopishib ketgan edi; "Bloker: yo'q" muammo emas."""
    text = ("#smartoffice_si #ai\n\nSana: 22.10.2026\n\nHolat: Sariq\n\nBajarildi:\n1.Analyze endpoint ga ohirgi o’zgarishlarni qo’shish.\n"
            "Ertangi reja:\n1. add_organization endpointni hatoliklarini to’g’irlash\nBloker: 409 va 422 berayotgan fayl berilmadi")
    say(conn, 1, 7, "Ahrorbek", text)
    assert [r["text"] for r in conn.execute("SELECT text FROM blockers")] == ["409 va 422 berayotgan fayl berilmadi"]
    assert [r["title"] for r in conn.execute("SELECT title FROM tasks WHERE status = 'open'")] == [
        "Add_organization endpointni hatoliklarini to’g’irlash"]
    say(conn, 2, 8, "Azizbek", "#smartoffice_si\nBajarildi:\n1. Hujjat profili qo'shildi\nBloker: Yo‘q")
    say(conn, 3, 9, "Erkin", "#smartoffice_si\nBajarildi:\n1. Dataset shakllantirildi\nBloker: Ha — test fayli berilmadi")
    assert [r["text"] for r in conn.execute("SELECT text FROM blockers ORDER BY id")] == [
        "409 va 422 berayotgan fayl berilmadi", "Test fayli berilmadi"]


def test_forwarded_old_report_counts_for_its_own_day(conn, calls):
    """Erkin kechagi hisobotini bugun forward qildi: ish kechaga yoziladi, bugungi ish bo'lib sanalmaydi."""
    from datetime import timedelta
    inc = Incoming(CHAT, "Ish guruhi", 1, 9, "Erkin", None, T0, "#hisobot\nBajarildi:\n1. Dataset shakllantirildi",
                   forwarded_at=T0 - timedelta(days=1))
    ingest(conn, inc, use_ai=True)
    assert conn.execute("SELECT done_at FROM tasks").fetchone()["done_at"] == "2026-10-21 18:00:00"


def test_hisobot_word_inside_a_sentence_is_not_a_report(conn, calls):
    """Guruhda tushuntirish: "#hisobot teg bilan yozilganda ..." — bu hisobot emas, ish bo'lib yozilmaydi."""
    text = ("#hisobot teg bilan yozilganda bot 100% adashmaydi\nteg bilan yozmasa ham model har bir habarni tekshiradi, "
            "hisobot yoki oddiy habar ekanini aniqlab, hisobot ga yaqin bo'lsa LLM ga uzatadi")
    r = say(conn, 1, 7, "Aziz Karimov", text)
    assert r.kind != "done" and done_titles(conn, "Aziz Karimov") == []
    r = say(conn, 2, 7, "Aziz Karimov", "#hisobot #Portal\n1. Login sahifasi")  # haqiqiy hisobot: teglar qatori
    assert done_titles(conn, "Aziz Karimov") == ["Login sahifasi"]


def test_sample_copied_as_is_does_not_open_placeholder_project(conn, calls):
    """Yo'riqnomadagi namuna so'zma-so'z ko'chirilsa ham "LoyihaNomi" degan loyiha ochilmaydi."""
    say(conn, 1, 7, "Aziz Karimov", "#hisobot #LoyihaNomi\nBajarildi:\n1. Login sahifasi API ga ulandi")
    assert done_titles(conn, "Aziz Karimov") == ["Login sahifasi API ga ulandi"]
    assert conn.execute("SELECT count(*) n FROM projects WHERE lower(name) = 'loyihanomi'").fetchone()["n"] == 0


def test_report_written_after_the_command_is_kept(conn, calls):
    """Xodim "#hisobot" o'rniga "/hisobot" deb boshlasa ham hisobot yo'qolmaydi; yolg'iz buyruq esa buyruqligicha qoladi."""
    from puls.bot import report_text
    assert report_text("/hisobot") is None and report_text("/hisobot@puls_loyiha_bot ") is None
    assert report_text("/hisobotlar ro'yxati") is None
    text = report_text("/hisobot@puls_loyiha_bot\nBajarildi:\n1. Login sahifasi")
    say(conn, 1, 7, "Aziz Karimov", text)
    assert done_titles(conn, "Aziz Karimov") == ["Login sahifasi"]


def test_guide_mentions_link_only_when_that_rule_is_on(conn):
    from puls import bot
    assert "shaxsiy havola" not in bot.guide()
    settings.save(conn, {"report_from": "ulangan"})
    conn.commit()
    assert "shaxsiy havola" in bot.guide()
