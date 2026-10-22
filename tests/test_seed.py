"""Namuna tashkilot: kun bo'yi jonli oqim (navbat) va xodim holatlari taqsimoti."""
from collections import Counter
from datetime import date, datetime, time

from puls import analytics, config, db, seed


def test_demo_day_is_released_over_time(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    morning = datetime.combine(date(2026, 10, 21), time(8, 30))
    st = seed.run(False, morning, True)
    assert st["queued"] > 10 and seed.seeded_day() == "2026-10-21"
    with db.session() as c:
        assert c.execute("SELECT max(m.date) FROM messages m JOIN chats ch ON ch.id = m.chat_id WHERE ch.demo = 1").fetchone()[0] <= "2026-10-21 08:30:00"
    released = seed.release(morning.replace(hour=12))
    assert 0 < released < st["queued"]
    with db.session() as c:
        assert c.execute("SELECT count(*) FROM demo_queue").fetchone()[0] == st["queued"] - released
        people = analytics.compute(c, "week", now=morning.replace(hour=12))["people"]
    states = Counter(p["state"] for p in people)
    assert len(people) >= 50
    assert states["ok"] > len(people) / 2                      # ko'pchilik me'yorida
    assert 2 <= states["overloaded"] <= 6 and states["idle"] >= 2  # ishi ko'p ham, bo'sh ham bor
