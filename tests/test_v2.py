"""2-variant uchun: dalil havolalari, faqat o'qiladigan SQL, o'sish tahlili, agent asboblari (AI'siz)."""
from datetime import date, datetime, timedelta

import pytest

from puls import agent, analytics, config, db, quality, sqlro
from puls.ingest import Incoming, ingest

CHAT = -1004462255934  # superguruh: xabarga havola bo'ladi


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 0)
    db.init()
    c = db.connect()
    c.execute("INSERT INTO people(id, name, username, department) VALUES(2, 'Sardor Tursunov', 'sardor', 'Backend'), "
              "(3, 'Elyor Hasanov', 'elyor', 'Backend')")
    yield c
    c.close()


def say(conn, mid, uid, name, when, text, chat=CHAT):
    return ingest(conn, Incoming(chat, "Ish guruhi", mid, uid, name, None, when, text), use_ai=False)


def test_repeat_shows_both_messages_with_telegram_links(conn):
    say(conn, 101, 2, "Sardor Tursunov", datetime(2026, 10, 1, 17), "#hisobot #Portal\nBajarildi:\n1. Login sahifasi")
    say(conn, 202, 2, "Sardor Tursunov", datetime(2026, 10, 20, 17), "#hisobot #Portal\nBajarildi:\n1. Login sahifasi")
    item = quality.day_report(conn, "2026-10-20")[0]["items"][0]
    assert item["dup_kind"] == "takror"
    assert item["link"] == "https://t.me/c/4462255934/202" and item["old_link"] == "https://t.me/c/4462255934/101"
    sus = quality.suspicious(conn, "2026-10-01 00:00:00")[0]
    assert sus["link"].endswith("/202") and sus["old_link"].endswith("/101")
    day = quality.person_days(conn, "Sardor Tursunov", "2026-10-20", 3)[0]
    assert day["items"][0]["old_link"].endswith("/101")
    assert quality.tg_link(-12345, 7) is None and quality.tg_link(CHAT, 7, demo=1) is None  # oddiy va namuna guruhda havola yo'q


def test_boss_can_mark_not_a_repeat_and_it_counts_again(conn):
    say(conn, 1, 2, "Sardor Tursunov", datetime(2026, 10, 1, 17), "#done #Portal Login sahifasi")
    say(conn, 2, 2, "Sardor Tursunov", datetime(2026, 10, 20, 17), "#done #Portal Login sahifasi")
    t = conn.execute("SELECT id FROM tasks WHERE dup_kind = 'takror'").fetchone()
    conn.execute("UPDATE tasks SET dup_kind = 'rad', dup_note = 'Rahbar: takror emas' WHERE id = ?", (t["id"],))
    assert quality.suspicious(conn, "2026-10-01 00:00:00") == []
    assert quality.day_report(conn, "2026-10-20")[0]["points"] > 0  # ish yana hisobga kiradi


def test_readonly_sql_reads_views_and_refuses_writes(conn):
    say(conn, 1, 2, "Sardor Tursunov", datetime(2026, 10, 20, 17), "#done #Portal Login sahifasi")
    conn.commit()
    r = sqlro.query("SELECT kim, count(*) AS n FROM ishlar WHERE holat = 'bajarilgan' GROUP BY kim")
    assert r["ustunlar"] == ["kim", "n"] and r["qatorlar"] == [["Sardor Tursunov", 1]]
    for bad in ("DELETE FROM ishlar", "SELECT 1; DROP TABLE tasks", "UPDATE tasks SET title = 'x'", "SELECT * INTO x FROM ishlar",
                "SELECT pg_sleep(9)", "WITH a AS (DELETE FROM tasks RETURNING *) SELECT * FROM a"):
        with pytest.raises(ValueError):
            sqlro.query(bad)
    assert sqlro.check("SELECT nomi FROM ishlar WHERE nomi LIKE '%update qildim%'")  # matn ichidagi so'z xalaqit bermaydi


