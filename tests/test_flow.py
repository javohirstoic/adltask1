"""To'liq oqim: xabar -> vazifa -> bajarildi -> xavf qoidalari -> sozlamalar (vaqtinchalik bazada)."""
from datetime import datetime, timedelta

import pytest

from puls import analytics, config, db, settings
from puls.ingest import Incoming, ingest

CHAT = -100123


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.init()
    c = db.connect()
    yield c
    c.close()


def msg(conn, mid, text, when, uid=1, name="Ali Valiyev", reply=None):
    return ingest(conn, Incoming(CHAT, "Test", mid, uid, name, "ali", when, text, reply), use_ai=False)


def test_task_then_done_by_reply_and_by_text(conn):
    t0 = datetime(2026, 10, 20, 9, 0)
    r = msg(conn, 1, "#task #Portal\n- Login sahifasi\n- Bosh sahifa", t0)
    assert r.kind == "task" and r.created == 2
    msg(conn, 2, "#done", t0 + timedelta(hours=2), reply=1)
    assert conn.execute("SELECT count(*) FROM tasks WHERE status='done'").fetchone()[0] == 2


@pytest.mark.parametrize("reply", ["Tayyor ✅", "Bajarildi 👍", "tayyor!"])
def test_short_reply_closes_parent_task(conn, reply):
    t0 = datetime(2026, 10, 20, 9, 0)
    msg(conn, 1, "#task #Portal Login sahifasi", t0)
    msg(conn, 2, reply, t0 + timedelta(hours=2), reply=1)
    rows = conn.execute("SELECT title, status FROM tasks").fetchall()
    assert [(r["title"], r["status"]) for r in rows] == [("Login sahifasi", "done")]  # "Tayyor ✅" nomli vazifa paydo bo'lmaydi


def test_done_matches_open_task(conn):
    t0 = datetime(2026, 10, 20, 9, 0)
    msg(conn, 1, "#task #Portal Login sahifasi", t0)
    msg(conn, 2, "#done #Portal login sahifasi", t0 + timedelta(hours=3))
    row = conn.execute("SELECT status, count(*) n FROM tasks").fetchone()
    assert row["status"] == "done" and row["n"] == 1  # yangi vazifa yaratilmadi, ochig'i yopildi


def test_edit_reverts_previous_effect(conn):
    t0 = datetime(2026, 10, 20, 9, 0)
    msg(conn, 1, "#task #Portal Login sahifasi", t0)
    ingest(conn, Incoming(CHAT, "Test", 1, 1, "Ali Valiyev", "ali", t0, "#task #Portal Bosh sahifa", edited=True), use_ai=False)
    titles = [r["title"] for r in conn.execute("SELECT title FROM tasks")]
    assert titles == ["Bosh sahifa"]


def test_duplicate_message_ignored(conn):
    t0 = datetime(2026, 10, 20, 9, 0)
    msg(conn, 1, "#task #Portal Login sahifasi", t0)
    assert msg(conn, 1, "#task #Portal Login sahifasi", t0).duplicate


def test_overdue_project_is_critical_and_has_decision(conn):
    now = datetime(2026, 10, 20, 12, 0)
    msg(conn, 1, "#deadline #Portal 18.10.2026", now - timedelta(days=5))
    msg(conn, 2, "#task #Portal Login sahifasi", now - timedelta(days=5))
    d = analytics.compute(conn, "week", now=now)
    p = d["projects"][0]
    assert p["level"] == 4 and p["risks"][0]["code"] == "overdue"
    assert any(x["action"] and x["action"]["type"] == "deadline" for x in d["decisions"])


def test_time_machine_hides_future(conn):
    t0 = datetime(2026, 10, 15, 9, 0)
    msg(conn, 1, "#task #Portal Login sahifasi", t0)
    msg(conn, 2, "#done #Portal Login sahifasi", t0 + timedelta(days=3))
    past = analytics.compute(conn, "week", now=t0 + timedelta(days=1))
    assert past["projects"][0]["open_total"] == 1  # o'sha kuni hali bajarilmagan edi


def test_settings_validation(conn):
    with pytest.raises(ValueError):
        settings.save(conn, {"silent_days": 99})
    assert settings.save(conn, {"silent_days": 5})["silent_days"] == 5
