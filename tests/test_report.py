"""Guruhga kun yakuni: bugun bajarilganlar Excel'da, faqat shu guruhniki, muddatidami belgisi bilan."""
import io
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

from ingest.services import Incoming, ingest
from people.models import Person
from projects.models import Task
from reports import services as report

CHAT, OTHER = -100321, -100654


@pytest.fixture(autouse=True)
def people():
    Person.objects.create(telegram_id=2, name="Ulug'bek Nazarov", username="demo_ulugbek")


def say(chat, mid, text, when, reply=None, uid=1, name="Javohir Jumaboyev"):
    ingest(Incoming(chat, "G", mid, uid, name, "javohir_fs", when, text, reply), use_ai=False)


def test_excel_has_only_today_done_tasks_of_this_chat():
    say(CHAT, 1, "#task #Portal Login sahifasi @demo_ulugbek 20-oktyabrgacha", datetime(2026, 10, 15, 9, 0))
    say(CHAT, 2, "#task #Portal Bosh sahifa @demo_ulugbek", datetime(2026, 10, 20, 9, 0))
    say(CHAT, 3, "#task #Portal Hisobot", datetime(2026, 10, 20, 9, 0))
    say(OTHER, 1, "#task #Arxiv Skaner", datetime(2026, 10, 20, 9, 0))
    say(CHAT, 4, "#done", datetime(2026, 10, 21, 10, 5), reply=1, uid=2, name="Ulug'bek Nazarov")
    say(CHAT, 5, "#done", datetime(2026, 10, 21, 16, 40), reply=2, uid=2, name="Ulug'bek Nazarov")
    say(OTHER, 2, "#done", datetime(2026, 10, 21, 11, 0), reply=1)
    data, name, caption = report.build(CHAT, date(2026, 10, 21))
    ws = load_workbook(io.BytesIO(data)).active
    rows = list(ws.iter_rows(min_row=4, values_only=True))
    assert [(r[1], r[3], r[6], r[9]) for r in rows] == [("Login sahifasi", "Ulug'bek Nazarov", "10:05", "yo'q"),
                                                        ("Bosh sahifa", "Ulug'bek Nazarov", "16:40", None)]
    assert len(load_workbook(io.BytesIO(data)).sheetnames) == 1
    assert name == "Bajarilgan_vazifalar_21.10.2026.xlsx"
    assert "2 ta vazifa bajarildi" in caption and "Ulug'bek (2)" in caption and "Ochiq qoldi: 1" in caption


def test_nothing_done_gives_none():
    say(CHAT, 1, "#task #Portal Login sahifasi", datetime(2026, 10, 20, 9, 0))
    assert report.build(CHAT, date(2026, 10, 21)) is None
    assert report.chats() == [CHAT]


def test_telegram_decoration_removed_and_rename_follows_everywhere():
    say(CHAT, 1, "#task #Portal Login sahifasi", datetime(2026, 10, 21, 9, 0), uid=7, name="Javohir ⚜️")
    assert Task.objects.get().assignee.name == "Javohir"
    Person.objects.filter(telegram_id=7).update(name="Javohir Jumaboyev", name_locked=True)
    say(CHAT, 2, "#done", datetime(2026, 10, 21, 15, 0), reply=1, uid=7, name="Javohir ⚜️")
    assert Person.objects.get(telegram_id=7).name == "Javohir Jumaboyev"
    t = Task.objects.get()
    assert (t.assignee.name, t.status) == ("Javohir Jumaboyev", "done")
    _, _, caption = report.build(CHAT, date(2026, 10, 21))
    assert "Javohir (1)" in caption


def test_formula_in_title_is_neutralised():
    say(CHAT, 1, '#task #Portal =HYPERLINK("http://x","click")', datetime(2026, 10, 21, 9, 0))
    say(CHAT, 2, "#done", datetime(2026, 10, 21, 10, 0), reply=1)
    data, _, _ = report.build(CHAT, date(2026, 10, 21))
    cell = load_workbook(io.BytesIO(data)).active.cell(4, 2)
    assert cell.data_type != "f" and cell.value.startswith("'=")