def _days(conn, uid, name, start, n, per_day, weight, repeat_from=None):
    d, k, mid = start, 0, uid * 100000 + start.toordinal() % 1000 * 100
    while k < n:
        if d.weekday() < 5:
            for i in range(per_day):
                mid += 1
                title = "%s ishi %s-%d" % (name.split()[0], d.isoformat(), i)
                say(conn, mid, uid, name, datetime(d.year, d.month, d.day, 17, i), "#done #Portal " + title)
            k += 1
        d += timedelta(days=1)
    conn.execute("UPDATE tasks SET weight = ? WHERE assignee = ? AND done_at >= ?", (weight, name, start.isoformat()))


def test_growth_sees_a_person_who_stopped_reposting_and_works_heavier(conn):
    """Oldin eski ishni qayta yozardi va yengil ish qilardi, oxirgi 2 haftada halol va og'irroq: "Ancha o'sdi"."""
    _days(conn, 2, "Sardor Tursunov", date(2026, 9, 14), 20, 2, 1)
    old = conn.execute("SELECT id FROM tasks WHERE assignee = 'Sardor Tursunov' ORDER BY id LIMIT 3").fetchall()
    late = conn.execute("SELECT id FROM tasks WHERE assignee = 'Sardor Tursunov' AND done_at >= '2026-09-28' "
                        "AND done_at < '2026-10-09' ORDER BY id LIMIT 3").fetchall()
    for o, t in zip(old, late):  # 28.09–08.10 orasida 3 ta eski ish qayta yozilgan
        conn.execute("UPDATE tasks SET dup_kind = 'takror', dup_of = ? WHERE id = ?", (o["id"], t["id"]))
    _days(conn, 2, "Sardor Tursunov", date(2026, 10, 12), 10, 3, 4)
    _days(conn, 3, "Elyor Hasanov", date(2026, 9, 14), 30, 2, 2)
    data = analytics.compute(conn, "week", now=datetime(2026, 10, 23, 18))
    g = {p["name"]: p["growth"] for p in data["people"]}
    assert g["Sardor Tursunov"]["verdict"] == "ancha_osdi"
    assert any("to'xtatdi" in w for w in g["Sardor Tursunov"]["why"])
    assert g["Elyor Hasanov"]["verdict"] in ("barqaror", "osdi", "pasaydi")
    assert any(d.get("good") and "Sardor" in d["title"] for d in data["decisions"])  # rahmat aytish taklifi
    gr = quality.person_growth(conn, "Sardor Tursunov", "2026-10-23", 60)
    assert gr["davr_turi"] == "hafta" and gr["solishtirish_birinchi_va_ikkinchi_yarmi"]["qayta_yozilgan"]["keyin"] == 0


def test_agent_tools_answer_without_model(conn, monkeypatch):
    monkeypatch.setattr(config, "now", lambda: datetime(2026, 10, 21, 18))
    say(conn, 1, 2, "Sardor Tursunov", datetime(2026, 10, 20, 17), "#done #Portal Login sahifasi")
    say(conn, 2, 3, "Elyor Hasanov", datetime(2026, 10, 19, 17), "#done #Portal Kesh qatlami")
    conn.commit()
    ctx = agent.Ctx(None, None)
    rep = agent.t_kun_hisoboti(ctx, "kecha")
    assert [p["kim"] for p in rep["hisobot_yozganlar"]] == ["Sardor Tursunov"] and rep["hisobot_yozmaganlar"] == ["Elyor Hasanov"]
    assert ctx.person("sardor")["name"] == "Sardor Tursunov"
    with pytest.raises(agent.ToolError):
        ctx.person("Botir")
    ctx.sql = True
    assert agent.t_sql(ctx, "SELECT count(*) AS n FROM ishlar")["qatorlar"] == [[2]]
    agent.t_taklif(ctx, "rahmat", kimga="Sardor", matn="yaxshi ish uchun")  # ism "kimga" da kelsa ham tushuniladi
    assert ctx.proposals[-1]["action"] == {"type": "thank_person", "name": "Sardor Tursunov", "text": "yaxshi ish uchun"}
