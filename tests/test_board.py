"""Menejer doskasi: vazifa yaratish, ustunlar, tugmalar va guruhdagi javoblar."""
from datetime import datetime

import pytest

from puls import board, config, db
from puls.ingest import Incoming, ingest

CHAT = -100888


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(board, "now", lambda: datetime(2026, 10, 22, 10, 0))
    db.init()
    c = db.connect()
    c.execute("INSERT INTO people(id, name, username, department) VALUES(2, 'Sardor Tursunov', 'demo_sardor', 'Backend'), "
              "(3, 'Elyor Hasanov', 'demo_elyor', 'DevOps')")
    ingest(c, Incoming(CHAT, "G", 1, 2, "Sardor Tursunov", "demo_sardor", datetime(2026, 10, 20, 9, 0), "#task #Shajara Login sahifasi"),
           use_ai=False)
    yield c
    c.close()


def pid(conn):
    return conn.execute("SELECT id FROM projects").fetchone()["id"]


def test_create_card_appears_in_new_column(conn):
    tid = board.create(conn, "Hisobot shaklini yangilash", pid(conn), "Sardor Tursunov", "2026-10-25", "yuqori", "API bilan")
    b = board.board(conn)
    c = next(x for x in b["cards"] if x["id"] == tid)
    assert c["stage"] == "yangi" and c["priority"] == "yuqori" and c["due_label"] == "25-oktyabr"
    assert b["cards"][0]["id"] == tid  # muhimi tepada
    assert [col["count"] for col in b["columns"]] == [2, 0, 0, 0, 0]


def test_buttons_move_card_and_finish_task(conn):
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov")
    board.act(conn, tid, "ok")
    assert board.stage_of(conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()) == "qabul"
    board.act(conn, tid, "50")
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert (board.stage_of(t), t["progress"]) == ("jarayon", 50)
    board.act(conn, tid, "done")
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert t["status"] == "done" and t["done_at"]  # tahlilda ham bajarilgan


@pytest.mark.parametrize("text,stage,progress,flag", [
    ("tushundim", "qabul", 0, None), ("70% qildim", "jarayon", 70, None), ("yarmini qildim", "jarayon", 50, None),
    ("bajardim", "bajarildi", 100, None), ("API hali tayyor emas, kutib turibmiz", "yangi", 0, "toqiq"),
    ("qaysi jadvalga yozish kerak?", "yangi", 0, "savol")])
def test_free_text_reply_updates_card(conn, text, stage, progress, flag):
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov")
    assert board.reply(conn, tid, text, "Sardor Tursunov")
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert (board.stage_of(t), 100 if t["status"] == "done" else (t["progress"] or 0), t["flag"]) == (stage, progress, flag)


def test_only_assignee_or_lead_may_press(conn):
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov")
    assert board.may_act(conn, tid, 2, "demo_sardor", False)
    assert not board.may_act(conn, tid, 3, "demo_elyor", False)
    conn.execute("UPDATE people SET role = 'rahbar' WHERE id = 3")
    assert board.may_act(conn, tid, 3, "demo_elyor", False)


def test_reassign_resets_acceptance_and_message(conn):
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov")
    conn.execute("UPDATE tasks SET tg_chat = 1, tg_msg = 5 WHERE id = ?", (tid,))
    board.act(conn, tid, "ok")
    board.update(conn, tid, assignee="Elyor Hasanov")
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert (t["assignee"], board.stage_of(t), t["accepted_at"], t["tg_msg"]) == ("Elyor Hasanov", "yangi", None, None)


def test_message_buttons_follow_stage(conn):
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov", "2026-10-25")
    text, rows, chat = board.message(conn, tid)
    assert "@demo_sardor" in text and "25-oktyabr" in text and [b[0] for b in rows[0]] == ["Tushundim", "Savolim bor"]
    board.act(conn, tid, "ok")
    _, rows, _ = board.message(conn, tid)
    assert [b[0] for b in rows[0]] == ["25%", "50%", "75%", "Bajardim"]
    assert chat == CHAT


def test_candidates_put_project_people_and_free_first(conn):
    out = board.candidates(conn, pid(conn))
    assert out[0]["name"] == "Sardor Tursunov" and out[0]["in_project"]


