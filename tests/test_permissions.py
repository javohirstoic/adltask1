"""Rollar: admin hamma narsa, rahbar to'liq dashboard, menejer faqat o'z loyihalari va vazifalari."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core import conf
from ingest.services import Incoming, ingest
from people.models import Department, Person
from projects.models import Blocker, Project, Task

CHAT = -100800


@pytest.fixture()
def world():
    """Ikki loyiha: Portal (Ali, Sardor) va Arxiv (Vali). Hamma vazifa bor, bittasi bajarilgan, bittasi muddati o'tgan."""
    now = conf.now()
    say = lambda mid, uid, name, un, text, when: ingest(Incoming(CHAT, "Guruh", mid, uid, name, un, when, text), use_ai=False)
    say(1, 1, "Ali Valiyev", "ali_v", "#task #Portal\n- Login @ali_v\n- Bosh sahifa @sardor_t muddat: 01.01.2026", now - timedelta(days=3))
    say(2, 2, "Sardor Tursunov", "sardor_t", "#task #Portal Eski ish @sardor_t muddat: 01.01.2026", now - timedelta(days=3))
    say(3, 1, "Ali Valiyev", "ali_v", "#done #Portal Login", now - timedelta(days=1))
    say(4, 3, "Vali Karimov", "vali_k", "#task #Arxiv Skaner @vali_k", now - timedelta(days=2))
    say(5, 3, "Vali Karimov", "vali_k", "#muammo #Arxiv Drayver ishlamayapti", now - timedelta(days=1))
    say(6, 1, "Ali Valiyev", "ali_v", "#muammo #Portal Server yo'q", now)
    return {"portal": Project.objects.get(key="portal"), "arxiv": Project.objects.get(key="arxiv")}


@pytest.fixture()
def admin(make_client):
    return make_client("admin", "Admin Odam")[0]


@pytest.fixture()
def boss(make_client):
    return make_client("rahbar", "Rahbar Odam")[0]


@pytest.fixture()
def manager(make_client, world):
    return make_client("menejer", "Menejer Portal", projects=[world["portal"]])[0]


def ids(resp):
    return {r["id"] for r in resp.json()["results"]}


# ---------- kirish ----------
def test_user_without_role_cannot_log_in_or_use_api():
    get_user_model().objects.create_user("rolsiz", password="Parol-12345!")
    c = APIClient()
    r = c.post("/api/login", {"username": "rolsiz", "password": "Parol-12345!"}, format="json")
    assert r.status_code == 403 and "rol" in r.json()["detail"]
    c.login(username="rolsiz", password="Parol-12345!")  # sessiya bo'lsa ham API yopiq
    assert c.get("/api/meta").status_code == 403
    assert c.get("/api/summary").status_code == 403
    assert c.get("/api/data/tasks").status_code == 403
    assert c.get("/").status_code == 403


def test_person_with_role_but_no_account_has_no_access(make_client):
    person = Person.objects.create(name="Akkauntsiz", role="rahbar")
    assert person.user is None  # Telegramda rahbar, panelga kira olmaydi


def test_superuser_is_admin_without_person():
    get_user_model().objects.create_superuser("root", password="Parol-12345!")
    c = APIClient()
    assert c.post("/api/login", {"username": "root", "password": "Parol-12345!"}, format="json").status_code == 200
    me = c.get("/api/meta").json()["me"]
    assert me["role"] == "admin" and me["access"]["people"] == "crud"


def test_meta_tells_frontend_role_and_access(admin, boss, manager):
    assert admin.get("/api/meta").json()["me"]["role"] == "admin"
    me = boss.get("/api/meta").json()["me"]
    assert me["role"] == "rahbar" and me["access"]["people"] == "r" and me["access"]["projects"] == "crud"
    me = manager.get("/api/meta").json()["me"]
    assert me["role"] == "menejer" and me["access"]["tasks"] == "crud" and "decisions" not in me["access"]


# ---------- menejer: faqat o'z loyihasi ----------
def test_manager_sees_only_own_project_in_dashboard(manager, world):
    body = manager.get("/api/summary").json()
    assert [p["name"] for p in body["projects"]] == ["Portal"]
    assert {p["name"] for p in body["people"]} == {"Ali Valiyev", "Sardor Tursunov"}  # Vali (Arxiv) ko'rinmaydi
    assert all(f["project"] == "Portal" for f in body["feed"])
    assert body["decisions"] == [] and body["decision_log"] == []  # qarorlar rahbarniki
    meta = manager.get("/api/meta").json()
    assert [p["name"] for p in meta["projects"]] == ["Portal"]


