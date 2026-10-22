"""Vazifa berilayotgan paytdagi nazorat: ishi ko'p xodim, bo'shroq hamkasb tavsiyasi, taklif rejimi."""
import json
from datetime import timedelta

import pytest

from puls import analytics, config, db, load, settings
from puls.ingest import Incoming, ingest

CHAT = -100777
GIVER = 1
STAFF = {  # id: (ism, username, bo'lim)
    1: ("Javohir Rahbar", "javohir", None),
    2: ("Sardor Tursunov", "sardor", "Backend"),
    3: ("Bekzod Aliyev", "bekzod", "Backend"),
    4: ("Ali Valiyev", "ali_valiyev", "Backend"),       # Telegram username kamida 5 belgi
    5: ("Vali Karimov", "vali_karimov", "Fullstack"),
    6: ("Laylo Karimova", "laylo", "AI"),
}


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 0)
    db.init()
    c = db.connect()
    for uid, (name, username, dept) in STAFF.items():
        c.execute("INSERT INTO people(id, name, username, department) VALUES(?, ?, ?, ?)", (uid, name, username, dept))
    yield c
    c.close()


class Sender:
    def __init__(self, conn):
        self.conn, self.mid = conn, 0

    def __call__(self, uid, text, hours_ago=1, reply=None, lead=True):
        self.mid += 1
        name, username, _ = STAFF[uid]
        when = config.now().replace(tzinfo=None) - timedelta(hours=hours_ago)
        res = ingest(self.conn, Incoming(CHAT, "Test", self.mid, uid, name, username, when, text, reply, lead=lead), use_ai=False)
        return self.mid, res


def team(conn):
    """Sardorda 8 ta ochiq vazifa; Ali va Vali'da 2 tadan; Bekzod o'zinikini yopgan."""
    send = Sender(conn)
    for i in range(8):
        send(GIVER, "#task #Portal Sardor vazifasi %d @sardor" % i, hours_ago=30 - i)
    for uid in (4, 5):
        send(GIVER, "#task #Portal\n- %s ishi A @%s\n- %s ishi B @%s" % (STAFF[uid][1], STAFF[uid][1], STAFF[uid][1], STAFF[uid][1]),
             hours_ago=20)
    send(GIVER, "#task #Portal Bekzod ishi @bekzod", hours_ago=20)
    send(3, "#done #Portal Bekzod ishi", hours_ago=10)
    return send


def test_overloaded_assignee_gets_alert_with_free_colleague(conn):
    send = team(conn)
    mid, res = send(GIVER, "#task #Portal Login API @sardor")
    alerts = load.check(conn, res.task_ids, GIVER, CHAT, mid)
    assert len(alerts) == 1
    a = load.get(conn, alerts[0]["id"])
    assert a["assignee"] == "Sardor Tursunov"
    assert json.loads(a["options"])[0] == "Bekzod Aliyev"          # shu bo'limda eng bo'sh
    assert json.loads(a["options"])[1] == "Ali Valiyev"            # fullstack'dan oldin aynan shu bo'lim
    assert "(Fullstack)" not in alerts[0]["text"]
    assert "Laylo" not in a["options"]                              # boshqa bo'lim tavsiya qilinmaydi
    assert alerts[0]["buttons"][-1][0][0] == "Sardorda qolsin"


def test_normal_load_and_self_assigned_tasks_are_silent(conn):
    send = team(conn)
    mid, res = send(GIVER, "#task #Portal Kichik ish @ali")
    assert load.check(conn, res.task_ids, GIVER, CHAT, mid) == []
    mid, res = send(2, "#task #Portal O'zimga eslatma")              # Sardor o'ziga yozdi
    assert load.check(conn, res.task_ids, 2, CHAT, mid) == []


def test_pick_colleague_moves_task_and_logs_decision(conn):
    send = team(conn)
    mid, res = send(GIVER, "#task #Portal Login API @sardor")
    aid = load.check(conn, res.task_ids, GIVER, CHAT, mid)[0]["id"]
    alert = load.get(conn, aid)
    assert not load.may_decide(conn, alert, 4, "ali", admin=False)   # begona odam hal qila olmaydi
    assert load.may_decide(conn, alert, GIVER, "javohir", admin=False)
    out = load.resolve(conn, aid, "0", "Javohir Rahbar")
    assert "Bekzod" in out["text"] and out["notify"]
    row = conn.execute("SELECT assignee FROM tasks WHERE id = ?", (res.task_ids[0],)).fetchone()
    assert row["assignee"] == "Bekzod Aliyev"
    log = conn.execute("SELECT type, origin FROM decisions").fetchone()
    assert (log["type"], log["origin"]) == ("reassign", "guruh")
    assert "Allaqachon" in load.resolve(conn, aid, "0", "Javohir Rahbar")["answer"]


def test_keep_is_logged_and_not_asked_again_today(conn):
    send = team(conn)
    mid, res = send(GIVER, "#task #Portal Login API @sardor")
    aid = load.check(conn, res.task_ids, GIVER, CHAT, mid)[0]["id"]
    load.resolve(conn, aid, "k", "Javohir Rahbar")
    assert conn.execute("SELECT type FROM decisions").fetchone()["type"] == "keep"
    mid, res = send(GIVER, "#task #Portal Yana bir ish @sardor")
    assert load.check(conn, res.task_ids, GIVER, CHAT, mid) == []


def test_leads_only_policy_waits_for_acceptance(conn):
    settings.save(conn, {"assign_policy": "rahbar"})
    send = Sender(conn)
    mid, res = send(4, "#task #Portal Hisobot shakli @bekzod", lead=False)
    assert res.proposed and not res.task_ids
    people = {p["name"]: p for p in analytics.compute(conn, "week")["people"]}
    assert "Bekzod Aliyev" not in people                              # qabul qilinmaguncha hisobga kirmaydi
    a = load.propose(conn, res.proposed, 4, "Ali Valiyev", CHAT, mid)[0]
    alert = load.get(conn, a["id"])
    assert not load.may_decide(conn, alert, 5, "vali", admin=False)
    assert load.may_decide(conn, alert, 3, "bekzod", admin=False)
    load.resolve(conn, a["id"], "ha", "Bekzod Aliyev")
    assert conn.execute("SELECT status FROM tasks").fetchone()["status"] == "open"
    _, own = send(4, "#task #Portal O'zimning ishim", lead=False)    # o'ziga yozgani darhol ochiladi
    assert own.task_ids and not own.proposed
