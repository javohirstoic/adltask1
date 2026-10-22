"""Modellar CRUD'i: /api/data/<resurs> — ro'yxat, qidiruv, filtr, yaratish, o'zgartirish, o'chirish, validatsiya."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from actions.models import Alert, Decision
from core import conf
from core.models import DataVersion
from ingest.models import Correction
from ingest.services import Incoming, ingest
from people.models import Person
from projects.models import Blocker, Chat, Message, Project, Task

CHAT = -100500


@pytest.fixture()
def client():
    get_user_model().objects.create_superuser("rahbar", password="parol-12345")
    c = APIClient()
    c.login(username="rahbar", password="parol-12345")
    return c


@pytest.fixture()
def data():
    now = conf.now()
    ingest(Incoming(CHAT, "Guruh", 1, 1, "Ali Valiyev", "ali_v", now - timedelta(days=1),
                    "#task #Portal\n- Login\n- Bosh sahifa @sardor_t"), use_ai=False)
    ingest(Incoming(CHAT, "Guruh", 2, 1, "Ali Valiyev", "ali_v", now, "#muammo #Portal Server ishlamayapti"), use_ai=False)


def test_all_endpoints_require_login():
    c = APIClient()
    for res in ("departments", "people", "chats", "projects", "tasks", "blockers", "messages", "decisions", "alerts", "corrections"):
        assert c.get("/api/data/" + res).status_code == 401, res
        assert c.post("/api/data/" + res, {}, format="json").status_code == 401, res


def test_list_is_paginated_searchable_and_filterable(client, data):
    r = client.get("/api/data/tasks").json()
    assert r["count"] == 2 and {t["title"] for t in r["results"]} == {"Login", "Bosh sahifa"}
    assert r["results"][0]["project_name"] == "Portal"
    assert client.get("/api/data/tasks?search=bosh").json()["count"] == 1
    sardor = Person.objects.get(username="sardor_t")
    assert client.get("/api/data/tasks?assignee=%d" % sardor.id).json()["count"] == 1
    assert client.get("/api/data/tasks?status=done").json()["count"] == 0
    assert len(client.get("/api/data/tasks?page_size=1").json()["results"]) == 1
    assert client.get("/api/data/tasks?ordering=title").json()["results"][0]["title"] == "Bosh sahifa"
    assert client.get("/api/data/tasks?project=abc").status_code == 400  # noto'g'ri filtr 500 emas


def test_project_crud(client, data):
    chat = Chat.objects.get()
    r = client.post("/api/data/projects", {"name": "Yangi Portal 2", "chat": chat.id, "deadline": "2026-12-01"}, format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["key"] == "yangiportal2" and body["chat_title"] == "Guruh" and body["created_at"]  # teg nomdan olinadi
    pid = body["id"]
    assert client.post("/api/data/projects", {"name": "Boshqa", "key": "Yangi-Portal 2"}, format="json").status_code == 400  # teg band
    assert client.post("/api/data/projects", {"name": "!!!"}, format="json").status_code == 400
    r = client.patch("/api/data/projects/%d" % pid, {"name": "Portal v2", "aliases": "portal ikki"}, format="json")
    assert r.status_code == 200 and r.json()["key"] == "yangiportal2"  # tahrirda teg o'zgarmaydi
    assert client.get("/api/data/projects").json()["results"][0]["open_tasks"] in (0, 2)
    assert client.delete("/api/data/projects/%d" % pid).status_code == 204
    assert not Project.objects.filter(id=pid).exists()


def test_deleting_project_removes_its_tasks_and_blockers(client, data):
    pid = Project.objects.get().id
    assert Task.objects.count() == 2 and Blocker.objects.count() == 1
    assert client.delete("/api/data/projects/%d" % pid).status_code == 204
    assert Task.objects.count() == 0 and Blocker.objects.count() == 0
    assert Message.objects.count() == 2  # xabarlar tarixi qoladi


def test_task_crud_and_status_timestamps(client, data):
    pid = Project.objects.get().id
    ali = Person.objects.get(username="ali_v")
    r = client.post("/api/data/tasks", {"project": pid, "title": "Hisobot", "assignee": ali.id, "deadline": "2026-11-01"}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "open" and r.json()["done_at"] is None and r.json()["assignee_name"] == "Ali Valiyev"
    tid = r.json()["id"]
    r = client.patch("/api/data/tasks/%d" % tid, {"status": "done"}, format="json")
    assert r.json()["done_at"]  # bajarilganda vaqt qo'yiladi
    r = client.patch("/api/data/tasks/%d" % tid, {"status": "open"}, format="json")
    assert r.json()["done_at"] is None  # qayta ochilsa o'chadi
    assert client.patch("/api/data/tasks/%d" % tid, {"status": "xato"}, format="json").status_code == 400
    assert client.post("/api/data/tasks", {"project": 9999, "title": "x"}, format="json").status_code == 400
    assert client.post("/api/data/tasks", {"project": pid}, format="json").status_code == 400
    assert client.delete("/api/data/tasks/%d" % tid).status_code == 204
    assert client.get("/api/data/tasks/%d" % tid).status_code == 404


def test_blocker_crud_and_resolve(client, data):
    pid = Project.objects.get().id
    b = client.get("/api/data/blockers").json()["results"][0]
    assert b["resolved"] is False and b["text"] == "Server ishlamayapti"
    assert client.get("/api/data/blockers?resolved=1").json()["count"] == 0
    r = client.patch("/api/data/blockers/%d" % b["id"], {"resolved": True}, format="json").json()
    assert r["resolved"] is True and r["resolved_at"]
    assert client.get("/api/data/blockers?resolved=1").json()["count"] == 1
    assert client.patch("/api/data/blockers/%d" % b["id"], {"resolved": False}, format="json").json()["resolved_at"] is None
    r = client.post("/api/data/blockers", {"project": pid, "text": "Ruxsat yo'q"}, format="json")
    assert r.status_code == 201 and r.json()["resolved"] is False
    assert client.delete("/api/data/blockers/%d" % r.json()["id"]).status_code == 204


def test_person_and_department_crud(client, data):
    dep = client.post("/api/data/departments", {"name": "  Mobil   ilova "}, format="json")
    assert dep.status_code == 201 and dep.json()["name"] == "Mobil ilova"
    assert client.post("/api/data/departments", {"name": "Mobil ilova"}, format="json").status_code == 400
    did = dep.json()["id"]
    r = client.post("/api/data/people", {"name": "Dilshod Karimov", "username": "@dilshod_k", "department": did, "role": "rahbar"}, format="json")
    assert r.status_code == 201, r.content
    p = r.json()
    assert p["username"] == "dilshod_k" and p["department_name"] == "Mobil ilova" and p["role"] == "rahbar" and p["dm_linked"] is False
    assert Person.objects.get(id=p["id"]).name_locked  # qo'lda yozilgan ism Telegram nomidan ustun
    assert client.post("/api/data/people", {"name": "Dilshod Karimov"}, format="json").status_code == 400  # ism unikal
    assert client.post("/api/data/people", {"name": "X"}, format="json").status_code == 400
    assert client.post("/api/data/people", {"name": "Boshqa", "role": "xato"}, format="json").status_code == 400
    r = client.patch("/api/data/people/%d" % p["id"], {"role": "", "name": "Dilshod K."}, format="json")
    assert r.json()["role"] is None and r.json()["name"] == "Dilshod K."
    assert client.get("/api/data/people?department=%d" % did).json()["count"] == 1
    assert client.get("/api/data/departments").json()["results"][-1]["people_count"] in (0, 1)
    assert client.delete("/api/data/departments/%d" % did).status_code == 204
    assert Person.objects.get(id=p["id"]).department is None  # xodim o'chmaydi, bo'limsiz qoladi


def test_deleting_person_keeps_tasks_unassigned(client, data):
    sardor = Person.objects.get(username="sardor_t")
    assert client.delete("/api/data/people/%d" % sardor.id).status_code == 204
    assert Task.objects.filter(assignee__isnull=True).count() == 1


def test_chat_crud(client, data):
    r = client.post("/api/data/chats", {"id": -100777, "title": "Yangi guruh"}, format="json")
    assert r.status_code == 201 and r.json()["added_at"] and r.json()["demo"] is False
    assert client.post("/api/data/chats", {"id": -100777, "title": "Takror"}, format="json").status_code == 400
    r = client.patch("/api/data/chats/-100777", {"title": "Nomi o'zgardi", "id": -1}, format="json")
    assert r.status_code == 200 and r.json()["id"] == -100777 and r.json()["title"] == "Nomi o'zgardi"
    listed = {c["id"]: c for c in client.get("/api/data/chats").json()["results"]}
    assert listed[CHAT]["messages_count"] == 2 and listed[CHAT]["projects_count"] == 1
    assert client.delete("/api/data/chats/-100777").status_code == 204


def test_messages_are_read_and_delete_only(client, data):
    r = client.get("/api/data/messages?kind=blocker").json()
    assert r["count"] == 1 and r["results"][0]["user_name"] == "Ali Valiyev" and r["results"][0]["project_name"] == "Portal"
    mid = r["results"][0]["id"]
    assert client.patch("/api/data/messages/%d" % mid, {"text": "x"}, format="json").status_code == 405
    assert client.post("/api/data/messages", {}, format="json").status_code == 405
    assert client.delete("/api/data/messages/%d" % mid).status_code == 204
    assert Message.objects.count() == 1


def test_system_logs_are_read_only(client, data):
    d = Decision.objects.create(created_at=conf.now(), type="deadline", title="Muddat surildi", payload={"a": 1})
    a = Alert.objects.create(kind="yuklama", created_at=conf.now(), text="Ishi ko'p")
    assert client.get("/api/data/decisions").json()["results"][0]["title"] == "Muddat surildi"
    assert client.get("/api/data/alerts").json()["results"][0]["text"] == "Ishi ko'p"
    for url in ("/api/data/decisions/%d" % d.id, "/api/data/alerts/%d" % a.id):
        assert client.delete(url).status_code == 405
        assert client.patch(url, {"title": "x"}, format="json").status_code == 405


def test_corrections_listed_and_deletable(client, data):
    m = Message.objects.filter(kind="blocker").get()
    c = Correction.objects.create(message=m, text=m.text, old_kind="blocker", new_kind="none", created_at=conf.now())
    assert client.get("/api/data/corrections?new_kind=none").json()["count"] == 1
    assert client.delete("/api/data/corrections/%d" % c.id).status_code == 204


def test_every_change_bumps_panel_version(client, data):
    v = DataVersion.current()
    client.post("/api/data/departments", {"name": "Yangi"}, format="json")
    assert DataVersion.current() > v
    v = DataVersion.current()
    client.get("/api/data/departments")
    assert DataVersion.current() == v  # o'qish versiyani oshirmaydi
