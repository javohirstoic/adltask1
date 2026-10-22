"""To'liq oqim: xabar -> vazifa -> bajarildi -> xavf qoidalari -> sozlamalar."""
from datetime import datetime, timedelta

import pytest

from analytics import services as analytics
from core import appsettings
from ingest.services import Incoming, ingest
from projects.models import Message, Project, Task

CHAT = -100123


def msg(mid, text, when, uid=1, name="Ali Valiyev", reply=None):
    return ingest(Incoming(CHAT, "Test", mid, uid, name, "ali", when, text, reply), use_ai=False)


def test_task_then_done_by_reply_and_by_text():
    t0 = datetime(2026, 10, 20, 9, 0)
    r = msg(1, "#task #Portal\n- Login sahifasi\n- Bosh sahifa", t0)
    assert r.kind == "task" and r.created == 2
    msg(2, "#done", t0 + timedelta(hours=2), reply=1)
    assert Task.objects.filter(status="done").count() == 2


@pytest.mark.parametrize("reply", ["Tayyor ✅", "Bajarildi 👍", "tayyor!"])
def test_short_reply_closes_parent_task(reply):
    t0 = datetime(2026, 10, 20, 9, 0)
    msg(1, "#task #Portal Login sahifasi", t0)
    msg(2, reply, t0 + timedelta(hours=2), reply=1)
    assert [(t.title, t.status) for t in Task.objects.all()] == [("Login sahifasi", "done")]  # "Tayyor ✅" nomli vazifa paydo bo'lmaydi


def test_done_matches_open_task():
    t0 = datetime(2026, 10, 20, 9, 0)
    msg(1, "#task #Portal Login sahifasi", t0)
    msg(2, "#done #Portal login sahifasi", t0 + timedelta(hours=3))
    assert Task.objects.count() == 1 and Task.objects.get().status == "done"  # yangi vazifa yaratilmadi, ochig'i yopildi


def test_edit_reverts_previous_effect():
    t0 = datetime(2026, 10, 20, 9, 0)
    msg(1, "#task #Portal Login sahifasi", t0)
    ingest(Incoming(CHAT, "Test", 1, 1, "Ali Valiyev", "ali", t0, "#task #Portal Bosh sahifa", edited=True), use_ai=False)
    assert list(Task.objects.values_list("title", flat=True)) == ["Bosh sahifa"]
    assert Message.objects.count() == 1


def test_duplicate_message_ignored():
    t0 = datetime(2026, 10, 20, 9, 0)
    msg(1, "#task #Portal Login sahifasi", t0)
    assert msg(1, "#task #Portal Login sahifasi", t0).duplicate


def test_overdue_project_is_critical_and_has_decision():
    now = datetime(2026, 10, 20, 12, 0)
    msg(1, "#deadline #Portal 18.10.2026", now - timedelta(days=5))
    msg(2, "#task #Portal Login sahifasi", now - timedelta(days=5))
    d = analytics.compute("week", now=now)
    p = d["projects"][0]
    assert p["level"] == 4 and p["risks"][0]["code"] == "overdue"
    assert any(x["action"] and x["action"]["type"] == "deadline" for x in d["decisions"])


def test_time_machine_hides_future():
    t0 = datetime(2026, 10, 15, 9, 0)
    msg(1, "#task #Portal Login sahifasi", t0)
    msg(2, "#done #Portal Login sahifasi", t0 + timedelta(days=3))
    past = analytics.compute("week", now=t0 + timedelta(days=1))
    assert past["projects"][0]["open_total"] == 1  # o'sha kuni hali bajarilmagan edi


def test_settings_validation():
    with pytest.raises(ValueError):
        appsettings.save({"silent_days": 99})
    assert appsettings.save({"silent_days": 5})["silent_days"] == 5


def test_same_telegram_name_gets_separate_people():
    t0 = datetime(2026, 10, 20, 9, 0)
    ingest(Incoming(CHAT, "T", 1, 11, "Ali", "ali_one", t0, "#task #Portal Birinchi ish"), use_ai=False)
    ingest(Incoming(CHAT, "T", 2, 22, "Ali", "ali_two", t0, "#task #Portal Ikkinchi ish"), use_ai=False)
    names = set(Task.objects.values_list("assignee__name", flat=True))
    assert len(names) == 2  # ikki alohida odam: vazifalari qo'shilib ketmaydi


def test_mentioned_stranger_is_linked_when_they_write():
    t0 = datetime(2026, 10, 20, 9, 0)
    ingest(Incoming(CHAT, "T", 1, 11, "Rahbar", "boss", t0, "#task #Portal Hisobot @newbie_1"), use_ai=False)
    task = Task.objects.get()
    assert task.assignee.telegram_id is None and task.assignee.username == "newbie_1"
    ingest(Incoming(CHAT, "T", 2, 99, "Yangi Xodim", "newbie_1", t0, "Salom"), use_ai=False)
    task.refresh_from_db()
    assert task.assignee.telegram_id == 99  # vazifa yangi odamga bog'liq qoldi
    assert Project.objects.count() == 1