def test_history_keeps_every_step_and_group_reply(conn):
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov", created_by="Javohir Jumaboyev")
    board.act(conn, tid, "ok", "Sardor Tursunov")
    board.reply(conn, tid, "kecha boshlayman", "Sardor Tursunov")  # holat o'zgarmaydi, lekin tarixda turadi
    board.heard(conn, tid, "API manzili qayerda?", "Elyor Hasanov")
    ev = board.detail(conn, tid)["events"]
    assert [e["kind"] for e in ev] == ["telegram", "telegram", "stage", "create"]
    assert ev[-1]["who"] == "Javohir Jumaboyev" and board.board(conn)["cards"][0]["comments"] == 2


def test_checklist_drives_progress_and_message(conn):
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov", checklist=["Jadval", "Grafik", ""])
    items = board.detail(conn, tid)["checklist"]
    assert [i["text"] for i in items] == ["Jadval", "Grafik"]
    board.check_set(conn, items[0]["id"], True)
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert (board.stage_of(t), t["progress"]) == ("jarayon", 50)
    c = next(x for x in board.board(conn)["cards"] if x["id"] == tid)
    assert c["checks"] == [1, 2]
    assert "☑ Jadval" in board.message(conn, tid)[0] and "☐ Grafik" in board.message(conn, tid)[0]
    board.check_del(conn, items[1]["id"])  # qolgan yagona band bajarilgan: ish tekshiruvga o'tadi
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert (board.stage_of(t), t["progress"], t["status"]) == ("tekshiruv", 100, "open")


def test_reply_to_bot_comment_finds_task(conn):
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov")
    conn.execute("UPDATE tasks SET tg_chat = ?, tg_msg = 50 WHERE id = ?", (CHAT, tid))
    board.comment(conn, tid, "Javohir Jumaboyev", "Ertaga 10 gacha bo'lsin")
    conn.execute("UPDATE task_events SET msg = 51 WHERE kind = 'comment'")
    assert board.find_by_message(conn, CHAT, 50) == tid and board.find_by_message(conn, CHAT, 51) == tid
    assert board.find_by_message(conn, CHAT, 52) is None


def test_only_board_tasks_can_be_deleted_and_copy_keeps_list(conn):
    group_task = conn.execute("SELECT id FROM tasks WHERE created_msg IS NOT NULL").fetchone()["id"]
    with pytest.raises(ValueError):
        board.remove(conn, group_task)
    tid = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov", "2026-10-25", checklist=["Jadval"])
    new = board.copy(conn, tid)
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (new,)).fetchone()
    assert (t["title"], t["assignee"], t["deadline"]) == ("Hisobot", None, "2026-10-25")
    assert [i["text"] for i in board.detail(conn, new)["checklist"]] == ["Jadval"]
    board.remove(conn, tid)
    assert conn.execute("SELECT count(*) FROM task_checks WHERE task_id = ?", (tid,)).fetchone()[0] == 0


def test_reminders_once_for_silence_and_daily_for_deadline(conn):
    a = board.create(conn, "Hisobot", pid(conn), "Sardor Tursunov")
    b = board.create(conn, "Grafik", pid(conn), "Elyor Hasanov", "2026-10-23")
    conn.execute("UPDATE tasks SET tg_chat = ?, tg_msg = id + 100, created_at = '2026-10-22 05:00:00' WHERE id = ?", (CHAT, a))
    conn.execute("UPDATE tasks SET tg_chat = ?, tg_msg = id + 100, accepted_at = created_at, stage = 'jarayon' WHERE id = ?", (CHAT, b))
    due = board.reminders(conn)
    assert sorted((tid, kind) for tid, _, _, kind, _ in due) == [(a, "javob"), (b, "muddat")]
    assert "@demo_sardor" in next(text for tid, _, _, _, text in due if tid == a)
    for tid, _, msg, kind, _ in due:
        board.reminded(conn, tid, kind, 900 + tid)
    assert board.reminders(conn) == []
    assert board.find_by_message(conn, CHAT, 900 + a) == a  # eslatmaga javob ham shu vazifaga


def test_one_task_for_several_people_keeps_own_progress(conn):
    ids = board.create_many(conn, "Hisobot moduli", pid(conn), ["Sardor Tursunov", "Elyor Hasanov"], "2026-10-25", checklist=["Jadval"])
    assert len(ids) == 2
    board.act(conn, ids[0], "done")
    cards = {c["id"]: c for c in board.board(conn)["cards"]}
    assert cards[ids[0]]["stage"] == "bajarildi" and cards[ids[1]]["stage"] == "yangi"
    assert (cards[ids[1]]["grp_size"], cards[ids[1]]["grp_done"]) == (2, 1)
    d = board.detail(conn, ids[1])
    assert [s["assignee"] for s in d["siblings"]] == ["Sardor Tursunov"] and d["checklist"][0]["text"] == "Jadval"
