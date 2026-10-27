"""Murojaatlar: yordam guruhi va chatbot oqimi, tasniflash, javob bahosi, takroriy murojaat, tahlil va ish tahlilidan ajratish."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from puls import ai, analytics, appeals, config, db, sqlro
from puls.ingest import Incoming, ingest

SUP = -100777          # "Yagona platforma | Yordam"
WORK = -100555         # "Shajara - Ishlar"
OWNER = (1, "Javohir")
ELON, MARK = (501, "Elon Musk"), (502, "Mark Zuckerberg")
T0 = datetime(2026, 10, 26, 10, 0)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 1)
    db.init()
    c = db.connect()
    yield c
    c.close()


def say(conn, who, mid, text, when, chat=SUP, title="Yagona platforma | Yordam", reply=None, admin=False):
    inc = Incoming(chat, title, mid, who[0], who[1], None, when, text, reply)
    inc.admin = admin
    return ingest(conn, inc, use_ai=True)


def one(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()


def test_support_group_flow_without_ai(conn):
    r = say(conn, ELON, 1, "OneID orqali kira olmayapman, xatolik chiqyapti", T0)
    assert r.skipped and not r.duplicate  # bot yordam guruhida jim
    assert one(conn, "SELECT kind FROM chats WHERE id = ?", (SUP,))["kind"] == "yordam"
    assert one(conn, "SELECT count(*) FROM people")[0] == 0  # foydalanuvchi xodimlar ro'yxatiga tushmaydi
    a = one(conn, "SELECT * FROM appeals")
    assert (a["type"], a["status"], a["source"]) == ("login", "ochiq", "tg")
    p = one(conn, "SELECT name, chat_id, yordam FROM projects WHERE id = ?", (a["project_id"],))
    assert (p["name"], p["chat_id"], p["yordam"]) == ("Yagona platforma", None, 1)
    say(conn, ELON, 2, "skrinshot ham yubordim", T0 + timedelta(minutes=5))  # 30 daqiqa ichida, javobsiz: qo'shimcha
    assert one(conn, "SELECT count(*) FROM appeals")[0] == 1
    assert one(conn, "SELECT count(*) FROM appeal_events WHERE kind = 'qoshimcha'")[0] == 1
    say(conn, OWNER, 3, "Keyinroq qayta urinib ko'ring", T0 + timedelta(minutes=40), reply=1)
    a = one(conn, "SELECT * FROM appeals")
    assert (a["status"], a["grade"], a["first_grade"], a["line"]) == ("javob", "tpl", "tpl", 2)
    say(conn, OWNER, 4, "OneID integratsiyasidagi xato tuzatildi, qayta kiring", T0 + timedelta(hours=2), reply=1)
    a = one(conn, "SELECT * FROM appeals")
    assert (a["status"], a["grade"], a["first_grade"], a["resolution"]) == ("hal", "good", "tpl", "javob")
    assert a["resolved_at"] == "2026-10-26 12:00:00"
    say(conn, ELON, 5, "ishladi, rahmat", T0 + timedelta(hours=3))
    assert one(conn, "SELECT count(*) FROM appeal_events WHERE kind = 'tasdiq'")[0] == 1
    assert one(conn, "SELECT count(*) FROM appeals")[0] == 1


def test_repeat_and_reopen(conn):
    say(conn, MARK, 1, "To'lov qildim, ariza to'lanmagan deb turibdi", T0)
    say(conn, OWNER, 2, "To'lov 24 soat ichida aks etadi, kuting", T0 + timedelta(hours=1), reply=1)
    say(conn, MARK, 3, "hali ham o'zgarmadi", T0 + timedelta(hours=30))
    a = one(conn, "SELECT status, resolved_at FROM appeals")
    assert a["status"] == "qayta" and a["resolved_at"] is None
    say(conn, MARK, 4, "Click orqali to'lov o'tdi, tizimda ko'rinmayapti", T0 + timedelta(days=5))
    rows = conn.execute("SELECT id, type, rep, chain FROM appeals ORDER BY id").fetchall()
    assert [r["type"] for r in rows] == ["payment", "payment"]
    assert (rows[1]["rep"], rows[1]["chain"], rows[0]["chain"]) == (1, rows[0]["id"], rows[0]["id"])
    say(conn, MARK, 5, "Click orqali to'lov yana o'tmadi", T0 + timedelta(days=30))  # 21 kundan keyin — yangi zanjir
    assert one(conn, "SELECT rep FROM appeals ORDER BY id DESC")["rep"] == 0


def test_ai_reading(conn, monkeypatch):
    monkeypatch.setattr(config, "ai_enabled", lambda: True)
    answers = []
    monkeypatch.setattr(ai, "_ask", lambda prompt, *a, **k: answers.pop(0) if answers else None)
    answers.append({"act": "appeal", "system": "yagonaplatforma", "type": "docs", "summary": "PDF fayl yuklanmayapti"})
    say(conn, ELON, 1, "fayl tushmayapti hech", T0)
    a = one(conn, "SELECT type, summary, ai FROM appeals")
    assert (a["type"], a["summary"], a["ai"]) == ("docs", "PDF fayl yuklanmayapti", "ai")
    aid = one(conn, "SELECT id FROM appeals")["id"]
    # ro'yxatda yo'q odam supportdek javob berdi: operator deb belgilanadi
    answers.append({"act": "answer", "appeal_ids": [aid], "grade": "good", "solved": True, "note": "Chegara oshirildi"})
    say(conn, (777, "Nilufar"), 2, "Fayl chegarasi 20 MB ga oshirildi, qayta yuklang", T0 + timedelta(minutes=20))
    a = one(conn, "SELECT status, line, answered_by, grade_note FROM appeals")
    assert (a["status"], a["line"], a["answered_by"], a["grade_note"]) == ("hal", 1, "Nilufar", "Chegara oshirildi")
    assert one(conn, "SELECT staff FROM clients WHERE ext = '777'")["staff"] == 1
    answers.append({"act": "answer", "appeal_ids": [99999], "grade": "good", "solved": True})  # to'qilgan id qabul qilinmaydi
    say(conn, (777, "Nilufar"), 3, "Hammasi joyida", T0 + timedelta(minutes=30))
    assert one(conn, "SELECT count(*) FROM appeal_events WHERE kind = 'javob'")[0] == 1


def test_support_linked_to_work_project_and_kept_out_of_work_views(conn):
    say(conn, (11, "Azizbek"), 1, "#hisobot\nBajarildi:\n1. Shajara daraxti eksporti", T0, chat=WORK, title="Shajara - Ishlar")
    work = one(conn, "SELECT id FROM projects WHERE chat_id = ?", (WORK,))["id"]
    say(conn, ELON, 1, "Shajarada FISh noto'g'ri ko'rsatilgan", T0 + timedelta(minutes=5), chat=-100888, title="Shajara yordam")
    a = one(conn, "SELECT project_id, type FROM appeals")
    assert (a["project_id"], a["type"]) == (work, "data")  # bitta tizim: ish va murojaat bir loyihada
    say(conn, MARK, 2, "Sayt ochilmayapti 502", T0 + timedelta(minutes=6))  # Yagona platforma: ish guruhi yo'q
    conn.commit()
    d = analytics.compute(conn, "day", now=T0 + timedelta(hours=1))
    names = [p["name"] for p in d["projects"]]
    assert names == ["Shajara - Ishlar"]  # yordamdan ochilgan tizim ish tahlilida yo'q
    assert d["projects"][0]["appeals"] == {"n": 1, "open": 1, "rep": 0}
    assert {p["name"] for p in d["people"]} == {"Azizbek"}


def test_switch_kind_back_and_forth(conn):
    say(conn, (11, "Azizbek"), 1, "#hisobot\nBajarildi:\n1. Login sahifasi", T0, chat=-100999, title="Test guruh")
    pid = one(conn, "SELECT id FROM projects WHERE chat_id = -100999")["id"]
    appeals.set_chat_kind(conn, -100999, "yordam")
    p = one(conn, "SELECT chat_id, yordam FROM projects WHERE id = ?", (pid,))
    assert (p["chat_id"], p["yordam"]) == (None, 1)
    assert [x["id"] for x in appeals.chat_projects(conn, -100999)] == [pid]
    assert one(conn, "SELECT count(*) FROM members WHERE chat_id = -100999")[0] == 0
    say(conn, ELON, 2, "Parolni tiklash havolasi ishlamayapti", T0 + timedelta(hours=1), chat=-100999, title="Test guruh")
    assert one(conn, "SELECT project_id FROM appeals")["project_id"] == pid
    appeals.set_chat_kind(conn, -100999, "ish")
    p = one(conn, "SELECT chat_id, yordam FROM projects WHERE id = ?", (pid,))
    assert (p["chat_id"], p["yordam"]) == (-100999, 0)
    assert one(conn, "SELECT count(*) FROM projects")[0] == 1


def test_work_group_with_support_word_stays_work(conn):
    say(conn, (11, "Azizbek"), 1, "#hisobot\nBajarildi:\n1. Murojaat formasi", T0, chat=-100444, title="Murojaatlar moduli - Ishlar")
    assert one(conn, "SELECT kind FROM chats WHERE id = -100444")["kind"] == "ish"
    assert one(conn, "SELECT count(*) FROM appeals")[0] == 0


def test_chatbot_push_and_auto_close(conn):
    s = appeals.new_source(conn, "@AdliyaHelpBot", None, "Admin")
    src = appeals.source_by_token(conn, s["token"])
    assert src is not None and appeals.source_by_token(conn, "pm_noto'g'ri") is None
    item = {"id": "A-1", "user": "u1", "text": "SMS kod kelmayapti", "at": "2026-10-26T10:00:00+05:00", "system": "Adliya mobile",
            "answers": [{"text": "Biroz kutib, kodni qayta so'rang", "at": "2026-10-26T10:01:00+05:00", "bot": True}]}
    out = appeals.push(conn, src, [item, {"id": "", "text": "x"}])
    assert (out["added"], len(out["errors"])) == (1, 1)
    a = one(conn, "SELECT a.*, p.name FROM appeals a JOIN projects p ON p.id = a.project_id")
    assert (a["source"], a["type"], a["status"], a["line"], a["grade"], a["name"]) == ("bot", "sms", "javob", 0, "tpl", "Adliya mobile")
    item["answers"].append({"text": "SMS provayderidagi navbat tozalandi, kod qayta yuborildi", "at": "2026-10-26T11:00:00+05:00", "line": 2})
    out = appeals.push(conn, src, [item])
    assert out["updated"] == 1 and one(conn, "SELECT count(*) FROM appeals")[0] == 1
    a = one(conn, "SELECT status, line, grade, first_grade FROM appeals")
    assert (a["status"], a["line"], a["grade"], a["first_grade"]) == ("hal", 2, "good", "tpl")
    appeals.push(conn, src, [{"id": "A-2", "user": "u2", "text": "Qanday ariza topshiriladi?", "at": "2026-10-26T12:00:00",
                              "answers": [{"text": "Saytdagi yo'riqnomani o'qing", "at": "2026-10-26T12:05:00"}]}])
    assert appeals.auto_close(conn, datetime(2026, 10, 27, 11, 0)) == 0
    assert appeals.auto_close(conn, datetime(2026, 10, 27, 13, 0)) == 1
    a = one(conn, "SELECT status, resolution, resolved_at FROM appeals WHERE ext_id = 'A-2'")
    assert (a["status"], a["resolution"], a["resolved_at"]) == ("hal", "jim", "2026-10-26 12:05:00")


def test_overview_real_and_sample(conn):
    d = appeals.overview(conn, datetime(2026, 10, 26, 18, 0))
    assert d["sample"] and d["kpi"]["n"] > 300 and d["projects"][0]["name"] == "Yagona platforma"
    assert d["insights"] and d["repeats"] and d["repeats"][0]["cause"]
    det = appeals.detail(conn, d["feed"]["items"][0]["id"], sample=True)
    assert det["sample"] and det["events"][0]["kind"] == "murojaat"
    say(conn, ELON, 1, "OneID orqali kira olmayapman", T0)
    say(conn, OWNER, 2, "Keyinroq urinib ko'ring", T0 + timedelta(minutes=10), reply=1)
    say(conn, ELON, 3, "OneID yana kira olmayapman", T0 + timedelta(days=1, hours=1))
    say(conn, MARK, 4, "Arizam 5 kundan beri ko'rib chiqilmoqda", T0 + timedelta(days=1, hours=2))
    conn.commit()
    d = appeals.overview(conn, datetime(2026, 10, 28, 18, 0))
    assert not d["sample"] and d["kpi"]["n"] == 3 and d["kpi"]["rep"] == 1
    assert d["projects"][0]["name"] == "Yagona platforma" and d["projects"][0]["n"] == 3
    assert d["quality"]["tpl"] == 1 and d["quality"]["none"] == 2
    assert [t["key"] for t in d["types"]][:1] == ["login"]
    assert d["feed"]["total"] == 3 and d["feed"]["items"][0]["type"] == "status"
    assert appeals.overview(conn, datetime(2026, 10, 28, 18, 0), status="takror")["feed"]["total"] == 1
    det = appeals.detail(conn, d["feed"]["items"][-1]["id"])
    assert [e["kind"] for e in det["events"]] == ["murojaat", "javob"] and det["appeal"]["chain"]
    # vaqt mashinasi: 26-oktyabr oxiri — keyingi kunlar hali yo'q
    assert appeals.overview(conn, datetime(2026, 10, 26, 23, 59, 59))["kpi"]["n"] == 1


def test_correction_by_head(conn):
    say(conn, ELON, 1, "nimadir ishlamayapti", T0)
    aid = one(conn, "SELECT id FROM appeals")["id"]
    appeals.correct(conn, aid, "Feruzbek", typ="mobile", status="hal")
    a = one(conn, "SELECT type, status, resolution, fixed_by FROM appeals")
    assert (a["type"], a["status"], a["resolution"], a["fixed_by"]) == ("mobile", "hal", "qolda", "Feruzbek")
    with pytest.raises(ValueError):
        appeals.correct(conn, aid, "Feruzbek", typ="yoq")


def test_bot_silent_in_support_and_agent_views(conn, monkeypatch):
    from puls import bot
    say(conn, ELON, 1, "Sayt ochilmayapti", T0)
    conn.commit()
    monkeypatch.setattr(db, "session", lambda: _Same(conn))
    assert bot._support_chat(SUP) and not bot._support_chat(WORK)
    rows = conn.execute("SELECT loyiha, turi, holat FROM %s" % ("agent.murojaatlar" if db.PG else "murojaatlar")).fetchall()
    assert [tuple(r) for r in rows] == [("Yagona platforma", "slow", "ochiq")]
    assert "murojaatlar" in sqlro.DOC


class _Same:
    def __init__(self, c):
        self.c = c

    def __enter__(self):
        return self.c

    def __exit__(self, *a):
        return False


def test_web_endpoints(conn, monkeypatch):
    from puls import web
    say(conn, ELON, 1, "OneID orqali kira olmayapman", T0)
    conn.commit()
    req = SimpleNamespace(state=SimpleNamespace(acc=web.LOCAL), query_params={})
    monkeypatch.setattr(config, "now", lambda: datetime(2026, 10, 26, 18, 0))
    d = web.appeals_overview(req, asof=None)
    assert d["kpi"]["n"] == 1 and not d["sample"]
    aid = d["feed"]["items"][0]["id"]
    assert web.appeal_detail(req, aid)["appeal"]["type"] == "login"
    web.appeal_fix(req, aid, web.AppealFix(status="hal"), acc=web.LOCAL)
    assert one(conn, "SELECT status FROM appeals")["status"] == "hal"
    assert "/api/appeals/push" in web.OPEN
    m = web.meta(req)
    assert [c["kind"] for c in m["chats"]] == ["yordam"] and m["projects"] == [] and m["systems"][0]["yordam"] == 1
