"""Vazifaning o'z muddati va AI kontekst bilan ishlashi (AI soxtalashtirilgan)."""
import zlib
from datetime import date, datetime, timedelta

import pytest

from analytics import services as analytics
from ingest import ai, memory
from ingest.parser import Item, Parsed, parse_format, parse_free
from ingest.services import Incoming, context, ingest
from people.models import Person
from projects.models import Project, Task

CHAT = -100777
T0 = datetime(2026, 10, 21, 11, 20)
SYNONYMS = {"prezentatsiya": "taqdimot", "slayd": "taqdimot"}


def fake_embed(texts, task_type):
    """Har so'z (sinonimi bilan) bitta o'lcham: so'zlari boshqa, ma'nosi bir gaplar yaqin chiqadi."""
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in t.lower().replace(",", " ").split():
            w = next((s for k, s in SYNONYMS.items() if w.startswith(k)), w[:5])
            v[zlib.crc32(w.encode()) % 64] += 1  # hash() har ishga tushishda boshqa: test barqaror bo'lsin
        out.append(v)
    return out


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(memory, "_embed", fake_embed)  # testda tarmoq yo'q: ma'noni so'zlar bilan taqlid qilamiz
    Person.objects.create(telegram_id=2, name="Ulug'bek Nazarov", username="demo_ulugbek")
    Person.objects.create(telegram_id=3, name="Sardor Tursunov", username="demo_sardor")


def msg(mid, text, when=T0, reply=None, use_ai=False):
    return ingest(Incoming(CHAT, "Test", mid, 1, "Javohir", "javohir_fs", when, text, reply), use_ai=use_ai)


def test_task_line_with_date_gets_own_deadline():
    p = parse_format("#task #Sinov Taqdimot slaydlari @demo_ulugbek 25-oktyabrgacha", date(2026, 10, 21))
    assert [(i.title, i.assignee, i.deadline) for i in p.items] == [("Taqdimot slaydlari", "@demo_ulugbek", date(2026, 10, 25))]


def test_free_text_deadline_without_title():
    p = parse_free("25-oktyabrgacha bajarilsin", [], date(2026, 10, 21))
    assert p.kind == "deadline" and p.deadline == date(2026, 10, 25)


def test_reply_deadline_goes_to_task_not_project():
    msg(1, "#task #Sinov Taqdimot slaydlarini tayyorlash @demo_ulugbek")
    r = msg(2, "25-oktyabrgacha bajarilsin", T0 + timedelta(minutes=1), reply=1)
    assert r.kind == "deadline" and r.changed == 1
    assert Task.objects.get().deadline == date(2026, 10, 25)
    assert Project.objects.get().deadline is None


def test_context_lists_team_tasks_and_reply():
    msg(1, "#task #Sinov Taqdimot slaydlari @demo_ulugbek")
    ctx = context(Incoming(CHAT, "Test", 2, 1, "Javohir", "javohir_fs", T0, "juma kuni tayyor bo'lsin", reply_to=1))
    tid = Task.objects.get().id
    assert ctx["reply"]["task_ids"] == [tid]
    assert [t["id"] for t in ctx["tasks"]] == [tid]
    assert ("Ulug'bek Nazarov", "demo_ulugbek") in ctx["team"]
    text = ai.context_text(ctx)
    assert "Taqdimot slaydlari" in text and "@demo_ulugbek" in text


def fake_ai(monkeypatch, parsed):
    seen = {}

    def extract(text, author, projects, today, retries=1, context=None):
        seen["context"] = context
        return parsed(context)
    monkeypatch.setattr(ai, "extract", extract)
    return seen


def test_ai_deadline_without_reply_by_name(monkeypatch):
    msg(1, "#task #Sinov Taqdimot slaydlari @demo_ulugbek")
    tid = Task.objects.get().id
    seen = fake_ai(monkeypatch, lambda ctx: Parsed("deadline", None, [], date(2026, 10, 24), "ai", [tid]))
    r = msg(2, "Ulug'bek, slaydlar juma kuni tayyor bo'lsin", use_ai=True)
    assert seen["context"]["tasks"][0]["id"] == tid
    assert r.changed == 1 and Task.objects.get().deadline == date(2026, 10, 24)