def test_manager_project_and_person_detail_scoped(manager, world):
    assert manager.get("/api/project/%d" % world["portal"].id).status_code == 200
    assert manager.get("/api/project/%d" % world["arxiv"].id).status_code == 404
    assert manager.get("/api/person", {"name": "Ali Valiyev"}).status_code == 200
    assert manager.get("/api/person", {"name": "Vali Karimov"}).status_code == 404


def test_project_detail_shows_who_did_what_and_how_well(manager, world):
    d = manager.get("/api/project/%d" % world["portal"].id).json()
    progress = {x["name"]: x for x in d["team_progress"]}
    ali, sardor = progress["Ali Valiyev"], progress["Sardor Tursunov"]
    assert (ali["total"], ali["done"], ali["open"], ali["pct"]) == (1, 1, 0, 100)
    assert ali["avg_days"] is not None and [t["title"] for t in ali["tasks"]] == ["Login"]
    assert (sardor["total"], sardor["done"], sardor["overdue"], sardor["pct"]) == (2, 0, 2, 0)  # muddati o'tgan vazifalar ko'rinadi
    assert all(len(x["tasks"]) == x["total"] for x in d["team_progress"])


def test_manager_data_lists_are_scoped(manager, world):
    tasks = manager.get("/api/data/tasks").json()
    assert tasks["count"] == 3 and {t["project_name"] for t in tasks["results"]} == {"Portal"}
    assert manager.get("/api/data/projects").json()["count"] == 1
    assert manager.get("/api/data/blockers").json()["count"] == 1
    assert {m["project_name"] for m in manager.get("/api/data/messages").json()["results"]} == {"Portal"}
    chats = manager.get("/api/data/chats").json()["results"]
    assert len(chats) == 1  # Portal yozilgan guruh
    other_task = Task.objects.get(project=world["arxiv"])
    assert manager.get("/api/data/tasks/%d" % other_task.id).status_code == 404
    assert manager.delete("/api/data/tasks/%d" % other_task.id).status_code == 404
    assert manager.patch("/api/data/tasks/%d" % other_task.id, {"title": "x"}, format="json").status_code == 404
    other_blocker = Blocker.objects.get(project=world["arxiv"])
    assert manager.delete("/api/data/blockers/%d" % other_blocker.id).status_code == 404
    assert Task.objects.filter(id=other_task.id).exists() and Blocker.objects.filter(id=other_blocker.id).exists()


def test_manager_task_crud_inside_own_project_only(manager, world):
    pid, other = world["portal"].id, world["arxiv"].id
    ali = Person.objects.get(username="ali_v")
    r = manager.post("/api/data/tasks", {"project": pid, "title": "Yangi ish", "assignee": ali.id}, format="json")
    assert r.status_code == 201, r.content
    tid = r.json()["id"]
    assert manager.patch("/api/data/tasks/%d" % tid, {"status": "done"}, format="json").json()["done_at"]
    # boshqa loyihaga yozish yoki ko'chirish mumkin emas
    assert manager.post("/api/data/tasks", {"project": other, "title": "Begona"}, format="json").status_code == 400
    assert manager.patch("/api/data/tasks/%d" % tid, {"project": other}, format="json").status_code == 400
    assert Task.objects.get(id=tid).project_id == pid
    assert manager.post("/api/data/blockers", {"project": other, "text": "x"}, format="json").status_code == 400
    assert manager.post("/api/data/blockers", {"project": pid, "text": "Menejer yozdi"}, format="json").status_code == 201
    assert manager.delete("/api/data/tasks/%d" % tid).status_code == 204


def test_manager_cannot_manage_projects_people_or_logs(manager, world):
    pid = world["portal"].id
    assert manager.post("/api/data/projects", {"name": "Yangi"}, format="json").status_code == 403
    assert manager.patch("/api/data/projects/%d" % pid, {"name": "Boshqa"}, format="json").status_code == 403
    assert manager.delete("/api/data/projects/%d" % pid).status_code == 403
    assert manager.post("/api/data/people", {"name": "Yangi Odam"}, format="json").status_code == 403
    assert manager.post("/api/data/departments", {"name": "Yangi"}, format="json").status_code == 403
    assert manager.post("/api/data/chats", {"id": -5, "title": "x"}, format="json").status_code == 403
    for res in ("decisions", "alerts", "corrections"):
        assert manager.get("/api/data/" + res).status_code == 403, res
    assert manager.delete("/api/data/messages/1").status_code == 403


