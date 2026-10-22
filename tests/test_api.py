"""REST API: kirish, himoya, har endpoint o'z vazifasini bajarishi."""
import io
import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from openpyxl import load_workbook
from rest_framework.test import APIClient

from core import conf
from ingest.services import Incoming, ingest
from people.models import Person
from projects.models import Message, Project, Task

CHAT = -100500


@pytest.fixture()
def client():
    get_user_model().objects.create_superuser("rahbar", password="parol-12345")
    c = APIClient()
    assert c.login(username="rahbar", password="parol-12345")
    return c


@pytest.fixture()
def data():
    """Bir loyiha, ikki xodim, bir ochiq va bir bajarilgan vazifa."""
    now = conf.now()
    Person.objects.create(telegram_id=2, name="Sardor Tursunov", username="sardor_t")
    ingest(Incoming(CHAT, "Guruh", 1, 1, "Ali Valiyev", "ali_v", now - timedelta(days=2), "#task #Portal\n- Login\n- Bosh sahifa @sardor_t"), use_ai=False)
    ingest(Incoming(CHAT, "Guruh", 2, 1, "Ali Valiyev", "ali_v", now - timedelta(days=1), "#done #Portal Login"), use_ai=False)


def test_api_requires_login():
    c = APIClient()
    for url in ("/api/meta", "/api/summary", "/api/settings", "/api/links", "/api/export.xlsx"):
        assert c.get(url).status_code == 401, url
    assert c.post("/api/actions/execute", {}, format="json").status_code == 401
    assert c.get("/").status_code == 302  # panel sahifasi /login ga yo'naltiradi


def test_login_logout_flow():
    get_user_model().objects.create_superuser("rahbar", password="parol-12345")
    c = APIClient()
    assert c.post("/api/login", {"username": "rahbar", "password": "xato"}, format="json").status_code == 401
    assert c.post("/api/login", {"username": "rahbar", "password": "parol-12345"}, format="json").status_code == 200
    assert c.get("/api/meta").status_code == 200
    assert c.post("/api/logout", {}, format="json").status_code == 200
    assert c.get("/api/meta").status_code == 401


def test_csrf_is_enforced_for_session_users():
    get_user_model().objects.create_superuser("rahbar", password="parol-12345")
    c = APIClient(enforce_csrf_checks=True)
    c.login(username="rahbar", password="parol-12345")
    assert c.put("/api/settings", {"silent_days": 5}, format="json").status_code == 403


def test_summary_project_and_person_endpoints(client, data):
    r = client.get("/api/summary?period=week")
    assert r.status_code == 200
    body = r.json()
    assert body["projects"][0]["name"] == "Portal" and body["kpi"]["created"] == 2 and body["feed"]
    pid = body["projects"][0]["id"]
    assert client.get("/api/project/%d" % pid).json()["project"]["open_total"] == 1
    assert client.get("/api/project/9999").status_code == 404
    assert client.get("/api/person", {"name": "Sardor Tursunov"}).json()["person"]["open"] == 1
    assert client.get("/api/person", {"name": "Yo'q odam"}).status_code == 404
    assert client.get("/api/summary?period=year").status_code == 400
    assert client.get("/api/summary?period=custom&start=x&end=y").status_code == 400
    assert client.get("/api/summary?asof=bad").status_code == 400


def test_meta_version_and_settings(client, data):
    meta = client.get("/api/meta").json()
    assert meta["chats"][0]["title"] == "Guruh" and "Backend" in meta["departments"]
    v = client.get("/api/version").json()["v"]
    assert client.put("/api/settings", {"silent_days": 6}, format="json").json()["values"]["silent_days"] == 6
    assert client.get("/api/version").json()["v"] > v
    assert client.get("/api/settings").json()["values"]["silent_days"] == 6
    assert client.put("/api/settings", {"silent_days": 99}, format="json").status_code == 400
    assert client.put("/api/settings", {"nomalum": 1}, format="json").status_code == 400


def test_person_management(client, data):
    assert client.post("/api/person/department", {"name": "Sardor Tursunov", "department": "Backend"}, format="json").status_code == 200
    assert Person.objects.get(name="Sardor Tursunov").department.name == "Backend"
    assert client.post("/api/person/role", {"name": "Sardor Tursunov", "role": "rahbar"}, format="json").status_code == 200
    assert client.post("/api/person/role", {"name": "Sardor Tursunov", "role": "xato"}, format="json").status_code == 400
    assert client.post("/api/person/name", {"name": "Sardor Tursunov", "new_name": "Sardor T."}, format="json").json()["name"] == "Sardor T."
    assert client.post("/api/person/name", {"name": "Sardor T.", "new_name": "Ali Valiyev"}, format="json").status_code == 409
    assert Task.objects.filter(assignee__name="Sardor T.").count() == 1  # ism hamma joyda birga almashadi
    assert client.post("/api/person/role", {"name": "Yo'q", "role": ""}, format="json").status_code == 404
    link = client.get("/api/person/link", {"name": "Sardor T."}).json()
    assert link["link"].endswith("?start=" + Person.objects.get(name="Sardor T.").invite_token) and not link["linked"]
    new = client.post("/api/person/link/reset", {"name": "Sardor T."}, format="json").json()
    assert new["link"] != link["link"]
    assert len(client.get("/api/links").json()["people"]) == 2