def test_ai_reassign_and_done_by_reference(monkeypatch):
    msg(1, "#task #Sinov Taqdimot slaydlari @demo_ulugbek")
    tid = Task.objects.get().id
    fake_ai(monkeypatch, lambda ctx: Parsed("reassign", None, [Item("Taqdimot slaydlari", "@demo_sardor")], None, "ai", [tid]))
    msg(2, "buni Sardor qilsin", use_ai=True)
    assert Task.objects.get().assignee.name == "Sardor Tursunov"
    fake_ai(monkeypatch, lambda ctx: Parsed("done", None, [Item("Slaydlar")], None, "ai", [tid]))
    r = msg(3, "slaydlar bitdi", T0 + timedelta(hours=1), use_ai=True)
    assert r.closed == 1 and Task.objects.get().status == "done"
    assert Task.objects.count() == 1  # yangi "bajarilgan" vazifa to'qilmadi


def test_memory_finds_year_old_task_from_other_chat_by_meaning():
    old = datetime(2025, 10, 1, 10, 0)
    ingest(Incoming(-100999, "Boshqa guruh", 1, 1, "Javohir", "javohir_fs", old,
                    "#task #Portal Taqdimot slaydlari @demo_ulugbek"), use_ai=False)
    for i in range(80):  # shu guruhda ko'p yangi vazifa: eski vazifa "oxirgi 60 ta" ga sig'masdi
        msg(10 + i, "#task #Sinov Mayda ish %d @demo_sardor" % i)
    inc = Incoming(CHAT, "Test", 200, 1, "Javohir", "javohir_fs", T0, "prezentatsiya fayllari juma kuni kerak")
    titles = [t["title"] for t in context(inc)["tasks"]]
    assert titles[0] == "Taqdimot slaydlari" and len(titles) <= 70


def test_voice_message_is_transcribed_then_understood(monkeypatch):
    monkeypatch.setattr(ai, "transcribe", lambda data, mime, caption="": "Ulug'bek, hisobotni ertaga topshir")
    seen = fake_ai(monkeypatch, lambda ctx: Parsed("task", "sinov", [Item("Hisobot", "@demo_ulugbek", date(2026, 10, 22))], None, "ai"))
    msg(1, "#task #Sinov Boshlang'ich ish")  # loyiha paydo bo'lsin
    r = ingest(Incoming(CHAT, "Test", 2, 1, "Javohir", "javohir_fs", T0, "", media=b"OggS...", mime="audio/ogg"), use_ai=True)
    assert r.kind == "task" and seen["context"] is not None
    from projects.models import Message
    assert Message.objects.get(msg_id=2).text == "Ovozli xabar: Ulug'bek, hisobotni ertaga topshir"
    t = Task.objects.get(title="Hisobot")
    assert (t.assignee.name, t.deadline) == ("Ulug'bek Nazarov", date(2026, 10, 22))


def test_ai_cannot_point_to_unknown_task():
    p = ai._normalize({"kind": "done", "refs": [999], "items": [{"title": "X"}]}, [], valid_refs={1, 2})
    assert p.refs == []
    p = ai._normalize({"kind": "reassign", "refs": [1], "items": [{"title": "X", "assignee": None}]}, [], valid_refs={1})
    assert p.kind == "none"


def test_overdue_task_shows_in_person_view():
    msg(1, "#task #Sinov Taqdimot slaydlari @demo_ulugbek 22-oktyabrgacha")
    data = analytics.compute("week", now=datetime(2026, 10, 24, 10, 0))
    p = next(x for x in data["people"] if x["name"] == "Ulug'bek Nazarov")
    t = p["open_tasks"][0]
    assert (t["due_in"], t["due_label"]) == (-2, "22-oktyabr")
    assert p["overdue"] == 1 and p["state"] == "stuck" and "muddati o'tgan" in p["fact"]