def test_manager_sees_people_names_but_not_other_projects_load(manager):
    people = manager.get("/api/data/people?page_size=100").json()["results"]
    assert {"Vali Karimov", "Ali Valiyev"} <= {p["name"] for p in people}  # vazifa biriktirish uchun
    assert set(people[0]) == {"id", "name", "username", "department", "department_name"}  # yuklama, bot va akkaunt ko'rinmaydi


def test_manager_cannot_use_boss_only_endpoints(manager, world):
    ali = Person.objects.get(username="ali_v")
    t = Task.objects.filter(project=world["portal"], status="open").first()
    action = {"type": "reassign", "from": t.assignee.name, "to": ali.name, "task_ids": [t.id]}
    assert manager.post("/api/actions/preview", {"action": action}, format="json").status_code == 403
    assert manager.post("/api/actions/execute", {"action": action}, format="json").status_code == 403
    assert manager.post("/api/messages/1/correct", {"kind": "none"}, format="json").status_code == 403
    assert manager.get("/api/settings").status_code == 403
    assert manager.put("/api/settings", {"silent_days": 5}, format="json").status_code == 403
    assert manager.post("/api/person/role", {"name": ali.name, "role": "admin"}, format="json").status_code == 403
    assert manager.post("/api/person/department", {"name": ali.name, "department": "AI"}, format="json").status_code == 403
    assert manager.get("/api/links").status_code == 403
    assert manager.post("/api/import", {}, format="multipart").status_code == 403


def test_manager_without_projects_sees_nothing(make_client, world):
    c, _ = make_client("menejer", "Bo'sh Menejer")
    body = c.get("/api/summary").json()
    assert body["projects"] == [] and body["people"] == [] and body["feed"] == []
    assert c.get("/api/data/tasks").json()["count"] == 0
    assert c.get("/api/export.xlsx").status_code == 200


def test_manager_export_contains_only_own_projects(manager):
    import io
    from openpyxl import load_workbook
    r = manager.get("/api/export.xlsx", {"view": "projects"})
    rows = [row[0] for row in load_workbook(io.BytesIO(r.content)).active.iter_rows(min_row=4, values_only=True)]
    assert rows == ["Portal"]


# ---------- rahbar: to'liq dashboard ----------
def test_boss_sees_everything_and_can_act(boss, world):
    body = boss.get("/api/summary").json()
    assert {p["name"] for p in body["projects"]} == {"Portal", "Arxiv"}
    assert {p["name"] for p in body["people"]} >= {"Ali Valiyev", "Vali Karimov"}
    assert boss.get("/api/project/%d" % world["arxiv"].id).status_code == 200
    assert boss.get("/api/data/tasks").json()["count"] == 4
    for res in ("decisions", "alerts", "corrections", "messages", "people", "departments", "chats"):
        assert boss.get("/api/data/" + res).status_code == 200, res
    assert boss.get("/api/settings").status_code == 200
    ali, sardor = Person.objects.get(username="ali_v"), Person.objects.get(username="sardor_t")
    t = Task.objects.filter(assignee=sardor, status="open").first()
    action = {"type": "reassign", "from": sardor.name, "to": ali.name, "task_ids": [t.id]}
    assert boss.post("/api/actions/execute", {"action": action, "send": False}, format="json").status_code == 200


def test_boss_manages_work_but_not_people_or_settings(boss, world):
    assert boss.post("/api/data/projects", {"name": "Rahbar loyihasi"}, format="json").status_code == 201
    assert boss.post("/api/data/tasks", {"project": world["arxiv"].id, "title": "Rahbar vazifasi"}, format="json").status_code == 201
    assert boss.post("/api/data/people", {"name": "Yangi Odam"}, format="json").status_code == 403
    assert boss.post("/api/data/departments", {"name": "Yangi"}, format="json").status_code == 403
    assert boss.put("/api/settings", {"silent_days": 5}, format="json").status_code == 403
    assert boss.post("/api/person/role", {"name": "Ali Valiyev", "role": "admin"}, format="json").status_code == 403
    assert boss.post("/api/import", {}, format="multipart").status_code == 403
    assert boss.delete("/api/data/messages/1").status_code == 403
    assert boss.post("/api/person/name", {"name": "Ali Valiyev", "new_name": "Ali V."}, format="json").status_code == 200


def test_boss_assigns_manager_to_project(boss, make_client, world):
    _, man = make_client("menejer", "Yangi Menejer")
    r = boss.patch("/api/data/projects/%d" % world["arxiv"].id, {"manager": man.id}, format="json")
    assert r.status_code == 200 and r.json()["manager_name"] == "Yangi Menejer"
    sardor = Person.objects.get(username="sardor_t")
    assert boss.patch("/api/data/projects/%d" % world["arxiv"].id, {"manager": sardor.id}, format="json").status_code == 400  # roli menejer emas