def test_actions_preview_execute_and_log(client, data):
    ali = Person.objects.get(name="Ali Valiyev")
    t = Task.objects.get(title="Bosh sahifa")
    action = {"type": "reassign", "from": "Sardor Tursunov", "to": "Ali Valiyev", "task_ids": [t.id]}
    pv = client.post("/api/actions/preview", {"action": action}, format="json").json()
    assert pv["items"] == ["Bosh sahifa"] and pv["will_send"] is False  # bot tokeni yo'q: Telegramga yuborilmaydi
    r = client.post("/api/actions/execute", {"action": action, "send": False}, format="json")
    assert r.status_code == 200 and Task.objects.get(id=t.id).assignee_id == ali.id
    assert client.post("/api/actions/execute", {"action": action}, format="json").status_code == 400  # allaqachon o'tgan
    assert client.get("/api/summary").json()["decision_log"][0]["title"].startswith("«Bosh sahifa»")
    pid = Project.objects.get().id
    dl = {"type": "deadline", "project_id": pid, "date": "2026-12-01"}
    assert client.post("/api/actions/execute", {"action": dl, "send": False}, format="json").status_code == 200
    assert str(Project.objects.get().deadline) == "2026-12-01"
    assert client.post("/api/actions/preview", {"action": {"type": "nomalum"}}, format="json").status_code == 400


def test_correct_ai_mistake(client, data):
    ingest(Incoming(CHAT, "Guruh", 3, 1, "Ali Valiyev", "ali_v", conf.now(), "Rahmat, ertaga uchrashamiz"), use_ai=False)
    mid = Message.objects.get(msg_id=3).id
    pid = Project.objects.get().id
    r = client.post("/api/messages/%d/correct" % mid, {"kind": "task", "project_id": pid}, format="json")
    assert r.status_code == 200 and r.json()["corrections"] == 1
    assert Message.objects.get(id=mid).kind == "task" and Message.objects.get(id=mid).source == "tuzatildi"
    assert client.post("/api/messages/%d/correct" % mid, {"kind": "task"}, format="json").status_code == 400
    assert client.post("/api/messages/%d/correct" % mid, {"kind": "xato"}, format="json").status_code == 400


def test_export_xlsx_views(client, data):
    for view, title in (("projects", "Loyihalar"), ("people", "Xodimlar"), ("tasks", "Ochiq vazifalar"), ("departments", "Bo'limlar")):
        r = client.get("/api/export.xlsx", {"view": view})
        assert r.status_code == 200 and "spreadsheetml" in r["Content-Type"]
        assert load_workbook(io.BytesIO(r.content)).active.title == title


def test_import_telegram_history(client):
    export = {"name": "Eski guruh", "type": "private_supergroup", "id": 777, "messages": [
        {"id": 1, "type": "message", "date": "2026-10-01T09:00:00", "from": "Ali", "from_id": "user11", "text": "#task #Eski Hisobot"},
        {"id": 2, "type": "message", "date": "2026-10-01T10:00:00", "from": "Ali", "from_id": "user11",
         "text": [{"type": "plain", "text": "#done #Eski "}, "Hisobot"]},
        {"id": 3, "type": "service", "date": "2026-10-01T10:00:00"}]}
    f = io.BytesIO(json.dumps(export).encode())
    f.name = "result.json"
    r = client.post("/api/import", {"file": f}, format="multipart")
    assert r.status_code == 200 and r.json() == {"chat": "Eski guruh", "added": 2, "skipped": 0}
    f.seek(0)
    assert client.post("/api/import", {"file": f}, format="multipart").json()["skipped"] == 2  # qayta yuklansa ikkilanmaydi
    assert Task.objects.get().status == "done"
    bad = io.BytesIO(b"bu json emas")
    bad.name = "x.json"
    assert client.post("/api/import", {"file": bad}, format="multipart").status_code == 400


def test_pages_served_for_logged_in_user(client):
    for url, marker in (("/", b"Puls"), ("/taqdimot", b"<html"), ("/login", b"api/login")):
        r = client.get(url)
        assert r.status_code == 200 and marker in b"".join(r.streaming_content), url
