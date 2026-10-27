"""Boshqa tizim bazasidan olingan xabarlar oqimi (guruh, bot, call-markaz, pochta): kanal = yordam guruhi, nomida lavozimi
bor odam = xodim, boshqa raqamlashdagi javob havolasi taxmin qilinmaydi."""
import pytest

from puls import appeals, config, db

ITEMS = [
    {"id": "MRJ-000001", "vaqt": "2026-10-20T09:00:00+05:00", "manba": "telegram_group", "manba_nomi": "Adliya yordam guruhi",
     "kimdan": "Nodira K.", "matn": "OneID orqali kira olmayapman, xatolik chiqyapti"},
    {"id": "MRJ-000002", "vaqt": "2026-10-20T09:05:00+05:00", "manba": "telegram_group", "manba_nomi": "Adliya yordam guruhi",
     "kimdan": "Operator Nigora", "matn": "Sessiyangiz tozalandi, xato tuzatildi. Qayta kirib ko'ring.", "javob_berilgan_xabar": 9931},
    {"id": "MRJ-000003", "vaqt": "2026-10-20T09:20:00+05:00", "manba": "telegram_group", "manba_nomi": "Adliya yordam guruhi",
     "kimdan": "Nodira K.", "matn": "Rahmat, hal bo'ldi", "javob_berilgan_xabar": 2},
    {"id": "MRJ-000004", "vaqt": "2026-10-20T10:00:00+05:00", "manba": "telegram_group", "manba_nomi": "Adliya yordam guruhi",
     "kimdan": "Aleksey", "matn": "Ingliz tili kurslari 50% chegirma! t.me/english_uz"},
    {"id": "MRJ-000005", "vaqt": "2026-10-20T10:30:00+05:00", "manba": "call_center", "manba_nomi": "1008",
     "kimdan": "Otabek M.", "matn": "Ариза ҳолати умуман кўринмаяпти, маълумот топилмади деяпти"},
    {"id": "MRJ-000006", "vaqt": "2026-10-20T11:00:00+05:00", "manba": "email", "manba_nomi": "info@adliya.uz",
     "kimdan": "Laylo", "mavzu": "Apostil", "matn": "Hujjatga apostil qo'yish uchun to'lov qildim, holat o'zgarmadi"},
    {"id": "MRJ-000009", "vaqt": "2026-10-20T11:05:00+05:00", "manba": "email", "manba_nomi": "info@adliya.uz",
     "kimdan": "Jamshid", "mavzu": "Notarius", "matn": "Ishonchnoma uchun qaysi hujjatlar kerak?"},
    {"id": "MRJ-000007", "vaqt": "2026-10-20T11:10:00+05:00", "manba": "telegram_group", "manba_nomi": "Apostil masalalari",
     "kimdan": "Sardor", "matn": "SMS kod kelmayapti"},
    {"id": "MRJ-000008", "vaqt": "2026-10-20T11:15:00+05:00", "manba": "telegram_group", "manba_nomi": "Apostil masalalari",
     "kimdan": "Sardor", "matn": "", "ilovalar": [{"type": "sticker"}]},
]
SYSTEMS = {"Adliya yordam guruhi": ["Apostil", "Notariat"], "1008": ["Apostil", "Notariat"],
           "info@adliya.uz": ["Apostil", "Notariat"], "Apostil masalalari": ["Apostil"]}


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "OWNER_ID", 1)
    monkeypatch.setattr(config, "APPEALS_AI", "off")
    db.init()
    c = db.connect()
    for key, name, aliases in (("apostil", "Apostil", "apostil,апостил"), ("notariat", "Notariat", "notari,нотари")):
        c.execute("INSERT INTO projects(key, name, created_at, yordam, aliases) VALUES(?, ?, '2026-10-01 00:00:00', 1, ?)",
                  (key, name, aliases))
    yield c
    c.close()


def test_stream_import(conn):
    out = appeals.import_stream(conn, ITEMS, use_ai=False, systems=SYSTEMS)
    assert out["errors"] == [] and out["channels"] == 4 and out["skipped"] == 1  # stiker: matnsiz
    rows = {r["text"][:20]: dict(r) for r in conn.execute(
        "SELECT a.*, p.name AS system FROM appeals a LEFT JOIN projects p ON p.id = a.project_id ORDER BY a.id")}
    assert len(rows) == 5  # reklama va "rahmat" murojaat emas
    assert rows["Notarius\nIshonchnoma"]["system"] == "Notariat"  # pochta mavzusi matn boshiga qo'shildi va tizimni aytdi
    login = rows["OneID orqali kira ol"]
    assert login["type"] == "login" and login["system"] is None  # umumiy kanal, tizim aytilmagan: taxmin qilinmaydi
    assert login["status"] == "hal" and login["answered_by"] == "Operator Nigora" and login["line"] == 1
    assert rows["Ариза ҳолати умуман "]["type"] == "status"  # kirill yozuvi ham tanildi
    apo = rows["Hujjatga apostil qo'"]  # mavzu matnda bor: qayta qo'shilmaydi
    assert apo["system"] == "Apostil" and apo["type"] == "payment"
    assert rows["SMS kod kelmayapti"]["system"] == "Apostil"  # kanal bitta tizimga xizmat qiladi
    # xodim xodimlar ro'yxatiga tushmaydi, mijoz bo'lib ham qolmaydi
    assert conn.execute("SELECT count(*) FROM people").fetchone()[0] == 0
    staff = conn.execute("SELECT name, staff FROM clients WHERE staff >= 1").fetchall()
    assert [(r["name"], r["staff"]) for r in staff] == [("Operator Nigora", 1)]
    # qayta yuklansa takrorlanmaydi
    again = appeals.import_stream(conn, ITEMS, use_ai=False, systems=SYSTEMS)
    assert again["added"] == 0 and conn.execute("SELECT count(*) FROM appeals").fetchone()[0] == 5


def test_foreign_reply_id_not_guessed(conn):
    """Havoladagi raqam boshqa raqamlashdan (Telegram ichki raqami) bo'lsa, raqami o'xshash boshqa xabarga ulanmaydi."""
    items = [dict(ITEMS[0], id="1"), dict(ITEMS[4], id="2", manba_nomi="Adliya yordam guruhi", kimdan="Otabek"),
             dict(ITEMS[1], id="3", javob_berilgan_xabar=2, matn="Arizangiz qayta yo'naltirildi")]
    appeals.import_stream(conn, items[:2], use_ai=False, systems=SYSTEMS)
    msg = conn.execute("SELECT reply_to FROM messages WHERE text LIKE 'Ариза%'").fetchone()
    assert msg["reply_to"] is None
    appeals.import_stream(conn, items[2:], use_ai=False, systems=SYSTEMS)
    rep = conn.execute("SELECT reply_to FROM messages WHERE text LIKE 'Arizangiz%'").fetchone()
    assert rep["reply_to"] is None  # "2" bu partiyada yo'q: alohida yuklangan fayllar orasida havola taxmin qilinmaydi


def test_latin_and_noise_rules():
    assert appeals.latin("Ариза ҳолати") == "ariza holati"
    assert appeals.guess_type("Свидетельство готово, но не скачивается") == "cert"
    assert appeals.guess_type("Davlat boji ikki marta yechib olindi") == "payment"
    assert appeals.NOISE_RE.search("Arzon kvartiralar Toshkentda")
    assert not appeals.NOISE_RE.search("Apostil uchun to'lov o'tmadi")
