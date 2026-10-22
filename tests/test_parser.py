from datetime import date

from ingest.parser import extract_items, match_score, parse_date, parse_format, parse_free

TODAY = date(2026, 10, 20)
PROJECTS = [
    {"key": "portal", "name": "Yangi portal", "aliases": "portal"},
    {"key": "arxiv", "name": "Arxivni raqamlashtirish", "aliases": "arxiv"},
    {"key": "hujjataylanishi", "name": "Hujjat aylanishi", "aliases": "hujjat aylanishi"},
]


def test_format_task_multiline_with_mentions():
    p = parse_format("#task #Portal\n- Login sahifasi @demo_aziz\n- SMS tasdiqlash", TODAY)
    assert p.kind == "task" and p.project == "Portal"
    assert [i.title for i in p.items] == ["Login sahifasi", "SMS tasdiqlash"]
    assert p.items[0].assignee == "@demo_aziz" and p.items[1].assignee is None


def test_format_done_and_deadline():
    assert parse_format("#done #Arxiv Skaner moduli", TODAY).kind == "done"
    d = parse_format("#deadline #Portal 15.11.2026", TODAY)
    assert d.kind == "deadline" and d.deadline == date(2026, 11, 15)


def test_no_type_tag_is_not_format():
    assert parse_format("#Portal login tayyor", TODAY) is None


def test_dates():
    assert parse_date("2026-11-15", TODAY) == date(2026, 11, 15)
    assert parse_date("15-noyabr", TODAY) == date(2026, 11, 15)
    assert parse_date("ertaga", TODAY) == date(2026, 10, 21)
    assert parse_date("5.01", TODAY) == date(2027, 1, 5)  # o'tgan oy emas, kelgusi yil


def test_free_text_kinds_and_project():
    p = parse_free("Portal: login sahifasi tayyor bo'ldi", PROJECTS)
    assert p.kind == "done" and p.project == "portal" and p.items[0].title == "Login sahifasi"
    assert parse_free("Arxivda skaner drayveri ishlamayapti", PROJECTS).kind == "blocker"
    assert parse_free("Login xatoligi tuzatildi", PROJECTS).kind == "done"
    assert parse_free("Rahmat, ertaga 10:00 da yig'ilish", PROJECTS).kind == "none"
    t = parse_free("Portal: SMS tasdiqlash qilish kerak, @demo_aziz olsin", PROJECTS)
    assert t.kind == "task" and t.items[0].title == "SMS tasdiqlash" and t.items[0].assignee == "@demo_aziz"


def test_reply_word_is_done():
    assert parse_free("Tayyor ✅", PROJECTS).kind == "done"


def test_project_needs_both_words():
    assert parse_free("Hujjatlar ro'yxati tayyor", PROJECTS).project is None


def test_header_line_is_not_a_task():
    items = extract_items("Portal bo'yicha bugungi vazifalar:\n- Login sahifasi\n- Bosh sahifa", "task", PROJECTS[0])
    assert [i.title for i in items] == ["Login sahifasi", "Bosh sahifa"]


def test_match_score():
    assert match_score("Login sahifasi — backend", "Portal: login sahifasi — backend tayyor bo'ldi") >= 0.9
    assert match_score("Login sahifasi — backend", "Arxiv katalogi — testlar") < 0.5
