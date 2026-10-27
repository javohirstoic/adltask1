"""Xodimlarning haqiqiy kunlik hisobot formati: #loyiha #bo'lim, Sana, Bajarildi / Jarayonda / Reja / Muammo."""
from datetime import date, datetime

import pytest

from puls import config, db, ingest
from puls.ingest import Incoming
from puls.parser import parse_report

REAL = """#shajara #backend

Sana: 22.10.2026

Bajarildi:
1. Tadqiqot arizasi statuslarini o'zgartirish logikasiga RESEARCH_REVIEW dan IN_RESEARCH ga qaytarish qismini qo'shish. Sabab Tadqiqotchi yuklagan natija yoki xulosa Manager ga ma'qul bo'lmasa, Tadqiqotchi tadqiqotni qayta ko'rib chiqishi kerak;
2. Tadqiqot natijasini olish uchun Portalga alohida Controller va API ishlab chiqish;
3. Tadqiqot natijasi javobiga createdAt qiymatini qo'shib qaytarish;
4. DNK arizasini to'liq ma'lumotini  id orqali olish uchun API ishlab chiqish;
5. DNK arizalarini yaratishda frontendga ma'lumot qaytarish."""


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.init()
    c = db.connect()
    yield c
    c.close()


def send(conn, text, when, msg_id=1, uid=7):
    return ingest.ingest(conn, Incoming(-100123, "Shajara", msg_id, uid, "Ali Valiyev", "ali", when, text), use_ai=False)


def test_real_report_is_read_exactly():
    p = parse_report(REAL, date(2026, 10, 22))
    assert p.project == "shajara" and p.department == "Backend" and p.day == date(2026, 10, 22)
    done = p.sections["done"]
    assert len(done) == 5
    assert done[0].title == "Tadqiqot arizasi statuslarini o'zgartirish logikasiga RESEARCH_REVIEW dan IN_RESEARCH ga qaytarish qismini qo'shish"
    assert done[0].note.startswith("Sabab Tadqiqotchi")
    assert done[4].title == "DNK arizalarini yaratishda frontendga ma'lumot qaytarish"


def test_real_report_creates_project_work_and_department(conn):
    r = send(conn, REAL, datetime(2026, 10, 22, 18, 5))
    assert (r.kind, r.closed, r.project, r.missing_project) == ("done", 5, "Shajara", False)
    assert conn.execute("SELECT count(*) FROM tasks WHERE status = 'done' AND assignee = 'Ali Valiyev'").fetchone()[0] == 5
    assert conn.execute("SELECT department FROM people WHERE id = 7").fetchone()[0] == "Backend"


def test_yesterdays_report_written_in_the_morning_counts_for_yesterday(conn):
    text = REAL.replace("Sana: 22.10.2026", "Sana: 21.10.2026")
    send(conn, text, datetime(2026, 10, 22, 9, 15))
    assert {r[0] for r in conn.execute("SELECT done_at FROM tasks")} == {"2026-10-21 18:00:00"}


def test_sections_wrapped_lines_and_russian_headers():
    text = """#portal #frontend
Дата: 20.10.2026
Выполнено:
- Login sahifasi
  mobil ko'rinishi ham tayyor
- Parolni tiklash formasi
Jarayonda:
1) Profil sahifasi
Reja:
1) Bildirishnomalar
Muammo: test serverga kirish yo'q"""
    p = parse_report(text, date(2026, 10, 20))
    assert [i.title for i in p.sections["done"]] == ["Login sahifasi mobil ko'rinishi ham tayyor", "Parolni tiklash formasi"]
    assert [i.title for i in p.sections["doing"]] == ["Profil sahifasi"]
    assert [i.title for i in p.sections["plan"]] == ["Bildirishnomalar"]
    assert [i.title for i in p.sections["blocker"]] == ["Test serverga kirish yo'q"]
    assert p.department == "Frontend" and p.project == "portal"


