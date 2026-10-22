"""Bot handlerlari: soxta Telegram xabari bilan (tarmoqsiz) — async va ORM birga to'g'ri ishlashini tekshiradi."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from people.models import Person
from projects.models import Task
from telegram import bot

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def shared_connection(monkeypatch):
    # test bazasi bitta ulanishda: oqimlar uni yopib yubormasin
    monkeypatch.setattr(bot, "close_old_connections", lambda: None)


def fake_message(text, uid=11, name="Ali Valiyev", username="ali_v", chat_id=-100900):
    tg_bot = SimpleNamespace(set_message_reaction=AsyncMock(), send_message=AsyncMock(), get_chat_administrators=AsyncMock(return_value=[]))
    m = SimpleNamespace(
        text=text, caption=None, voice=None, video_note=None, audio=None, photo=None, document=None, reply_to_message=None,
        from_user=SimpleNamespace(id=uid, is_bot=False, full_name=name, username=username),
        chat=SimpleNamespace(id=chat_id, title="Guruh", type="supergroup"), message_id=1,
        date=datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc), bot=tg_bot,
        reply=AsyncMock(), answer=AsyncMock())
    return m


def test_task_message_gets_reaction_and_is_saved():
    m = fake_message("#task #Portal Login sahifasi @sardor_t")
    asyncio.run(bot._handle(m))
    reaction = m.bot.set_message_reaction.call_args.args[2][0]
    assert reaction.emoji == "✍"
    assert Task.objects.get().title == "Login sahifasi"


def test_missing_project_asks_which_project():
    m = fake_message("#task Login sahifasi")
    asyncio.run(bot._handle(m))
    assert m.bot.set_message_reaction.call_args.args[2][0].emoji == "🤔"
    assert "Qaysi loyiha" in m.reply.call_args.args[0]


def test_bot_commands_use_database_off_the_event_loop():
    asyncio.run(bot._handle(fake_message("#task #Portal Login sahifasi")))
    m = fake_message("/loyihalar")
    asyncio.run(bot.projects(m))
    assert "Portal" in m.answer.call_args.args[0]
    m = fake_message("/hisobot")
    asyncio.run(bot.report(m))
    assert "Kun yakuni" in m.answer.call_args.args[0]


def test_start_link_connects_person():
    person = Person.objects.create(name="Ali Valiyev", username="ali_v", telegram_id=11, invite_token="tok123")
    assert bot._link_person("tok123", 555) == "Ali Valiyev"
    person.refresh_from_db()
    assert person.dm_chat_id == 555 and person.dm_linked_at
    assert bot._link_person("yoq", 1) is None