# ---------- admin: hamma narsa ----------
def test_admin_has_everything(admin, world):
    for res in ("departments", "people", "chats", "projects", "tasks", "blockers", "messages", "decisions", "alerts", "corrections"):
        assert admin.get("/api/data/" + res).status_code == 200, res
    assert admin.put("/api/settings", {"silent_days": 5}, format="json").status_code == 200
    assert admin.post("/api/person/role", {"name": "Ali Valiyev", "role": "menejer"}, format="json").status_code == 200
    assert Person.objects.get(username="ali_v").role == "menejer"
    assert admin.post("/api/person/role", {"name": "Ali Valiyev", "role": "xato"}, format="json").status_code == 400
    assert admin.get("/api/links").status_code == 200
    assert admin.delete("/api/data/messages/1").status_code in (204, 404)


# ---------- admin: akkaunt va rol berish ----------
def test_admin_creates_account_for_manager_and_manager_can_log_in(admin, world):
    dep = Department.objects.get(name="Backend")
    r = admin.post("/api/data/people", {"name": "Yangi Menejer", "role": "menejer", "department": dep.id,
                                         "login": "yangi.menejer", "password": "Kuchli-Parol-77"}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["account"] == "yangi.menejer" and "password" not in r.json()  # parol hech qachon qaytmaydi
    pid = r.json()["id"]
    assert admin.patch("/api/data/projects/%d" % world["arxiv"].id, {"manager": pid}, format="json").status_code == 200
    c = APIClient()
    assert c.post("/api/login", {"username": "yangi.menejer", "password": "Kuchli-Parol-77"}, format="json").status_code == 200
    assert [p["name"] for p in c.get("/api/summary").json()["projects"]] == ["Arxiv"]


def test_account_validation(admin, make_client):
    base = {"name": "Akkauntli", "role": "rahbar"}
    assert admin.post("/api/data/people", {**base, "login": "a1"}, format="json").status_code == 400  # parol kerak
    assert admin.post("/api/data/people", {**base, "login": "a1", "password": "123"}, format="json").status_code == 400  # zaif parol
    assert admin.post("/api/data/people", {"name": "Rolsiz", "login": "a2", "password": "Kuchli-Parol-77"}, format="json").status_code == 400
    assert admin.post("/api/data/people", {**base, "login": "a1", "password": "Kuchli-Parol-77"}, format="json").status_code == 201
    r = admin.post("/api/data/people", {"name": "Boshqa", "role": "rahbar", "login": "a1", "password": "Kuchli-Parol-77"}, format="json")
    assert r.status_code == 400 and "band" in str(r.json())  # login unikal


def test_admin_changes_role_password_and_deletes_account(admin, make_client):
    c, person = make_client("menejer", "Almashuvchi")
    assert c.get("/api/summary").status_code == 200
    # rol olib tashlansa kirish yopiladi
    assert admin.patch("/api/data/people/%d" % person.id, {"role": ""}, format="json").status_code == 200
    assert c.get("/api/summary").status_code == 403
    assert admin.patch("/api/data/people/%d" % person.id, {"role": "rahbar", "password": "Yangi-Parol-99"}, format="json").status_code == 200
    c2 = APIClient()
    assert c2.post("/api/login", {"username": person.username, "password": "Yangi-Parol-99"}, format="json").status_code == 200
    assert c2.get("/api/data/decisions").status_code == 200  # endi rahbar
    user_id = person.user_id
    assert admin.delete("/api/data/people/%d" % person.id).status_code == 204
    assert not get_user_model().objects.filter(id=user_id).exists()  # yetim akkaunt qolmaydi


def test_cannot_delete_or_edit_superuser_account(admin):
    su = get_user_model().objects.create_superuser("root", password="Parol-12345!")
    person = Person.objects.create(name="Root Odam", role="admin", user=su)
    assert admin.delete("/api/data/people/%d" % person.id).status_code == 400
    r = admin.patch("/api/data/people/%d" % person.id, {"password": "Boshqa-Parol-55"}, format="json")
    assert r.status_code == 400
    assert get_user_model().objects.filter(username="root").exists()


def test_telegram_lead_includes_all_panel_roles(make_client):
    from people.services import is_lead
    for role in ("admin", "rahbar", "menejer"):
        Person.objects.create(name="T " + role, telegram_id=hash(role) % 10**6, role=role)
        assert is_lead(hash(role) % 10**6)
    Person.objects.create(name="Oddiy", telegram_id=424242)
    assert not is_lead(424242)