def test_in_progress_items_repeated_daily_stay_one_task(conn):
    day1 = "#portal\nJarayonda:\n1. Profil sahifasi\nReja:\n1. Bildirishnomalar"
    send(conn, day1, datetime(2026, 10, 20, 18), msg_id=1)
    send(conn, day1.replace("Profil sahifasi", "Profil sahifasi."), datetime(2026, 10, 21, 18), msg_id=2)
    rows = conn.execute("SELECT title, status, stage FROM tasks ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("Profil sahifasi", "open", "jarayon"), ("Bildirishnomalar", "open", None)]
    send(conn, "#portal\nBajarildi:\n1. Profil sahifasi", datetime(2026, 10, 22, 18), msg_id=3)
    assert conn.execute("SELECT status FROM tasks WHERE title = 'Profil sahifasi'").fetchone()[0] == "done"


def test_plain_messages_are_not_reports():
    assert parse_report("Bajarildi login sahifasi", date(2026, 10, 22)) is None
    assert parse_report("Rahmat, ertaga gaplashamiz", date(2026, 10, 22)) is None
    assert parse_report("Reja:\n", date(2026, 10, 22)) is None


def test_same_report_posted_twice_is_not_counted_twice(conn):
    first = send(conn, REAL, datetime(2026, 10, 23, 5, 56), msg_id=1)
    again = send(conn, REAL, datetime(2026, 10, 23, 5, 57), msg_id=2)
    assert first.repeats == [] and len(again.repeats) == 5
    kinds = [r[0] for r in conn.execute("SELECT dup_kind FROM tasks ORDER BY id")]
    assert kinds == [None] * 5 + ["takror"] * 5
    from puls import analytics
    data = analytics.compute(conn, "custom", "2026-10-22", "2026-10-22", now=datetime(2026, 10, 23, 9))
    assert sum(p["repeats"] for p in data["people"]) == 5  # ish baliga faqat birinchisi kirdi


def test_edited_report_is_not_a_repeat_of_itself(conn):
    send(conn, REAL, datetime(2026, 10, 23, 5, 56), msg_id=1)
    inc = Incoming(-100123, "Shajara", 1, 7, "Ali Valiyev", "ali", datetime(2026, 10, 23, 5, 56), REAL + "\n6. Yana bitta ish", edited=True)
    r = ingest.ingest(conn, inc, use_ai=False)
    assert r.repeats == [] and conn.execute("SELECT count(*) FROM tasks WHERE dup_kind IS NOT NULL").fetchone()[0] == 0


def test_real_team_report_titles_progress_and_status():
    """24.10 haqiqiy hisobotlar: qisqa nom + ostida uzun tafsilot, uzun band ma'no chegarasidan, "— 90%" va "Holat: Sariq"."""
    text = """#smartoffice_si #ai

Sana: 22.10.2026

Holat: Sariq

Bajarildi:
1. 2000 ta xat sinovi
db_Xalqaro_huquqiy_2000 dagi 2000 ta xat pipeline dan o‘tkazildi (21-oktabr, 4 soat 44 daqiqa, xatosiz). PDF bor 1955 ta xatdan 1552 tasida (79,4%) tizim ijrochini tanladi
2. Videoselektor xatlariga reyestrdagi ikkinchi topshiriq (hududiy adliya organlari, muddatsiz) va jo‘natuvchiga qarab topshiriq matni qo‘shildi; topshiriqlar soni reyestr bilan 47% → 94% mos
Jarayonda:
1. azizbek/yigilish branchidagi o‘zgarishlarni commit va review’ga tayyorlash — 90%"""
    p = parse_report(text, date(2026, 10, 23))
    assert p.holat == "sariq" and p.day == date(2026, 10, 22)
    done = p.sections["done"]
    assert done[0].title == "2000 ta xat sinovi" and done[0].note.startswith("db_Xalqaro_huquqiy_2000")
    assert done[1].title.endswith("topshiriq matni qo‘shildi") and done[1].note == "topshiriqlar soni reyestr bilan 47% → 94% mos"
    assert p.sections["doing"][0].progress == 90 and not p.sections["doing"][0].title.endswith("%")
