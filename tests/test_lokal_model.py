"""Lokal model (llama.cpp, OpenAI'ga mos API) va murojaat tizimini taxmin qilmaslik: bir nechta tizimga xizmat qiladigan
guruhda tizim aytilmagan murojaat "aniqlanmagan" bo'ladi (SMS, login hamma tizimda bor)."""
import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from puls import ai, appeals, config, db
from puls.ingest import Incoming, ingest

CHAT = -100321
T0 = datetime(2026, 10, 27, 10, 0)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 1)
    db.init()
    c = db.connect()
    yield c
    c.close()


@pytest.fixture()
def fake_llm(monkeypatch):
    """llama.cpp serveri o'rnida: navbatdagi javobni qaytaradi, kelgan so'rovlarni yozib boradi."""
    state = {"answers": [], "got": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["got"].append((self.path, body))
            ans = state["answers"].pop(0) if state["answers"] else {"act": "none"}
            out = json.dumps({"choices": [{"message": {"content": json.dumps(ans)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "LOCAL_AI_URL", "http://127.0.0.1:%d/v1" % srv.server_port)
    monkeypatch.setattr(config, "APPEALS_AI", "local")
    yield state
    srv.shutdown()


def test_json_schema_conversion():
    s = ai.json_schema(appeals.SUPPORT_SCHEMA)
    assert s["type"] == "object" and s["required"] == ["act"]
    assert s["properties"]["system"]["type"] == ["string", "null"]
    assert s["properties"]["grade"]["enum"][-1] is None and "tpl" in s["properties"]["grade"]["enum"]
    assert s["properties"]["appeal_ids"] == {"type": "array", "items": {"type": "integer"}}


def test_ask_local_request_shape(fake_llm):
    fake_llm["answers"].append({"act": "appeal", "system": None, "type": "sms", "summary": "SMS kelmayapti"})
    out = ai.ask_appeals("salom sms kelmayapti", appeals.SUPPORT_SCHEMA)
    assert out["type"] == "sms"
    path, body = fake_llm["got"][0]
    assert path == "/v1/chat/completions"
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and body["temperature"] == 0
    assert body["response_format"]["json_schema"]["schema"]["properties"]["act"]["enum"][0] == "appeal"


def test_waits_while_model_is_loading(monkeypatch):
    """Qayta ishga tushgan llama.cpp model yuklanguncha 503 qaytaradi: bu xato emas, javob kutiladi (qoidaga o'tilmaydi)."""
    calls = []

    def fake(prompt, schema, max_tokens=600, timeout=None):
        calls.append(1)
        if len(calls) <= 3:
            raise ai.urllib.error.HTTPError("http://x", 503, "Loading model", {}, None)
        return {"act": "none"}
    monkeypatch.setattr(ai, "_call_local", fake)
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "LOCAL_AI_URL", "http://x/v1")
    assert ai.ask_local("salom", appeals.SUPPORT_SCHEMA, retries=0) == {"act": "none"} and len(calls) == 4


def test_local_model_down_falls_back_to_rules(conn, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_AI_URL", "http://127.0.0.1:9/v1")  # hech kim tinglamaydi
    monkeypatch.setattr(config, "APPEALS_AI", "local")
    ingest(conn, Incoming(CHAT, "Yagona platforma | Yordam", 1, 501, "Elon Musk", None, T0, "OneID orqali kira olmayapman"), use_ai=True)
    a = conn.execute("SELECT type, ai FROM appeals").fetchone()
    assert (a["type"], a["ai"]) == ("login", "qoida")


def test_pick_system_never_guesses_by_problem_type():
    systems = [{"id": 1, "key": "zags", "name": "Zags", "aliases": "FHDY"}, {"id": 2, "key": "shajara", "name": "Shajara", "aliases": ""},
               {"id": 3, "key": "apostil", "name": "Apostil", "aliases": ""}]
    assert appeals.pick_system(systems, None, "salom sms kelmayapti") is None
    assert appeals.pick_system(systems, None, "login ishlamayapti, parol xato deyapti") is None
    assert appeals.pick_system(systems, None, "Apostil uchun sms kod kelmayapti") == 3
    assert appeals.pick_system(systems, None, "shajarada ma'lumot noto'g'ri") == 2  # qo'shimcha bilan yozilgan nom ham taniladi
    assert appeals.pick_system(systems, None, "fhdy bo'limida guvohnoma") == 1  # boshqa nomi bilan
    assert appeals.pick_system(systems, None, "zags va apostil ikkalasida ham xato") is None  # ikkita tizim aytilgan: odam hal qiladi
    assert appeals.pick_system(systems, "zags", "guvohnoma yuklanmayapti") == 1
    assert appeals.pick_system(systems, "boshqa", "guvohnoma yuklanmayapti") is None  # ro'yxatda yo'q kalit qabul qilinmaydi
    assert appeals.pick_system(systems[:1], None, "sms kelmayapti") == 1  # guruh bitta tizimga xizmat qiladi: manba aytadi


def test_shared_chat_unknown_system_goes_to_review(conn, fake_llm):
    ingest(conn, Incoming(CHAT, "FHDY bo'limlari chati | Yordam", 1, 501, "Elon Musk", None, T0, "salom"), use_ai=True)
    zags = conn.execute("INSERT INTO projects(key, name, created_at, yordam) VALUES('zags', 'Zags', ?, 1)", (T0.isoformat(),)).lastrowid
    shaj = conn.execute("INSERT INTO projects(key, name, created_at, yordam) VALUES('shajara', 'Shajara', ?, 1)", (T0.isoformat(),)).lastrowid
    appeals.set_chat_kind(conn, CHAT, "yordam", [zags, shaj])
    fake_llm["answers"].append({"act": "appeal", "system": None, "type": "sms", "summary": "SMS kod kelmayapti"})
    ingest(conn, Incoming(CHAT, "FHDY bo'limlari chati | Yordam", 2, 501, "Elon Musk", None, T0 + timedelta(minutes=1),
                          "sms kod kelmayapti"), use_ai=True)
    fake_llm["answers"].append({"act": "appeal", "system": "shajara", "type": "data", "summary": "Shajarada ism xato"})
    ingest(conn, Incoming(CHAT, "FHDY bo'limlari chati | Yordam", 3, 502, "Mark", None, T0 + timedelta(minutes=2),
                          "shajara daraxtida ism xato chiqyapti"), use_ai=True)
    rows = conn.execute("SELECT project_id, type, ai FROM appeals ORDER BY id").fetchall()
    assert [(r["project_id"], r["type"], r["ai"]) for r in rows] == [(None, "sms", "ai"), (shaj, "data", "ai")]
    conn.commit()
    d = appeals.overview(conn, datetime(2026, 10, 27, 18, 0))
    assert d["kpi"]["unknown"] == 1 and d["unknown_id"] == appeals.UNKNOWN
    assert {p["name"] for p in d["projects"]} == {"Tizim aniqlanmagan", "Shajara"}
    only = appeals.overview(conn, datetime(2026, 10, 27, 18, 0), project=appeals.UNKNOWN)
    assert only["feed"]["total"] == 1 and only["feed"]["items"][0]["type"] == "sms"
    # rahbar tizimni tanlaydi: misol o'quv to'plamiga "tekshirilgan" bo'lib tushadi
    aid = conn.execute("SELECT id FROM appeals WHERE project_id IS NULL").fetchone()["id"]
    appeals.correct(conn, aid, "Feruzbek", project_id=zags)
    data = {r["id"]: r for r in appeals.dataset(conn)}
    assert data[aid]["system"] == "Zags" and data[aid]["checked"] is True
    assert sum(1 for r in data.values() if not r["checked"]) == 1


def test_user_context_has_only_own_messages(conn, fake_llm):
    """Call-markaz, bot, pochta kanalida ketma-ket xabarlar turli odamlarniki: B'ning xabarini o'qishda A'ning gapi va
    murojaati modelga berilmaydi (aks holda model B'ga A'ning tizimini yopishtiradi). Xodim javobida esa butun suhbat."""
    title = "1008 | Yordam"
    ingest(conn, Incoming(CHAT, title, 1, 501, "Laylo", None, T0, "salom"), use_ai=True)
    ap = conn.execute("INSERT INTO projects(key, name, created_at, yordam) VALUES('apostil', 'Apostil', ?, 1)", (T0.isoformat(),)).lastrowid
    no = conn.execute("INSERT INTO projects(key, name, created_at, yordam) VALUES('notariat', 'Notariat', ?, 1)", (T0.isoformat(),)).lastrowid
    appeals.set_chat_kind(conn, CHAT, "yordam", [ap, no])
    fake_llm["answers"].append({"act": "appeal", "system": "apostil", "type": "payment", "summary": "Apostil to'lovi o'tmadi"})
    ingest(conn, Incoming(CHAT, title, 2, 501, "Laylo", None, T0 + timedelta(minutes=1), "Apostil bojini to'ladim, holat o'zgarmadi"),
           use_ai=True)
    fake_llm["answers"].append({"act": "appeal", "system": None, "type": "howto", "summary": "Qaysi hujjatlar kerak"})
    ingest(conn, Incoming(CHAT, title, 3, 502, "Otabek", None, T0 + timedelta(minutes=2), "Qaysi hujjatlar kerak?"), use_ai=True)
    user_prompt = fake_llm["got"][-1][1]["messages"][0]["content"]
    assert "Qaysi hujjatlar kerak?" in user_prompt
    assert "Apostil bojini" not in user_prompt and "Apostil to'lovi" not in user_prompt and "Laylo" not in user_prompt
    fake_llm["answers"].append({"act": "answer", "appeal_ids": [], "grade": "part", "solved": False, "note": "x"})
    ingest(conn, Incoming(CHAT, title, 4, 1, "Operator", None, T0 + timedelta(minutes=3), "Apostil holati yangilandi"), use_ai=True)
    staff_prompt = fake_llm["got"][-1][1]["messages"][0]["content"]
    assert "Apostil bojini" in staff_prompt and "Qaysi hujjatlar kerak?" in staff_prompt


def test_voice_not_sent_outside_in_local_mode(conn, fake_llm, monkeypatch):
    called = []
    monkeypatch.setattr(ai, "transcribe", lambda *a, **k: called.append(1) or "matn")
    inc = Incoming(-100654, "Adliya mobile | Yordam", 1, 501, "Elon Musk", None, T0, "")
    inc.media, inc.mime = b"OggS...", "audio/ogg"
    fake_llm["answers"].append({"act": "appeal", "system": None, "type": "boshqa", "summary": "Ovozli murojaat"})
    ingest(conn, inc, use_ai=True)
    assert called == []  # lokal rejimda ovoz Gemini'ga yuborilmaydi
    assert conn.execute("SELECT text FROM messages").fetchone()["text"] == "[Ovozli xabar]"
