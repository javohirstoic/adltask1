"""Namuna tashkilot: kun bo'yi jonli oqim (navbat) va xodim holatlari taqsimoti."""
from collections import Counter
from datetime import date, datetime, time

from analytics import services as analytics
from core import demo
from ingest.models import DemoQueueItem
from projects.models import Message


def test_demo_day_is_released_over_time():
    morning = datetime.combine(date(2026, 10, 21), time(8, 30))
    st = demo.run(False, morning, True)
    assert st["queued"] > 10 and demo.seeded_day() == "2026-10-21"
    assert Message.objects.filter(chat__demo=True).order_by("-date").first().date <= morning
    released = demo.release(morning.replace(hour=12))
    assert 0 < released < st["queued"]
    assert DemoQueueItem.objects.count() == st["queued"] - released
    people = analytics.compute("week", now=morning.replace(hour=12))["people"]
    states = Counter(p["state"] for p in people)
    assert len(people) >= 50
    assert states["ok"] > len(people) / 2                      # ko'pchilik me'yorida
    assert 2 <= states["overloaded"] <= 6 and states["idle"] >= 2  # ishi ko'p ham, bo'sh ham bor
