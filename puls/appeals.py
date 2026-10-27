"""Murojaatlar: axborot tizimlari foydalanuvchilarining yordam guruhlari va chatbotlarga yozgan savol va shikoyatlari.

Loyiha = axborot tizimi. Ish guruhi (chats.kind = 'ish') jamoaning hisobotlari uchun; yordam guruhi (chats.kind = 'yordam')
bir yoki bir nechta tizimga xizmat qiladi (chat_projects), chatbot esa murojaatlarni kalit bilan API orqali yuboradi
(appeal_sources). Ikkala oqim bir-biriga aralashmaydi: yordam guruhidagi odamlar xodimlar ro'yxatiga tushmaydi (clients),
xabarlari vazifa yoki hisobot bo'lmaydi, ish tahlilida (hisobot, reyting) ko'rinmaydi.

Yordam guruhidagi har xabar bittasi: yangi murojaat | o'z murojaatiga qo'shimcha | xodim javobi (bahosi bilan) |
foydalanuvchi tasdig'i ("ishladi, rahmat") | qayta ochish ("hali ham ishlamayapti") | boshqa gap. Uni AI suhbat
kontekstida o'qiydi; AI ishlamasa kalit so'zlar bo'yicha qoida ishlaydi.

Hisob Feruzbek maketidagi formulalar bilan: hal qilingan ulush, o'rtacha hal qilish vaqti, takroriy murojaat (bir odam,
bir tizim, bir tur, 21 kun ichida), shablon yoki javobsiz qolgan murojaatlar, e'tibor indeksi (0-100).
"""
import hashlib
import json
import logging
import re
import secrets
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import ai, config, db

log = logging.getLogger("puls.appeals")
FMT = "%Y-%m-%d %H:%M:%S"

TYPES = {
    "login": "Tizimga kirish (OneID, parol)",
    "status": "Ariza holati va muddati",
    "docs": "Hujjat yuklashda xatolik",
    "slow": "Tizim sekin yoki ochilmayapti",
    "howto": "Qanday foydalanish kerak",
    "cert": "Tayyor hujjatni yuklab olish",
    "data": "Shaxsiy ma'lumotlar noto'g'ri",
    "payment": "To'lov o'tgan, holat o'zgarmagan",
    "sms": "SMS kod kelmayapti",
    "mobile": "Mobil ilovada xatolik",
    "boshqa": "Boshqa savol",
}
LINES = {0: "Chatbot", 1: "Operator", 2: "Mutaxassis", 3: "Dasturchi"}
GRADES = {"good": "To'liq hal qilgan", "part": "Qisman", "tpl": "Shablon javob", "none": "Javobsiz"}
STATUS = {"ochiq": "Ochiq", "javob": "Javob berildi", "hal": "Hal qilindi", "qayta": "Qayta ochildi"}
OPEN = ("ochiq", "javob", "qayta")
REPEAT_DAYS = 21          # shu kun ichida bir odam bir tizim bo'yicha bir xil turdagi muammo bilan qaytsa — takroriy
SILENT_HOURS = 24         # javobdan keyin foydalanuvchi shuncha soat yozmasa murojaat yopiladi ("jim")
FOLLOW_MIN = 30           # AI'siz: o'z ochiq murojaatiga shu daqiqa ichida yozgani — qo'shimcha, yangi murojaat emas
DEV_DEPTS = {"AI", "Backend", "Frontend", "Fullstack", "DevOps"}
SUPPORT_RE = re.compile(r"yordam|support|help|qo.?llab|murojaat|savol|helpdesk|поддерж|помощ|обращен", re.I)
# guruh nomidan tizim nomi: "Yagona platforma | Yordam" -> "Yagona platforma"
SYS_TAIL_RE = re.compile(r"\s*[|—–:-]*\s*(yordam|support|help|qo.?llab(-|\s)?quvvatlash|murojaat\w*|savol\w*|helpdesk|"
                         r"guruhi|chati|поддержка|помощь)\b.*$", re.I)
GENERIC = {"ishlar", "ish", "jamoa", "jamoasi", "guruh", "guruhi", "team", "yordam", "support", "help", "chat", "chati",
           "loyiha", "loyihasi", "si", "test", "va", "uchun"}


def _now() -> str:
    return config.now().strftime(FMT)


def _ts(dt: datetime) -> str:
    return dt.strftime(FMT)


def _dt(s: str) -> datetime:
    return datetime.strptime(s[:19], FMT)


def _hours(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return max(0.0, (_dt(b) - _dt(a)).total_seconds() / 3600)


def fold(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").lower().replace("'", "").replace("ʻ", "").replace("’", "").replace("‘", "")))


def core_name(name: str) -> str:
    """Tizim nomining o'zagi: "Shajara - Ishlar" va "Shajara yordam" ikkalasi ham "shajara"."""
    return " ".join(w for w in fold(name).split() if w not in GENERIC)


def system_name(title: str) -> str:
    from .ingest import clean_name
    base = SYS_TAIL_RE.sub("", title or "").strip(" |—–:-")
    return clean_name(base or title or "")[:80] or "Yordam guruhi"


# ---------------------------------------------------------------- guruh turi va tizim

def chat_kind(conn: sqlite3.Connection, chat_id: int | None) -> str:
    if not chat_id:
        return "ish"
    r = conn.execute("SELECT kind FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return (r["kind"] if r is not None and r["kind"] else "ish")


WORK_RE = re.compile(r"ishlar|jamoa|team|dasturchi|developer|\bdev\b|loyiha|internship|amaliyot", re.I)


def looks_support(title: str) -> bool:
    """Nomidan yordam guruhiga o'xshaydimi: "Yagona platforma | Yordam" ha, "Murojaatlar moduli - Ishlar" yo'q."""
    return bool(SUPPORT_RE.search(title or "")) and not WORK_RE.search(title or "")


def is_support(conn: sqlite3.Connection, chat_id: int | None, title: str | None) -> bool:
    """Guruh yordam guruhimi. Turi hali belgilanmagan guruh birinchi ko'rilganda bir marta belgilanadi: nomida "yordam",
    "support" kabi so'z bo'lsa va ish ma'lumoti hali yo'q bo'lsa — yordam guruhi, aks holda ish guruhi (keyin nomi
    o'zgarsa ham turi o'zicha almashmaydi; panelda admin almashtiradi)."""
    if not chat_id or chat_id > 0:
        return False
    r = conn.execute("SELECT kind FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if r is not None and r["kind"]:
        return r["kind"] == "yordam"
    support = looks_support(title or "") and not conn.execute("SELECT 1 FROM projects WHERE chat_id = ?", (chat_id,)).fetchone()
    if r is not None:
        conn.execute("UPDATE chats SET kind = ? WHERE id = ?", ("yordam" if support else "ish", chat_id))
    elif support:
        conn.execute("INSERT INTO chats(id, title, demo, added_at, kind) VALUES(?, ?, 0, ?, 'yordam') ON CONFLICT(id) DO UPDATE "
                     "SET kind = 'yordam'", (chat_id, title or "", _now()))
    return support


def chat_projects(conn: sqlite3.Connection, chat_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT p.id, p.key, p.name, p.aliases FROM chat_projects cp JOIN projects p ON p.id = cp.project_id "
        "WHERE cp.chat_id = ? ORDER BY p.id", (chat_id,))]


UNKNOWN = -1_000_000  # tahlilda "tizim aniqlanmagan" guruhi (bazada project_id NULL)


def pick_system(systems: list[dict], ai_key: str | None, text: str) -> int | None:
    """Murojaat qaysi tizimga tegishli. Guruh bitta tizimga xizmat qilsa — o'sha: buni manbaning o'zi aytadi, xato bo'lmaydi.
    Bir nechtasiga xizmat qilsa — faqat AI yoki matnning o'zi tizimni ko'rsatsa; aks holda None ("tizim aniqlanmagan", odam
    tasdiqlaydi). Muammo turiga (SMS, login, to'lov) qarab tanlanmaydi: ular hamma tizimda bor, taxmin xato bo'lardi."""
    if len(systems) == 1:
        return systems[0]["id"]
    keys = {p["key"]: p["id"] for p in systems}
    if ai_key and ai_key in keys:
        return keys[ai_key]
    low = " %s " % fold(text)
    toks = low.split()

    def named(n: str) -> bool:
        c = core_name(n)
        if len(c) < 3:
            return False
        if " " in c:
            return " %s " % c in low
        return any(t == c or (len(c) >= 4 and t.startswith(c)) for t in toks)  # "shajarada", "zagsda", "apostilga"
    hits = []
    for p in systems:
        names = [p["name"] or ""] + [a for a in (p.get("aliases") or "").split(",") if a.strip()]
        if any(named(n) for n in names):
            hits.append(p["id"])
    return hits[0] if len(hits) == 1 else None


def find_project(conn: sqlite3.Connection, name: str) -> dict | None:
    """Nomi (yoki boshqa nomi) mos tizim; ish guruhining loyihasi birinchi: yordam guruhi shu loyihaga bog'lanadi va rahbar
    bir loyihada ham jamoa ishini, ham kelgan murojaatlarni ko'radi."""
    want, key = core_name(name), fold(name)
    if not want:
        return None
    best = None
    for p in conn.execute("SELECT id, key, name, aliases, chat_id, coalesce(yordam, 0) AS yordam FROM projects ORDER BY id"):
        names = [p["name"] or "", p["key"] or ""] + [a for a in (p["aliases"] or "").split(",") if a.strip()]
        if any(core_name(n) == want or fold(n) == key for n in names):
            if best is None or (best["yordam"] and not p["yordam"]):
                best = dict(p)
    return best


def support_project(conn: sqlite3.Connection, chat_id: int, title: str, when: str | None = None) -> dict:
    """Yordam guruhining tizimi: bog'langan bo'lsa o'sha; bo'lmasa guruh nomidan topiladi yoki ochiladi (ish tahlilida
    ko'rinmaydigan "yordam" loyihasi)."""
    rows = chat_projects(conn, chat_id)
    if rows:
        return rows[0]
    from .parser import norm_key
    name = system_name(title)
    proj = find_project(conn, name)
    if proj is None:
        key = norm_key(name) or "yordam%d" % abs(chat_id)
        if conn.execute("SELECT 1 FROM projects WHERE key = ?", (key,)).fetchone():
            key = "%s-%d" % (key, abs(chat_id))
        conn.execute("INSERT INTO projects(key, name, chat_id, created_at, yordam) VALUES(?, ?, NULL, ?, 1)",
                     (key, name, when or _now()))
        proj = dict(conn.execute("SELECT id, key, name, aliases FROM projects WHERE key = ?", (key,)).fetchone())
    conn.execute("INSERT INTO chat_projects(chat_id, project_id) VALUES(?, ?) ON CONFLICT DO NOTHING", (chat_id, proj["id"]))
    return {k: proj[k] for k in ("id", "key", "name", "aliases")}


def set_chat_kind(conn: sqlite3.Connection, chat_id: int, kind: str, project_ids: list[int] | None = None,
                  new_name: str | None = None) -> dict:
    """Guruh turini almashtirish (panelda, admin). Ish -> yordam: guruhning ish loyihasi tizim sifatida yordam guruhiga
    bog'lanadi (ish tahlilidan chiqadi), guruh a'zolari jamoa hisoblanmaydi. Yordam -> ish: hammasi orqaga qaytadi."""
    if kind not in ("ish", "yordam"):
        raise ValueError("Guruh turi: ish yoki yordam")
    chat = conn.execute("SELECT id, title FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if chat is None:
        raise ValueError("Guruh topilmadi")
    when = _now()
    conn.execute("UPDATE chats SET kind = ? WHERE id = ?", (kind, chat_id))
    if kind == "yordam":
        own = [dict(r) for r in conn.execute("SELECT id FROM projects WHERE chat_id = ?", (chat_id,))]
        for p in own:
            conn.execute("UPDATE projects SET chat_id = NULL, yordam = 1 WHERE id = ?", (p["id"],))
        conn.execute("DELETE FROM members WHERE chat_id = ?", (chat_id,))
        want = [int(x) for x in project_ids or []]
        if new_name and new_name.strip():
            from .parser import norm_key
            name = " ".join(new_name.split())[:80]
            proj = find_project(conn, name)
            if proj is None:
                key = norm_key(name) or "yordam%d" % abs(chat_id)
                if conn.execute("SELECT 1 FROM projects WHERE key = ?", (key,)).fetchone():
                    key = "%s-%d" % (key, abs(chat_id))
                conn.execute("INSERT INTO projects(key, name, chat_id, created_at, yordam) VALUES(?, ?, NULL, ?, 1)", (key, name, when))
                proj = conn.execute("SELECT id FROM projects WHERE key = ?", (key,)).fetchone()
            want.append(proj["id"])
        if not want:
            want = [p["id"] for p in own]
        if want:
            for pid in want:
                if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone():
                    raise ValueError("Loyiha topilmadi")
            conn.execute("DELETE FROM chat_projects WHERE chat_id = ?", (chat_id,))
            for pid in dict.fromkeys(want):
                conn.execute("INSERT INTO chat_projects(chat_id, project_id) VALUES(?, ?) ON CONFLICT DO NOTHING", (chat_id, pid))
        else:
            support_project(conn, chat_id, chat["title"] or "", when)
    else:
        linked = chat_projects(conn, chat_id)
        conn.execute("DELETE FROM chat_projects WHERE chat_id = ?", (chat_id,))
        if not conn.execute("SELECT 1 FROM projects WHERE chat_id = ?", (chat_id,)).fetchone():
            for p in linked:  # yordam uchun ochilgan, boshqa guruhga bog'lanmagan tizim — shu ish guruhining loyihasi bo'ladi
                row = conn.execute("SELECT chat_id, coalesce(yordam, 0) AS yordam FROM projects WHERE id = ?", (p["id"],)).fetchone()
                other = conn.execute("SELECT 1 FROM chat_projects WHERE project_id = ?", (p["id"],)).fetchone()
                if row and row["chat_id"] is None and row["yordam"] and other is None:
                    conn.execute("UPDATE projects SET chat_id = ?, yordam = 0 WHERE id = ?", (chat_id, p["id"]))
                    break
        from .ingest import ensure_group_projects
        ensure_group_projects(conn)
    db.bump_version(conn)
    return {"kind": kind, "projects": chat_projects(conn, chat_id)}


# ---------------------------------------------------------------- kim yozdi

def _in_work_group(conn: sqlite3.Connection, user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM members m JOIN chats c ON c.id = m.chat_id WHERE m.user_id = ? AND m.left_at IS NULL "
                        "AND coalesce(c.kind, 'ish') = 'ish' LIMIT 1", (user_id,)).fetchone() is not None


def _staff_line(conn: sqlite3.Connection, person, chat_id: int) -> int:
    """Puls xodimi javob berganda liniyasi: panelda belgilangani; bo'lmasa shu tizimning ish guruhida bo'lsa dasturchi
    (dasturlash bo'limi) yoki mutaxassis; boshqa xodim — mutaxassis."""
    if person["line"] in (1, 2, 3):
        return int(person["line"])
    team = conn.execute("SELECT 1 FROM chat_projects cp JOIN projects p ON p.id = cp.project_id JOIN members m ON m.chat_id = p.chat_id "
                        "WHERE cp.chat_id = ? AND m.user_id = ? AND m.left_at IS NULL LIMIT 1", (chat_id, person["id"])).fetchone()
    if team is not None:
        return 3 if (person["department"] or "") in DEV_DEPTS else 2
    return 2


def author(conn: sqlite3.Connection, chat_id: int, user_id: int, full_name: str, username: str | None, admin: bool,
           when: str) -> dict:
    """Puls xodimi (liniyasi bilan), yordam guruhi xodimi (operator) yoki tizim foydalanuvchisi."""
    from .ingest import clean_name
    pe = conn.execute("SELECT id, name, department, role, status, line, dm_chat_id FROM people WHERE id = ?", (user_id,)).fetchone()
    if pe is not None and pe["status"] != "begona" and (
            pe["status"] == "xodim" or pe["role"] == "rahbar" or pe["dm_chat_id"] or pe["line"]
            or (config.OWNER_ID and user_id == config.OWNER_ID) or _in_work_group(conn, user_id)):
        return {"staff": True, "name": pe["name"], "line": _staff_line(conn, pe, chat_id), "client_id": None, "auto": False}
    name = clean_name(full_name) or (username or str(user_id))
    if pe is None and config.OWNER_ID and user_id == config.OWNER_ID:  # panel egasi hali ish guruhiga yozmagan bo'lsa ham xodim
        return {"staff": True, "name": name, "line": 2, "client_id": None, "auto": False}
    cl = conn.execute("SELECT id, staff FROM clients WHERE source = 'tg' AND ext = ?", (str(user_id),)).fetchone()
    if cl is None:
        cur = conn.execute("INSERT INTO clients(source, ext, name, username, first_seen, staff) VALUES('tg', ?, ?, ?, ?, ?)",
                           (str(user_id), name, username, when, 1 if admin else None))
        cid, staff = cur.lastrowid, (1 if admin else None)
    else:
        cid, staff = cl["id"], cl["staff"]
        if admin and staff is None:
            staff = 1  # yordam guruhi admini — operator (rahbar panelda boshqacha belgilashi mumkin)
        conn.execute("UPDATE clients SET name = ?, username = ?, staff = ? WHERE id = ?", (name, username, staff, cid))
    return {"staff": bool(staff), "name": name, "line": int(staff) if staff else None, "client_id": cid, "auto": staff is None}


# ---------------------------------------------------------------- AI'siz qoida

TYPE_RULES = [
    ("mobile", r"ilova|prilojen|приложен|android|iphone|ios\b|play ?market|app ?store"),
    ("sms", r"\bsms\b|смс|kod kel|код не|kod yo.?q|kod xato"),
    ("payment", r"to.?lov|tolov|to.?la(dim|gan|nmagan)|oplat|оплат|пошлин|\bclick\b|payme|uzcard|humo|boj(i|ini)?\b|pul yechil|списал"),
    ("cert", r"guvohnoma|yuklab ol|qr ?kod|sertifikat|tayyor hujjat|скача|справк|свидетельств"),
    ("data", r"ma.?lumot\w* (noto.?g.?ri|xato)|familiya|pinfl|jshshir|tug.?ilgan|fish\b|ф\.?и\.?о|данные|manzil\w* noto|"
             r"ism\w* (xato|noto)|с ошибкой|ошибк\w* в (дат|фамил|имен)|boshqa odamning"),
    ("docs", r"yuklan\w*ma|yuklay olma|yuklab bo.?lma|fayl|pdf\b|\bmb\b|format|skaner|загруз|файл|imzo|подпис|skan\b|скан\b"),
    ("status", r"ariza\w*|holat\w*|ko.?rib chiq|muddat\w*|qachon|rad etil|qaytaril|javob yo.?q|kutyapman|статус|заявк|"
               r"заявлени|срок|нет ответа|ответа нет"),
    ("slow", r"sekin|ochilma|ochilmay|ishlamay|\b50[234]\b|server|qotib|osilib|медлен|не открыва|не работает|висит"),
    ("login", r"kir(a|o)?\s?olma|kirolma|kirish|kirmoqchi|kirib bo.?lma|login|parol|one ?id|avtoriz|kabinet|вход|войти|логин|"
              r"парол|кабинет"),
    ("howto", r"qanday|qanaqa|qayerda|qayerdan|qilsa bo.?ladi|yo.?riqnoma|kimga murojaat|qaysi hujjat|qancha turadi|narxi|"
              r"как\b|где\b|подскаж|какие документ|сколько стоит"),
]
THANKS_RE = re.compile(r"rahmat|raxmat|ishladi|ishlayapti|bo.?ldi|hal bo.?ldi|tushundim|спасибо|заработал|получилось", re.I)
STILL_RE = re.compile(r"hali ham|haliyam|baribir|yana (o.?sha|xato|ishlamay)|ishlamayapti|o.?zgarmadi|не работает|всё ещё|все еще|опять", re.I)
GREET_RE = re.compile(r"^\W*(assalomu?\s*alaykum|assalomu?\s*aleykum|salom|привет|здравствуйте|добрый день|xayrli (kun|tong)|"
                      r"hayrli (kun|tong))\W*$", re.I)
# yordamga aloqasi yo'q gap: reklama, havola, guruhdagi suhbat ("Admin bormi?", "Hayrli tong hammaga")
NOISE_RE = re.compile(r"t\.me/|https?://|chegirma|скидк|kvartira|квартир|sotiladi|sotaman|продаю|продает|kurslari|ob-havo|"
                      r"погод|hammaga|всем привет|admin bormi|bormisiz|кто-нибудь здесь|telefon raqam almash|guruhga qo.?sh", re.I)
CYR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k",
       "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
       "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o'", "қ": "q",
       "ғ": "g'", "ҳ": "h"}


def latin(text: str) -> str:
    """Kirill yozuvidagi o'zbekcha matn lotinchada (kalit so'z qoidalari ikkala yozuvni ham tanisin): "ариза" -> "ariza"."""
    return "".join(CYR.get(ch, ch) for ch in (text or "").lower())


def _rule_text(text: str) -> str:
    low = (text or "").lower()
    return "%s\n%s" % (low, latin(low)) if re.search(r"[а-яёўқғҳ]", low) else low
TPL_RE = re.compile(r"keyinroq|qayta urinib|keshni tozala|kesh\w* tozala|boshqa brauzer|kuting|ko.?rib chiqamiz|"
                    r"ko.?rib chiqilmoqda|murojaat qiling|qo.?ng.?iroq qiling|texnik ishlar|попробуйте позже|ожидайте", re.I)
ASK_RE = re.compile(r"yuboring|skrinshot|screenshot|raqamini|pinfl|jshshir|qaysi|ma.?lumot bering|пришлите|скрин|номер", re.I)
FIXED_RE = re.compile(r"tuzatildi|to.?g.?rilandi|hal qilindi|yangilandi|qayta yuborildi|o.?zgartirildi|bajarildi|tiklandi|"
                      r"qo.?shildi|ochib berildi|endi ishlay|исправлен|готово|обновлен", re.I)


def guess_type(text: str) -> str:
    low = _rule_text(text)
    for key, pat in TYPE_RULES:
        if re.search(pat, low):
            return key
    return "boshqa"


def guess_grade(text: str) -> tuple[str, bool, str]:
    """(baho, hal qildimi, izoh) — AI'siz taxmin."""
    t = text or ""
    if FIXED_RE.search(t):
        return "good", True, "Javobda muammo tuzatilgani aytilgan"
    if TPL_RE.search(t) and len(t) < 160:
        return "tpl", False, "Umumiy javob: aniq yechim yo'q"
    if ASK_RE.search(t):
        return "part", False, "Qo'shimcha ma'lumot so'ralgan, muammo hali hal bo'lmagan"
    return ("part", False, "Yo'nalish berilgan") if len(t) >= 40 else ("tpl", False, "Qisqa javob: aniq yechim ko'rinmaydi")


def short(text: str, n: int = 90) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# ---------------------------------------------------------------- AI

SUPPORT_PROMPT = """You read a Telegram support chat of Uzbek government information systems (Ministry of Justice). Users
(citizens, notaries, civil registry staff) write questions and complaints; support staff answer them. People write in Uzbek
(Latin or Cyrillic), Russian or mixed, with typos. Read the new message like an experienced support supervisor who follows
the chat, and return JSON.

act:
- "appeal": a user reports a new problem, asks a question or requests help with a system.
- "followup": the user adds details or asks again about their OWN open appeal listed below (put its id in appeal_ids).
  A different problem from the same user is a new "appeal".
- "answer": support staff (or someone who answers like support) replies to users' appeals. appeal_ids: the appeals it answers,
  the replied message's appeal first. One answer may cover several appeals.
- "confirm": after an answer, the user says the problem is solved or thanks ("ishladi", "bo'ldi rahmat", "заработало").
- "reopen": after an answer, the user says it still does not work.
- "none": greetings, chit-chat, staff talking among themselves, ads, thanks without an answered appeal.
system: only for "appeal": ONE key of the systems this chat serves, or null. Choose a system only when this message or this
author's own earlier messages name it, its service or its document (e.g. "guvohnoma", "apostil", "notarial", "litsenziya",
the app name). Other people's messages never decide this author's system. Never choose by the problem type: SMS codes,
login, payments and slowness happen in every system. When unsure: null.
{systems}
type: only for "appeal", one of: {types}
summary: only for "appeal": the problem in one short Uzbek (Latin) sentence a manager understands, at most 90 characters,
no greeting, no names.
grade: only for "answer", how well it handles the user's problem:
- "good": names the cause and gives a working solution, or says the problem was fixed or done for this user.
- "part": gives direction or asks for details needed (screenshot, application number, PINFL), but it is not solved yet.
- "tpl": boilerplate that does not address this specific problem ("keyinroq urinib ko'ring", "keshni tozalang", "kuting",
  "operatorga murojaat qiling").
solved: only for "answer": true when this answer itself resolves the problem (a fix was made, or the instruction clearly
solves it). note: only for "answer": why this grade, Uzbek (Latin), at most 110 characters.
Use only appeal ids listed below; leave appeal_ids empty when unsure.

Open and recent appeals in this chat (id | user | system | type | problem | status | last activity):
{open}
This author's appeals in the last 21 days (id | system | type | problem | status | date):
{mine}
Recent messages in this chat (time | who | text):
{chat}
{reply}
Author: {author} ({role})
Message:
\"\"\"{text}\"\"\"
"""

SUPPORT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "act": {"type": "STRING", "enum": ["appeal", "followup", "answer", "confirm", "reopen", "none"]},
        "appeal_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "system": {"type": "STRING", "nullable": True},
        "type": {"type": "STRING", "enum": list(TYPES)},
        "summary": {"type": "STRING"},
        "grade": {"type": "STRING", "enum": ["good", "part", "tpl"], "nullable": True},
        "solved": {"type": "BOOLEAN"},
        "note": {"type": "STRING"},
    },
    "required": ["act"],
}

BATCH_PROMPT = """You check support appeals that chatbots of Uzbek government information systems (Ministry of Justice)
received, with the answers users got. For each appeal return:
- type: one of {types}
- system: ONE key from the list below, only when the appeal names the system, its service or its document; never by the
  problem type alone (SMS, login, payment exist in every system); otherwise null.
{systems}
- summary: the problem in one short Uzbek (Latin) sentence, at most 90 characters.
- grades: one grade per answer, same order: "good" (cause + working solution, or says it was fixed), "part" (direction or
  asks for needed details, not solved yet), "tpl" (boilerplate not about this problem).
- solved: true when the answers resolve the problem.
- note: why the last answer got its grade, Uzbek (Latin), at most 110 characters.

Appeals (number | user's message | answers in order):
{items}

Return {{"results": [...]}}, one object per appeal, "i" = appeal number."""

BATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {"results": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "i": {"type": "INTEGER"}, "type": {"type": "STRING", "enum": list(TYPES)}, "system": {"type": "STRING", "nullable": True},
        "summary": {"type": "STRING"}, "grades": {"type": "ARRAY", "items": {"type": "STRING", "enum": ["good", "part", "tpl"]}},
        "solved": {"type": "BOOLEAN"}, "note": {"type": "STRING"}}, "required": ["i", "type", "summary"]}}},
    "required": ["results"],
}

INSIGHT_PROMPT = """Below are support appeals about the information system "{system}" of the Ministry of Justice of Uzbekistan,
type "{type}". These users wrote again about the same problem, so the first answers did not solve it. Each block is one user's
chain: their messages and the answers they got, in order.

{chains}

Return JSON in Uzbek (Latin), plain words a manager understands:
- cause: why people come back: what in the answers or in the system leaves the problem unsolved. At most 230 characters.
- act: one concrete recommendation for the head of the IT center. At most 210 characters.
Judge only from these texts. Do not invent numbers, names or facts that are not in them."""

INSIGHT_SCHEMA = {"type": "OBJECT", "properties": {"cause": {"type": "STRING"}, "act": {"type": "STRING"}},
                  "required": ["cause", "act"]}


def _who_role(conn: sqlite3.Connection, user_id: int | None) -> tuple[str, bool]:
    """Suhbat kontekstida xabar egasi: ismi va xodimmi (Puls xodimi yoki belgilangan operator)."""
    if user_id is None:
        return "-", False
    pe = conn.execute("SELECT name, status, role, dm_chat_id, line FROM people WHERE id = ?", (user_id,)).fetchone()
    if pe is not None and pe["status"] != "begona" and (pe["status"] == "xodim" or pe["role"] == "rahbar" or pe["dm_chat_id"]
                                                        or pe["line"] or _in_work_group(conn, user_id)):
        return pe["name"] or "-", True
    cl = conn.execute("SELECT name, staff FROM clients WHERE source = 'tg' AND ext = ?", (str(user_id),)).fetchone()
    if cl is not None:
        return cl["name"] or "-", bool(cl["staff"])
    return (pe["name"] if pe is not None else "-") or "-", False


def _context(conn: sqlite3.Connection, chat_id: int, when: str, me: dict, mid: int, parent, user_id: int | None = None) -> dict:
    """Xabarni tushunish uchun suhbat. Xodim javobi uchun — butun guruh (qaysi murojaatga javob bergani). Foydalanuvchi xabari
    uchun — faqat o'zining xabarlari va murojaatlari: boshqa odamning gapi uning tizimini yoki muammosini belgilamaydi
    (call-markaz, bot, pochtada yonma-yon yozilgan xabarlar umuman boshqa-boshqa odamlarniki)."""
    since3 = _ts(_dt(when) - timedelta(days=3))
    own = not me["staff"] and user_id is not None
    open_ = [dict(r) for r in conn.execute(
        "SELECT a.id, a.client_id, c.name AS client, p.name AS project, a.type, coalesce(a.summary, a.text) AS summary, a.status, "
        "a.last_at FROM appeals a LEFT JOIN clients c ON c.id = a.client_id LEFT JOIN projects p ON p.id = a.project_id "
        "WHERE a.chat_id = ? AND (a.status IN ('ochiq', 'javob', 'qayta') OR a.last_at >= ?)%s ORDER BY a.last_at DESC LIMIT 25"
        % (" AND a.client_id = ?" if own else ""), (chat_id, since3) + ((me.get("client_id"),) if own else ()))]
    mine = []
    if me.get("client_id"):
        mine = [dict(r) for r in conn.execute(
            "SELECT a.id, p.name AS project, a.type, coalesce(a.summary, a.text) AS summary, a.status, a.created_at FROM appeals a "
            "LEFT JOIN projects p ON p.id = a.project_id WHERE a.client_id = ? AND a.created_at >= ? ORDER BY a.created_at DESC LIMIT 10",
            (me["client_id"], _ts(_dt(when) - timedelta(days=REPEAT_DAYS))))]
    chat = []
    for r in reversed(conn.execute(
            "SELECT id, user_id, date, text FROM messages WHERE chat_id = ? AND date >= ? AND date <= ? AND id != ?%s "
            "ORDER BY date DESC, id DESC LIMIT 25" % (" AND user_id = ?" if own else ""),
            (chat_id, _ts(_dt(when) - timedelta(days=2)), when, mid) + ((user_id,) if own else ())).fetchall()):
        name, staff = _who_role(conn, r["user_id"])
        chat.append({"time": r["date"][5:16], "who": "%s [%s]" % (name, "xodim" if staff else "foydalanuvchi"),
                     "text": short(r["text"], 220)})
    reply = None
    if parent is not None:
        ids = [x["appeal_id"] for x in conn.execute("SELECT DISTINCT appeal_id FROM appeal_events WHERE msg = ?", (parent["id"],))]
        pname, pstaff = _who_role(conn, parent["user_id"])
        reply = {"who": "%s [%s]" % (pname, "xodim" if pstaff else "foydalanuvchi"), "text": short(parent["text"], 500), "ids": ids}
    return {"open": open_, "mine": mine, "chat": chat, "reply": reply}


def _ai_read(ctx: dict, systems: list[dict], me: dict, text: str) -> dict | None:
    if not config.appeals_ai_enabled():
        return None
    role = ("support staff, %s" % LINES.get(me["line"] or 1, "Operator").lower()) if me["staff"] else "user"
    prompt = SUPPORT_PROMPT.format(
        systems="\n".join("- %s: %s" % (p["key"], p["name"]) for p in systems) or "- (unknown)",
        types=", ".join("%s (%s)" % (k, v) for k, v in TYPES.items()),
        open="\n".join("- %d | %s | %s | %s | %s | %s | %s" % (a["id"], a["client"] or "-", a["project"] or "-", a["type"] or "-",
                                                             short(a["summary"], 120), a["status"], (a["last_at"] or "")[5:16])
                       for a in ctx["open"]) or "- (none)",
        mine="\n".join("- %d | %s | %s | %s | %s | %s" % (a["id"], a["project"] or "-", a["type"] or "-", short(a["summary"], 120),
                                                         a["status"], a["created_at"][:10]) for a in ctx["mine"]) or "- (none)",
        chat="\n".join("- %s | %s | %s" % (m["time"], m["who"], m["text"]) for m in ctx["chat"]) or "- (none)",
        reply=('This message is a reply to %s: """%s"""%s' % (ctx["reply"]["who"], ctx["reply"]["text"],
               " (appeal ids of that message: %s)" % ", ".join(map(str, ctx["reply"]["ids"])) if ctx["reply"]["ids"] else ""))
        if ctx["reply"] else "",
        author=me["name"], role=role, text=(text or "")[:2500])
    return ai.ask_appeals(prompt, SUPPORT_SCHEMA, 1, 300)


def _rule_read(conn: sqlite3.Connection, ctx: dict, me: dict, text: str, when: str) -> dict:
    """AI'siz: kim yozgani, nimaga javob bergani va kalit so'zlar bo'yicha."""
    t = (text or "").strip()
    reply_ids = ctx["reply"]["ids"] if ctx["reply"] else []
    if me["staff"]:
        if not t or GREET_RE.match(t):
            return {"act": "none"}
        ids = list(reply_ids)
        if not ids:
            fresh = _ts(_dt(when) - timedelta(hours=6))
            ids = [a["id"] for a in ctx["open"] if a["status"] in ("ochiq", "qayta") and (a["last_at"] or "") >= fresh][:1]
        if not ids:
            return {"act": "none"}
        g, solved, note = guess_grade(t)
        return {"act": "answer", "appeal_ids": ids, "grade": g, "solved": solved, "note": note}
    mine_open = [a for a in ctx["mine"] if a["status"] in OPEN]
    answered = [a for a in ctx["mine"] if a["status"] in ("javob", "hal")]
    rt = _rule_text(t)
    if THANKS_RE.search(rt) and len(t) < 120 and answered:
        return {"act": "confirm", "appeal_ids": [answered[0]["id"]]}
    if STILL_RE.search(rt) and answered:
        return {"act": "reopen", "appeal_ids": [answered[0]["id"]]}
    if not t or GREET_RE.match(t) or GREET_RE.match(latin(t)) or (len(t) < 8 and "?" not in t):
        return {"act": "none"}
    if guess_type(t) == "boshqa" and (NOISE_RE.search(rt) or (THANKS_RE.search(rt) and len(t) < 60)):
        return {"act": "none"}  # reklama, guruhdagi suhbat, javobsiz "rahmat" — murojaat emas
    if mine_open:
        last = conn.execute("SELECT max(at) FROM appeal_events WHERE appeal_id = ?", (mine_open[0]["id"],)).fetchone()[0]
        staff_after = conn.execute("SELECT 1 FROM appeal_events WHERE appeal_id = ? AND staff = 1 LIMIT 1", (mine_open[0]["id"],)).fetchone()
        if last and _hours(last, when) * 60 <= FOLLOW_MIN and staff_after is None:
            return {"act": "followup", "appeal_ids": [mine_open[0]["id"]]}
    return {"act": "appeal", "type": guess_type(t), "summary": short(t, 90)}


# ---------------------------------------------------------------- yozish

def _repeat_of(conn: sqlite3.Connection, client_id: int | None, project_id: int | None, typ: str, when: str):
    if not client_id or not project_id or typ == "boshqa":
        return None
    return conn.execute("SELECT id, chain FROM appeals WHERE client_id = ? AND project_id = ? AND type = ? AND created_at >= ? "
                        "AND created_at < ? ORDER BY created_at DESC LIMIT 1",
                        (client_id, project_id, typ, _ts(_dt(when) - timedelta(days=REPEAT_DAYS)), when)).fetchone()


def new_appeal(conn: sqlite3.Connection, *, source: str, project_id: int | None, client_id: int | None, text: str,
               when: str, typ: str, summary: str | None, chat_id: int | None = None, msg: int | None = None,
               source_id: int | None = None, ext_id: str | None = None, how: str | None = "qoida", who: str | None = None) -> int:
    typ = typ if typ in TYPES else "boshqa"
    prev = _repeat_of(conn, client_id, project_id, typ, when)
    chain = (prev["chain"] or prev["id"]) if prev is not None else None
    cur = conn.execute(
        "INSERT INTO appeals(source, source_id, chat_id, ext_id, project_id, client_id, msg, text, summary, type, created_at, "
        "status, chain, rep, last_at, ai) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ochiq', ?, ?, ?, ?)",
        (source, source_id, chat_id, ext_id, project_id, client_id, msg, (text or "")[:4000], (summary or short(text, 90))[:160],
         typ, when, chain, 1 if prev is not None else 0, when, how))
    aid = cur.lastrowid
    if prev is not None and not prev["chain"]:
        conn.execute("UPDATE appeals SET chain = ? WHERE id = ?", (prev["id"], prev["id"]))
    conn.execute("INSERT INTO appeal_events(appeal_id, at, kind, who, staff, text, msg) VALUES(?, ?, 'murojaat', ?, 0, ?, ?)",
                 (aid, when, who, (text or "")[:4000], msg))
    return aid


def add_answer(conn: sqlite3.Connection, aid: int, when: str, who: str, line: int, grade: str, solved: bool, note: str | None,
               text: str, msg: int | None = None) -> None:
    grade = grade if grade in ("good", "part", "tpl") else "part"
    a = conn.execute("SELECT status, first_answer_at FROM appeals WHERE id = ?", (aid,)).fetchone()
    if a is None:
        return
    conn.execute("INSERT INTO appeal_events(appeal_id, at, kind, who, staff, line, grade, note, text, msg) "
                 "VALUES(?, ?, 'javob', ?, 1, ?, ?, ?, ?, ?)", (aid, when, who, line, grade, (note or "")[:200], (text or "")[:4000], msg))
    sets = ["answered_by = ?", "line = ?", "grade = ?", "grade_note = ?", "last_at = ?"]
    args: list = [who, line, grade, (note or "")[:200], when]
    if not a["first_answer_at"]:
        sets += ["first_answer_at = ?", "first_grade = ?"]
        args += [when, grade]
    if solved:
        sets += ["status = 'hal'", "resolved_at = ?", "resolved_by = ?", "resolution = 'javob'"]
        args += [when, who]
    elif a["status"] in ("ochiq", "qayta"):
        sets.append("status = 'javob'")
    conn.execute("UPDATE appeals SET %s WHERE id = ?" % ", ".join(sets), args + [aid])


def _client_event(conn: sqlite3.Connection, aid: int, kind: str, when: str, who: str, text: str, msg: int | None) -> None:
    conn.execute("INSERT INTO appeal_events(appeal_id, at, kind, who, staff, text, msg) VALUES(?, ?, ?, ?, 0, ?, ?)",
                 (aid, when, kind, who, (text or "")[:4000], msg))
    a = conn.execute("SELECT status FROM appeals WHERE id = ?", (aid,)).fetchone()
    if kind == "tasdiq" and a["status"] != "hal":
        last = conn.execute("SELECT at, who FROM appeal_events WHERE appeal_id = ? AND kind = 'javob' ORDER BY at DESC, id DESC LIMIT 1",
                            (aid,)).fetchone()
        conn.execute("UPDATE appeals SET status = 'hal', resolved_at = ?, resolved_by = ?, resolution = 'tasdiq', last_at = ? WHERE id = ?",
                     (last["at"] if last else when, last["who"] if last else None, when, aid))
    elif kind == "qayta" or (kind == "qoshimcha" and a["status"] == "hal"):
        conn.execute("UPDATE appeals SET status = 'qayta', resolved_at = NULL, resolved_by = NULL, resolution = NULL, last_at = ? "
                     "WHERE id = ?", (when, aid))
    else:
        conn.execute("UPDATE appeals SET last_at = ? WHERE id = ?", (when, aid))


def handle(conn: sqlite3.Connection, inc, use_ai: bool = True):
    """Yordam guruhidagi bitta xabar (bot ham, Telegram akkaunt ham, tarix importi ham shu yo'ldan). Bot guruhda hech
    qachon gapirmaydi va reaksiya qo'ymaydi: natija "skipped"."""
    from .ingest import Result
    when = inc.date.strftime(FMT)
    existing = conn.execute("SELECT id, text FROM messages WHERE chat_id = ? AND msg_id = ?", (inc.chat_id, inc.msg_id)).fetchone()
    if existing and not inc.edited:
        return Result("none", "yordam", duplicate=True)
    conn.execute("INSERT INTO chats(id, title, demo, added_at, kind) VALUES(?, ?, 0, ?, 'yordam') "
                 "ON CONFLICT(id) DO UPDATE SET title = excluded.title", (inc.chat_id, inc.chat_title, when))
    if existing:  # tahrirlandi: matn va tarix yangilanadi, murojaat qayta tasniflanmaydi
        if (existing["text"] or "") != (inc.text or ""):
            stamp = _now()
            conn.execute("INSERT INTO message_edits(message_id, at, kind, old_text, new_text) VALUES(?, ?, 'edit', ?, ?)",
                         (existing["id"], stamp, existing["text"], inc.text))
            conn.execute("UPDATE messages SET text = ?, edited_at = ? WHERE id = ?", (inc.text, stamp, existing["id"]))
            conn.execute("UPDATE appeal_events SET text = ? WHERE msg = ?", ((inc.text or "")[:4000], existing["id"]))
            conn.execute("UPDATE appeals SET text = ? WHERE msg = ?", ((inc.text or "")[:4000], existing["id"]))
            db.bump_version(conn)
        return Result("none", "yordam", skipped=True)
    if inc.media and use_ai and config.APPEALS_AI == "gemini":  # lokal rejimda ovoz tashqi xizmatga yuborilmaydi
        heard = ai.transcribe(inc.media, inc.mime or "application/octet-stream", inc.text)
        if heard:
            label = "Rasm" if (inc.mime or "").startswith("image/") else "Ovozli xabar"
            inc.text = "%s: %s%s" % (label, heard, "\n" + inc.text if inc.text and inc.text not in heard else "")
    if inc.media and not (inc.text or "").strip():
        inc.text = "[Rasm]" if (inc.mime or "").startswith("image/") else "[Ovozli xabar]"
    cur = conn.execute("INSERT INTO messages(chat_id, msg_id, user_id, date, text, kind, project_id, source, reply_to) "
                       "VALUES(?, ?, ?, ?, ?, 'none', NULL, 'yordam', ?)",
                       (inc.chat_id, inc.msg_id, inc.user_id, when, inc.text, inc.reply_to))
    _process(conn, inc, cur.lastrowid, when, use_ai)
    db.bump_version(conn)
    return Result("none", "yordam", skipped=True)


def _process(conn: sqlite3.Connection, inc, mid: int, when: str, use_ai: bool) -> None:
    """Saqlangan xabarni tushunib murojaatlarga yozadi (jonli xabar ham, qayta o'qish ham)."""
    me = author(conn, inc.chat_id, inc.user_id, inc.user_name, inc.username, inc.admin, when)
    parent = conn.execute("SELECT id, user_id, text FROM messages WHERE chat_id = ? AND msg_id = ?",
                          (inc.chat_id, inc.reply_to)).fetchone() if inc.reply_to else None
    systems = chat_projects(conn, inc.chat_id) or [support_project(conn, inc.chat_id, inc.chat_title, when)]
    ctx = _context(conn, inc.chat_id, when, me, mid, parent, inc.user_id)
    raw = _ai_read(ctx, systems, me, inc.text) if use_ai else None
    how = "ai" if raw else "qoida"
    act = raw or _rule_read(conn, ctx, me, inc.text, when)
    _apply(conn, act, how, ctx, systems, me, inc, when, mid)


def reread(chat_id: int, days: int = 30) -> int:
    """Ish guruhi yordam guruhiga aylantirildi: oxirgi kunlardagi xabarlari murojaat sifatida qayta o'qiladi (fonda, AI bilan).
    Allaqachon murojaatga yozilgan xabar qayta o'qilmaydi."""
    from types import SimpleNamespace
    since = _ts(config.now() - timedelta(days=days))
    with db.session() as conn:
        title = (conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone() or {"title": ""})["title"]
        rows = [dict(r) for r in conn.execute(
            "SELECT m.id, m.msg_id, m.user_id, m.date, m.text, m.reply_to, coalesce(pe.tg_name, pe.name, cl.name) AS name, "
            "coalesce(pe.username, cl.username) AS username FROM messages m LEFT JOIN people pe ON pe.id = m.user_id "
            "LEFT JOIN clients cl ON cl.source = 'tg' AND cl.ext = CAST(m.user_id AS TEXT) "
            "WHERE m.chat_id = ? AND m.date >= ? AND m.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM appeal_events e WHERE e.msg = m.id) "
            "ORDER BY m.date, m.id", (chat_id, since))]
    n = 0
    for r in rows:
        if not (r["text"] or "").strip():
            continue
        inc = SimpleNamespace(chat_id=chat_id, chat_title=title or "", msg_id=r["msg_id"], user_id=r["user_id"],
                              user_name=r["name"] or str(r["user_id"]), username=r["username"], admin=False, text=r["text"],
                              reply_to=r["reply_to"])
        try:
            with db.session() as conn:
                conn.execute("UPDATE messages SET source = 'yordam', kind = 'none', project_id = NULL WHERE id = ?", (r["id"],))
                _process(conn, inc, r["id"], r["date"], True)
                db.bump_version(conn)
            n += 1
        except Exception:  # noqa: BLE001 — bitta xabar xatosi qolganlarini to'xtatmasin
            log.exception("murojaat qayta o'qilmadi: %s", r["id"])
    return n


def _apply(conn, act: dict, how: str, ctx: dict, systems: list[dict], me: dict, inc, when: str, mid: int) -> None:
    kind = act.get("act") or "none"
    known = {a["id"]: a for a in ctx["open"]} | {a["id"]: a for a in ctx["mine"]}
    reply_ids = ctx["reply"]["ids"] if ctx["reply"] else []
    ids = [i for i in act.get("appeal_ids") or [] if isinstance(i, int) and (i in known or i in reply_ids)]
    if kind == "answer" and not me["staff"] and me.get("client_id") and me.get("auto"):
        # ro'yxatda yo'q odam foydalanuvchilarga support kabi javob beryapti: operator deb belgilanadi (rahbar tuzatishi mumkin)
        conn.execute("UPDATE clients SET staff = 1 WHERE id = ? AND staff IS NULL", (me["client_id"],))
        me = {**me, "staff": True, "line": 1}
        # model unga foydalanuvchi sifatida faqat o'z murojaatlarini ko'rsatgan edi: javob qaysi murojaatga — butun guruhdan
        ctx = {**ctx, "open": _context(conn, inc.chat_id, when, me, mid, None)["open"]}
        ids = [i for i in act.get("appeal_ids") or [] if isinstance(i, int) and i in {a["id"] for a in ctx["open"]}]
    if me["staff"]:
        if kind != "answer":
            return
        if not ids:
            ids = list(reply_ids) or [a["id"] for a in ctx["open"] if a["status"] in ("ochiq", "qayta")][:1]
        for aid in dict.fromkeys(ids):
            add_answer(conn, aid, when, me["name"], me["line"] or 1, act.get("grade") or "part", bool(act.get("solved")),
                       act.get("note"), inc.text, mid)
        return
    own = [i for i in ids if (known.get(i) or {}).get("client_id", me["client_id"]) == me["client_id"]
           or i in {a["id"] for a in ctx["mine"]}]
    if kind in ("followup", "confirm", "reopen"):
        target = own[0] if own else next((a["id"] for a in ctx["mine"] if a["status"] in (OPEN if kind == "followup" else ("javob", "hal", "qayta"))), None)
        if target is None:
            if kind != "followup":
                return
            kind = "appeal"
        else:
            _client_event(conn, target, {"followup": "qoshimcha", "confirm": "tasdiq", "reopen": "qayta"}[kind], when, me["name"],
                          inc.text, mid)
            return
    if kind != "appeal":
        return
    pid = pick_system(systems, act.get("system") if how == "ai" else None, inc.text)
    typ = act.get("type") if act.get("type") in TYPES else guess_type(inc.text)
    new_appeal(conn, source="tg", project_id=pid, client_id=me["client_id"], text=inc.text, when=when, typ=typ,
               summary=(act.get("summary") or "").strip() or short(inc.text, 90), chat_id=inc.chat_id, msg=mid, how=how,
               who=me["name"])


# ---------------------------------------------------------------- chatbotlar (API)

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_source(conn: sqlite3.Connection, name: str, project_id: int | None, by: str) -> dict:
    name = " ".join((name or "").split())[:80]
    if len(name) < 2:
        raise ValueError("Chatbot nomini yozing")
    if project_id and not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
        raise ValueError("Loyiha topilmadi")
    token = "pm_" + secrets.token_urlsafe(24)
    cur = conn.execute("INSERT INTO appeal_sources(name, project_id, token_hash, created_at, created_by, active) VALUES(?, ?, ?, ?, ?, 1)",
                       (name, project_id or None, _hash(token), _now(), by))
    db.bump_version(conn)
    return {"id": cur.lastrowid, "name": name, "token": token}


def reset_source(conn: sqlite3.Connection, sid: int) -> dict:
    token = "pm_" + secrets.token_urlsafe(24)
    if not conn.execute("UPDATE appeal_sources SET token_hash = ? WHERE id = ?", (_hash(token), sid)).rowcount:
        raise ValueError("Manba topilmadi")
    return {"id": sid, "token": token}


def source_by_token(conn: sqlite3.Connection, token: str | None):
    if not token:
        return None
    return conn.execute("SELECT * FROM appeal_sources WHERE token_hash = ? AND active = 1", (_hash(token.strip()),)).fetchone()


def sources(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT s.id, s.name, s.project_id, p.name AS project, s.created_at, s.created_by, s.last_at, s.active, "
                          "(SELECT count(*) FROM appeals a WHERE a.source_id = s.id) AS n FROM appeal_sources s "
                          "LEFT JOIN projects p ON p.id = s.project_id ORDER BY s.id"):
        out.append(dict(r))
    return out


def _project_by_hint(conn: sqlite3.Connection, hint, when: str) -> int | None:
    if hint in (None, ""):
        return None
    if isinstance(hint, int) or str(hint).isdigit():
        r = conn.execute("SELECT id FROM projects WHERE id = ?", (int(hint),)).fetchone()
        if r is not None:
            return r["id"]
    p = find_project(conn, str(hint))
    if p is not None:
        return p["id"]
    from .parser import norm_key
    name = " ".join(str(hint).split())[:80]
    key = norm_key(name)
    if not key:
        return None
    if conn.execute("SELECT 1 FROM projects WHERE key = ?", (key,)).fetchone():
        key = "%s-bot" % key
    conn.execute("INSERT INTO projects(key, name, chat_id, created_at, yordam) VALUES(?, ?, NULL, ?, 1)", (key, name, when))
    return conn.execute("SELECT id FROM projects WHERE key = ?", (key,)).fetchone()["id"]


def _when(value) -> str:
    """ISO vaqt (zona bilan yoki zonasiz) -> Toshkent vaqti matni."""
    s = str(value or "").strip().replace("T", " ").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError("vaqt ISO ko'rinishida bo'lsin: 2026-10-26T10:15:00+05:00")
    if dt.tzinfo is not None:
        dt = dt.astimezone(config.TZ).replace(tzinfo=None)
    return dt.strftime(FMT)


def push(conn: sqlite3.Connection, src, items: list[dict]) -> dict:
    """Chatbot murojaatlari: bir xil "id" qayta kelsa o'sha murojaat yangilanadi (javoblar va holat). Tasniflash va baholash
    fonda (AI); AI o'chiq bo'lsa darhol kalit so'zlar bo'yicha."""
    if not isinstance(items, list) or not items:
        raise ValueError("items: kamida bitta murojaat")
    if len(items) > 500:
        raise ValueError("Bir so'rovda ko'pi bilan 500 ta murojaat")
    added = updated = 0
    errors = []
    for n, it in enumerate(items):
        try:
            if not isinstance(it, dict):
                raise ValueError("murojaat obyekt bo'lsin")
            ext = str(it.get("id") or "").strip()[:100]
            text = str(it.get("text") or "").strip()
            if not ext or not text:
                raise ValueError("id va text majburiy")
            when = _when(it.get("at"))
            user = str(it.get("user") or ("anon:" + ext))[:100]
            source_key = "src:%d" % src["id"]
            cl = conn.execute("SELECT id FROM clients WHERE source = ? AND ext = ?", (source_key, user)).fetchone()
            if cl is None:
                cid = conn.execute("INSERT INTO clients(source, ext, name, first_seen, staff) VALUES(?, ?, ?, ?, 0)",
                                   (source_key, user, str(it.get("user_name") or "")[:80] or None, when)).lastrowid
            else:
                cid = cl["id"]
            pid = _project_by_hint(conn, it.get("system"), when) or src["project_id"]
            typ = it.get("type") if it.get("type") in TYPES else None
            row = conn.execute("SELECT id FROM appeals WHERE source_id = ? AND ext_id = ?", (src["id"], ext)).fetchone()
            if row is None:
                aid = new_appeal(conn, source="bot", project_id=pid, client_id=cid, text=text, when=when,
                                 typ=typ or guess_type(text), summary=None, source_id=src["id"], ext_id=ext,
                                 how=None if config.appeals_ai_enabled() and typ is None else "qoida")
                added += 1
            else:
                aid = row["id"]
                conn.execute("UPDATE appeals SET text = ?, project_id = coalesce(?, project_id) WHERE id = ?", (text[:4000], pid, aid))
                conn.execute("DELETE FROM appeal_events WHERE appeal_id = ? AND kind != 'tuzatish'", (aid,))
                conn.execute("INSERT INTO appeal_events(appeal_id, at, kind, who, staff, text) VALUES(?, ?, 'murojaat', NULL, 0, ?)",
                             (aid, when, text[:4000]))
                conn.execute("UPDATE appeals SET status = 'ochiq', first_answer_at = NULL, first_grade = NULL, answered_by = NULL, "
                             "line = NULL, grade = NULL, resolved_at = NULL, resolved_by = NULL, resolution = NULL, last_at = ? "
                             "WHERE id = ?", (when, aid))
                if config.appeals_ai_enabled() and typ is None:
                    conn.execute("UPDATE appeals SET ai = NULL WHERE id = ? AND coalesce(ai, '') != 'qolda'", (aid,))
                updated += 1
            pending = config.appeals_ai_enabled() and typ is None
            for ans in it.get("answers") or []:
                if not isinstance(ans, dict) or not str(ans.get("text") or "").strip():
                    continue
                at = _when(ans.get("at") or it.get("at"))
                line = 0 if ans.get("bot") else (int(ans["line"]) if str(ans.get("line", "")).isdigit() and 0 <= int(ans["line"]) <= 3 else 1)
                g, solved, note = guess_grade(str(ans["text"]))
                add_answer(conn, aid, at, str(ans.get("by") or (LINES[line] if line == 0 else "Operator"))[:80], line,
                           g, solved and not pending, note, str(ans["text"]), None)
            if str(it.get("status") or "") == "hal":
                res_at = _when(it.get("resolved_at")) if it.get("resolved_at") else (
                    conn.execute("SELECT max(at) FROM appeal_events WHERE appeal_id = ? AND kind = 'javob'", (aid,)).fetchone()[0] or when)
                conn.execute("UPDATE appeals SET status = 'hal', resolved_at = ?, resolution = coalesce(resolution, 'tasdiq') WHERE id = ?",
                             (res_at, aid))
        except (ValueError, TypeError) as e:
            errors.append({"i": n, "id": (it or {}).get("id") if isinstance(it, dict) else None, "error": str(e)})
    conn.execute("UPDATE appeal_sources SET last_at = ? WHERE id = ?", (_now(), src["id"]))
    db.bump_version(conn)
    return {"added": added, "updated": updated, "errors": errors}


# ---------------------------------------------------------------- xabarlar oqimi (boshqa tizim bazasidan)

# yozgan odam nomidagi lavozim: "Operator Nigora", "Texnik yordam | Aziz", "Mutaxassis Bekzod" — xodim va uning liniyasi
STAFF_NAME_RE = re.compile(r"^\s*(?:(mutaxassis|специалист|dasturchi|разработчик)|operator|оператор|support|texnik yordam|"
                           r"техподдержка|admin|администратор|moderator|модератор)\b", re.I)
STREAM_KEYS = {"id": ("id",), "at": ("vaqt", "at", "date", "time"), "kind": ("manba", "source"),
               "channel": ("manba_nomi", "channel", "chat"), "who": ("kimdan", "from", "user_name", "user"),
               "text": ("matn", "text", "message"), "files": ("ilovalar", "attachments"),
               "reply": ("javob_berilgan_xabar", "reply_to"), "subject": ("mavzu", "subject")}
FILE_LABEL = {"photo": "[Rasm]", "document": "[Hujjat]", "voice": "[Ovozli xabar]", "video": "[Video]"}


def _field(it: dict, key: str):
    return next((it[k] for k in STREAM_KEYS[key] if it.get(k) not in (None, "")), None)


def _stable(*parts: str) -> int:
    return int(hashlib.sha1("|".join(parts).encode()).hexdigest()[:9], 16)


def stream_chat_id(channel: str) -> int:
    """Faylga kelgan kanal (guruh, bot, call-markaz, pochta) uchun doimiy ichki raqam; Telegram raqamlari bilan to'qnashmaydi."""
    return -(3 * 10 ** 13 + _stable("kanal", channel))


def import_stream(conn: sqlite3.Connection, items: list[dict], use_ai: bool = False, systems: dict | None = None,
                  commit_each: bool = False) -> dict:
    """Boshqa tizimlar bazasidan olingan xabarlar oqimi (yordam guruhlari, chatbotlar, call-markaz, pochta, sayt formasi):
    har xabar yordam guruhidagi xabar kabi o'qiladi — yangi murojaat, qo'shimcha, xodim javobi, tasdiq yoki boshqa gap.
    Kanal = yordam guruhi; yozgan odam kanal ichida nomi bilan aniqlanadi; nomida lavozimi bo'lsa ("Operator Nigora") —
    xodim. systems: {kanal nomi: [tizim nomlari]} — kanal qaysi tizimlarga xizmat qiladi (bo'lmasa nomidan).
    commit_each: har xabar alohida saqlanadi (uzoq AI importi: panelda asta-sekin ko'rinadi, kanallar parallel yuklanadi)."""
    from types import SimpleNamespace
    added = skipped = 0
    errors = []
    chats: dict[str, int] = {}
    known: dict[tuple[int, str], int] = {}
    rows = []
    for n, it in enumerate(items):
        if not isinstance(it, dict):
            errors.append({"i": n, "error": "xabar obyekt bo'lsin"})
            continue
        try:
            rows.append((_when(_field(it, "at")), n, it))
        except ValueError as e:
            errors.append({"i": n, "id": it.get("id"), "error": str(e)})
    rows.sort(key=lambda r: (r[0], r[1]))
    for when, n, it in rows:
        channel = " ".join(str(_field(it, "channel") or _field(it, "kind") or "Fayl").split())[:120]
        cid = chats.get(channel)
        if cid is None:
            cid = chats[channel] = stream_chat_id(channel)
            conn.execute("INSERT INTO chats(id, title, demo, added_at, kind) VALUES(?, ?, 0, ?, 'yordam') "
                         "ON CONFLICT(id) DO UPDATE SET title = excluded.title, kind = 'yordam'", (cid, channel, when))
            want = (systems or {}).get(channel)
            if want and not chat_projects(conn, cid):
                for name in want:
                    p = find_project(conn, name) or {"id": _project_by_hint(conn, name, when)}
                    conn.execute("INSERT INTO chat_projects(chat_id, project_id) VALUES(?, ?) ON CONFLICT DO NOTHING", (cid, p["id"]))
            if commit_each:
                conn.commit()  # kanal va uning tizimlari birinchi xabar xatosi bilan birga bekor bo'lib ketmasin
        who = " ".join(str(_field(it, "who") or "Noma'lum").split())[:80]
        uid = 10 ** 12 + _stable("odam", channel, who)
        m = STAFF_NAME_RE.match(who)
        if m:
            line = 2 if m.group(1) else 1
            conn.execute("INSERT INTO clients(source, ext, name, first_seen, staff) VALUES('tg', ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                         (str(uid), who, when, line))
        text = str(_field(it, "text") or "").strip()
        subject = str(_field(it, "subject") or "").strip()
        if subject and subject.lower() not in ("(mavzusiz)", "(без темы)", "(no subject)") and subject.lower() not in text.lower():
            text = "%s\n%s" % (subject, text) if text else subject
        if not text:
            kinds = [str((f or {}).get("type") or "") for f in _field(it, "files") or [] if isinstance(f, dict)]
            text = " ".join(FILE_LABEL[k] for k in kinds if k in FILE_LABEL)
        ext = str(it.get("id") or n)
        msg_id = int(re.sub(r"\D", "", ext)[-12:] or n + 1)
        if not text:
            conn.execute("INSERT INTO messages(chat_id, msg_id, user_id, date, text, kind, project_id, source) "
                         "VALUES(?, ?, ?, ?, '', 'none', NULL, 'yordam') ON CONFLICT DO NOTHING", (cid, msg_id, uid, when))
            skipped += 1
            continue
        ref = _field(it, "reply")
        # havola faqat shu kanaldagi xabar id'siga aynan mos kelsa olinadi: boshqa raqamlashdagi (masalan Telegram ichki
        # raqami) havolani raqami o'xshash boshqa xabarga ulash xato javob bog'lashga olib keladi
        reply = known.get((cid, str(ref))) if ref is not None else None
        known[(cid, ext)] = msg_id
        inc = SimpleNamespace(chat_id=cid, chat_title=channel, msg_id=msg_id, user_id=uid, user_name=who, username=None,
                              admin=False, text=text, reply_to=reply, date=_dt(when), edited=False, media=None, mime=None)
        try:
            r = handle(conn, inc, use_ai)
            if r.duplicate:
                skipped += 1
            else:
                added += 1
            if commit_each:
                conn.commit()
        except Exception as e:  # noqa: BLE001 — bitta xabar xatosi qolganlarini to'xtatmasin
            log.exception("oqim xabari o'qilmadi: %s", ext)
            errors.append({"i": n, "id": ext, "error": str(e)[:200]})
            if commit_each:
                conn.rollback()
    db.bump_version(conn)
    return {"added": added, "skipped": skipped, "errors": errors, "channels": len(chats)}


# ---------------------------------------------------------------- fon ishchisi

def auto_close(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Javob berilgan, foydalanuvchi SILENT_HOURS davomida qaytib yozmagan murojaat yopiladi (hal qilingan vaqti — oxirgi
    javob vaqti; baho o'zgarmaydi: shablon javobdan keyin jim qolgan ham "yomon javob" bo'lib ko'rinadi)."""
    now = now or config.now()
    edge = _ts(now - timedelta(hours=SILENT_HOURS))
    n = 0
    for a in conn.execute("SELECT a.id, (SELECT max(at) FROM appeal_events e WHERE e.appeal_id = a.id AND e.kind = 'javob') AS ans, "
                          "(SELECT max(at) FROM appeal_events e WHERE e.appeal_id = a.id AND e.staff = 0) AS cli "
                          "FROM appeals a WHERE a.status = 'javob'").fetchall():
        if a["ans"] and a["ans"] <= edge and (not a["cli"] or a["cli"] <= a["ans"]):
            who = conn.execute("SELECT who FROM appeal_events WHERE appeal_id = ? AND kind = 'javob' ORDER BY at DESC, id DESC LIMIT 1",
                               (a["id"],)).fetchone()
            conn.execute("UPDATE appeals SET status = 'hal', resolved_at = ?, resolved_by = ?, resolution = 'jim' WHERE id = ?",
                         (a["ans"], who["who"] if who else None, a["id"]))
            n += 1
    if n:
        db.bump_version(conn)
    return n


def classify_pending(conn: sqlite3.Connection, limit: int = 40) -> int:
    """Chatbotdan kelgan, hali o'qilmagan murojaatlar: AI turini, tizimini, qisqa mazmunini va javoblar bahosini beradi."""
    if config.APPEALS_AI == "local":
        limit = min(limit, 6)  # protsessorda sekin: kichik bo'laklar
    rows = [dict(r) for r in conn.execute("SELECT id, text, project_id, source_id FROM appeals WHERE ai IS NULL ORDER BY id LIMIT ?",
                                          (limit,))]
    if not rows:
        return 0
    projects = [dict(r) for r in conn.execute("SELECT id, key, name FROM projects ORDER BY name")]
    keys = {p["key"]: p["id"] for p in projects}
    answers = defaultdict(list)
    marks = ",".join("?" * len(rows))
    for e in conn.execute("SELECT id, appeal_id, text FROM appeal_events WHERE kind = 'javob' AND appeal_id IN (%s) ORDER BY at, id" % marks,
                          [r["id"] for r in rows]):
        answers[e["appeal_id"]].append(dict(e))
    raw = None
    if config.appeals_ai_enabled():
        body = "\n".join("%d | %s | %s" % (n + 1, short(r["text"], 600), " || ".join(short(x["text"], 300) for x in answers[r["id"]]) or "(no answer)")
                         for n, r in enumerate(rows))
        raw = ai.ask_appeals(BATCH_PROMPT.format(types=", ".join("%s (%s)" % (k, v) for k, v in TYPES.items()),
                                          systems="\n".join("- %s: %s" % (p["key"], p["name"]) for p in projects) or "- (none)",
                                          items=body), BATCH_SCHEMA, 2, 220 * len(rows) + 100)
    got = {}
    for res in (raw or {}).get("results") or []:
        if isinstance(res.get("i"), int) and 1 <= res["i"] <= len(rows):
            got[res["i"] - 1] = res
    n = 0
    for i, r in enumerate(rows):
        res = got.get(i)
        if res is None and config.appeals_ai_enabled() and raw is None:
            continue  # model ishlamadi: keyingi safar qayta uriniladi
        typ = res.get("type") if res and res.get("type") in TYPES else guess_type(r["text"])
        pid = r["project_id"] or (keys.get(res.get("system")) if res else None)
        summ = (res.get("summary") or "").strip()[:160] if res else short(r["text"], 90)
        prev_type = conn.execute("SELECT type, client_id, created_at FROM appeals WHERE id = ?", (r["id"],)).fetchone()
        conn.execute("UPDATE appeals SET type = ?, project_id = ?, summary = ?, ai = ? WHERE id = ?",
                     (typ, pid, summ or short(r["text"], 90), "ai" if res else "qoida", r["id"]))
        if prev_type["type"] != typ or not r["project_id"]:
            prev = _repeat_of(conn, prev_type["client_id"], pid, typ, prev_type["created_at"])
            conn.execute("UPDATE appeals SET rep = ?, chain = ? WHERE id = ?",
                         (1 if prev is not None else 0, (prev["chain"] or prev["id"]) if prev is not None else None, r["id"]))
        grades = (res or {}).get("grades") or []
        evs = answers[r["id"]]
        for j, e in enumerate(evs):
            g = grades[j] if j < len(grades) and grades[j] in ("good", "part", "tpl") else guess_grade(e["text"])[0]
            conn.execute("UPDATE appeal_events SET grade = ?, note = ? WHERE id = ?",
                         (g, ((res or {}).get("note") or "")[:200] if j == len(evs) - 1 else None, e["id"]))
        if evs:
            first_g = conn.execute("SELECT grade FROM appeal_events WHERE id = ?", (evs[0]["id"],)).fetchone()["grade"]
            last = conn.execute("SELECT at, who, grade, note FROM appeal_events WHERE id = ?", (evs[-1]["id"],)).fetchone()
            conn.execute("UPDATE appeals SET first_grade = ?, grade = ?, grade_note = ? WHERE id = ?",
                         (first_g, last["grade"], last["note"], r["id"]))
            if res and res.get("solved"):
                conn.execute("UPDATE appeals SET status = 'hal', resolved_at = coalesce(resolved_at, ?), "
                             "resolved_by = coalesce(resolved_by, ?), resolution = coalesce(resolution, 'javob') WHERE id = ?",
                             (last["at"], last["who"], r["id"]))
        n += 1
    if n:
        db.bump_version(conn)
    return n


def _insight_key(pid: int, typ: str, day: str) -> str:
    return "%d|%s|%s" % (pid, typ, day)


def refresh_insights(conn: sqlite3.Connection, now: datetime | None = None, limit: int = 4) -> int:
    """Takroriy murojaatlar ko'p bo'lgan (tizim, tur) juftliklari uchun sabab va tavsiya — kuniga bir marta (AI)."""
    if not config.appeals_ai_enabled():
        return 0
    now = now or config.now()
    day = now.date().isoformat()
    since = _ts(now - timedelta(days=30))
    pairs = conn.execute("SELECT project_id, type, count(*) AS n FROM appeals WHERE rep = 1 AND created_at >= ? AND project_id IS NOT NULL "
                         "GROUP BY project_id, type HAVING count(*) >= 2 ORDER BY count(*) DESC", (since,)).fetchall()
    done = 0
    for p in pairs:
        if done >= limit:
            break
        key = _insight_key(p["project_id"], p["type"], day)
        if conn.execute("SELECT 1 FROM appeal_insights WHERE key = ?", (key,)).fetchone():
            continue
        chains = defaultdict(list)
        for a in conn.execute("SELECT id, coalesce(chain, id) AS ch FROM appeals WHERE project_id = ? AND type = ? AND created_at >= ? "
                              "AND chain IS NOT NULL ORDER BY created_at", (p["project_id"], p["type"], since)):
            chains[a["ch"]].append(a["id"])
        blocks = []
        for ch, ids in list(chains.items())[:12]:
            marks = ",".join("?" * len(ids))
            lines = ["%s %s: %s" % ("javob" if e["staff"] else "foydalanuvchi", e["at"][5:16], short(e["text"], 220))
                     for e in conn.execute("SELECT at, staff, text FROM appeal_events WHERE appeal_id IN (%s) AND kind IN "
                                           "('murojaat', 'qoshimcha', 'javob', 'qayta') ORDER BY at, id" % marks, ids)]
            blocks.append("---\n" + "\n".join(lines[:12]))
        name = conn.execute("SELECT name FROM projects WHERE id = ?", (p["project_id"],)).fetchone()
        raw = ai.ask_appeals(INSIGHT_PROMPT.format(system=name["name"] if name else "-", type=TYPES.get(p["type"], p["type"]),
                                                   chains="\n".join(blocks)), INSIGHT_SCHEMA, 1, 400)
        done += 1
        if raw and raw.get("cause"):
            conn.execute("INSERT INTO appeal_insights(key, cause, act, at) VALUES(?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                         "cause = excluded.cause, act = excluded.act, at = excluded.at",
                         (key, raw["cause"].strip()[:300], (raw.get("act") or "").strip()[:300], _now()))
            conn.commit()
    return done


def tick() -> int:
    with db.session() as conn:
        n = auto_close(conn)
        n += classify_pending(conn)
        conn.commit()
        n += refresh_insights(conn)
        return n


# ---------------------------------------------------------------- rahbar tuzatishi

def correct(conn: sqlite3.Connection, aid: int, who: str, typ: str | None = None, project_id: int | None = None,
            status: str | None = None) -> dict:
    a = conn.execute("SELECT * FROM appeals WHERE id = ?", (aid,)).fetchone()
    if a is None:
        raise ValueError("Murojaat topilmadi")
    notes = []
    if typ is not None and typ != a["type"]:
        if typ not in TYPES:
            raise ValueError("Murojaat turi noto'g'ri")
        notes.append("turi: %s" % TYPES[typ])
        conn.execute("UPDATE appeals SET type = ? WHERE id = ?", (typ, aid))
    if project_id is not None and project_id != a["project_id"]:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise ValueError("Loyiha topilmadi")
        notes.append("loyiha o'zgardi")
        conn.execute("UPDATE appeals SET project_id = ? WHERE id = ?", (project_id, aid))
    if typ is not None or project_id is not None:
        b = conn.execute("SELECT client_id, project_id, type, created_at FROM appeals WHERE id = ?", (aid,)).fetchone()
        prev = _repeat_of(conn, b["client_id"], b["project_id"], b["type"], b["created_at"])
        conn.execute("UPDATE appeals SET rep = ?, chain = ? WHERE id = ?",
                     (1 if prev is not None else 0, (prev["chain"] or prev["id"]) if prev is not None else None, aid))
    if status is not None and status != a["status"]:
        if status == "hal":
            conn.execute("UPDATE appeals SET status = 'hal', resolved_at = ?, resolved_by = ?, resolution = 'qolda' WHERE id = ?",
                         (_now(), who, aid))
        elif status == "ochiq":
            conn.execute("UPDATE appeals SET status = CASE WHEN first_answer_at IS NULL THEN 'ochiq' ELSE 'qayta' END, "
                         "resolved_at = NULL, resolved_by = NULL, resolution = NULL WHERE id = ?", (aid,))
        else:
            raise ValueError("Holat: hal yoki ochiq")
        notes.append("hal qilindi deb belgilandi" if status == "hal" else "qayta ochildi")
    if notes:
        conn.execute("UPDATE appeals SET fixed_by = ?, ai = CASE WHEN ai IS NULL THEN 'qolda' ELSE ai END WHERE id = ?", (who, aid))
        conn.execute("INSERT INTO appeal_events(appeal_id, at, kind, who, staff, text) VALUES(?, ?, 'tuzatish', ?, 1, ?)",
                     (aid, _now(), who, "; ".join(notes)))
        db.bump_version(conn)
    return {"ok": True, "changed": notes}


def set_client_staff(conn: sqlite3.Connection, cid: int, line: int | None) -> None:
    if line is not None and line not in (0, 1, 2, 3):
        raise ValueError("Liniya: 0 (foydalanuvchi), 1, 2 yoki 3")
    if not conn.execute("UPDATE clients SET staff = ? WHERE id = ?", (line, cid)).rowcount:
        raise ValueError("Topilmadi")
    db.bump_version(conn)


# ---------------------------------------------------------------- tahlil

def _scope_sql(scope: set[int] | None, col: str = "a.project_id") -> str:
    if scope is None:
        return ""
    return " AND %s IN (%s)" % (col, ",".join(str(int(x)) for x in scope) or "NULL")


def real_mode(conn: sqlite3.Connection) -> bool:
    """Haqiqiy manba ulanganmi: yordam guruhi, chatbot yoki kamida bitta murojaat."""
    return bool(conn.execute("SELECT 1 FROM chats WHERE kind = 'yordam' LIMIT 1").fetchone()
                or conn.execute("SELECT 1 FROM appeal_sources LIMIT 1").fetchone()
                or conn.execute("SELECT 1 FROM appeals LIMIT 1").fetchone())


def load_rows(conn: sqlite3.Connection, since: str, until: str, scope: set[int] | None = None) -> list[dict]:
    rows = []
    for r in conn.execute(
            "SELECT a.id, a.source, a.source_id, a.chat_id, a.project_id, p.name AS project, a.client_id, cl.name AS client, "
            "cl.username, a.text, a.summary, a.type, a.created_at, a.first_answer_at, a.first_grade, a.answered_by, a.line, a.grade, "
            "a.status, a.resolved_at, a.resolution, a.chain, a.rep, a.last_at, a.ai, ch.title AS chat, s.name AS bot "
            "FROM appeals a LEFT JOIN projects p ON p.id = a.project_id LEFT JOIN clients cl ON cl.id = a.client_id "
            "LEFT JOIN chats ch ON ch.id = a.chat_id LEFT JOIN appeal_sources s ON s.id = a.source_id "
            "WHERE a.created_at > ? AND a.created_at <= ?" + _scope_sql(scope), (since, until)):
        rows.append(dict(r))
    return rows


def _norm(rows: list[dict], until: str) -> list[dict]:
    """Vaqt mashinasi: tanlangan kun oxiridan keyin hal qilingani hali ochiq hisoblanadi."""
    out = []
    for r in rows:
        x = dict(r)
        res = x["status"] == "hal" and x["resolved_at"] and x["resolved_at"] <= until
        x["resolved"] = bool(res)
        x["hours"] = _hours(x["created_at"], x["resolved_at"]) if res else None
        if not res and x["status"] == "hal":
            x["status"] = "javob" if x["first_answer_at"] and x["first_answer_at"] <= until else "ochiq"
        if x["first_answer_at"] and x["first_answer_at"] > until:  # tanlangan kundan keyin javob berilgan: o'sha kuni hali ochiq
            x["grade"], x["line"], x["status"] = None, None, "ochiq"
        x["q"] = x["grade"] or "none"
        if x["project_id"] is None:  # tizimi aniqlanmagan: alohida qatorda, odam tasdiqlaydi
            x["project_id"], x["project"] = UNKNOWN, "Tizim aniqlanmagan"
        x["bot_src"] = x["source"] == "bot"
        x["src_name"] = x["bot"] if x["bot_src"] else x["chat"]
        out.append(x)
    return out


def agg(rows: list[dict]) -> dict:
    o = {"n": len(rows), "res": 0, "open": 0, "rep": 0, "h": 0.0, "hn": 0, "q": {"good": 0, "part": 0, "tpl": 0, "none": 0},
         "cl": {}, "line": [0, 0, 0, 0], "line_res": [0, 0, 0, 0], "line_h": [0.0, 0.0, 0.0, 0.0], "bucket": [0, 0, 0, 0, 0]}
    for x in rows:
        ln = x["line"] if x["line"] in (0, 1, 2, 3) else None
        if x["resolved"]:
            o["res"] += 1
            o["h"] += x["hours"] or 0
            o["hn"] += 1
            h = x["hours"] or 0
            o["bucket"][0 if h < 1 else 1 if h < 4 else 2 if h < 24 else 3 if h < 72 else 4] += 1
            if ln is not None:
                o["line_res"][ln] += 1
                o["line_h"][ln] += h
        else:
            o["open"] += 1
        if x["rep"]:
            o["rep"] += 1
        o["q"][x["q"]] += 1
        if ln is not None:
            o["line"][ln] += 1
        c = o["cl"].setdefault(x["type"] or "boshqa", {"n": 0, "rep": 0, "h": 0.0, "hn": 0, "bad": 0, "open": 0})
        c["n"] += 1
        c["rep"] += 1 if x["rep"] else 0
        if x["resolved"]:
            c["h"] += x["hours"] or 0
            c["hn"] += 1
        else:
            c["open"] += 1
        if x["q"] in ("tpl", "none"):
            c["bad"] += 1
    n = o["n"] or 1
    o["avg_h"] = o["h"] / o["hn"] if o["hn"] else None
    o["res_rate"] = o["res"] / n if o["n"] else None
    o["rep_rate"] = o["rep"] / n if o["n"] else None
    o["bad_rate"] = (o["q"]["tpl"] + o["q"]["none"]) / n if o["n"] else None
    return o


def first_answer_bad(rows: list[dict], all_rows: list[dict] | None = None) -> float | None:
    """Takroriy zanjirlarda birinchi murojaatga berilgan javob shablon yoki qisman bo'lgan ulush."""
    chains = {x["chain"] for x in rows if x["chain"]}
    firsts = [x for x in (all_rows or rows) if x["id"] in chains]
    if not firsts:
        return None
    return sum(1 for x in firsts if (x["first_grade"] or x["q"]) in ("tpl", "part", "none")) / len(firsts)


def fh(h: float | None) -> str:
    if h is None:
        return "—"
    if h < 1:
        return "%d daqiqa" % max(1, round(h * 60))
    if h < 24:
        return ("%.1f soat" % h).replace(".0 ", " ").replace(".", ",")
    return ("%.1f kun" % (h / 24)).replace(".0 ", " ").replace(".", ",")


def pctf(x: float | None) -> str:
    return "—" if x is None else "%d%%" % round(x * 100)


def _delta(cur: int, prev: int) -> dict:
    if not prev:
        return {"t": "yangi" if cur else "—", "c": "flat", "v": None}
    d = (cur - prev) / prev
    if abs(d) < .03:
        return {"t": "o'zgarmagan", "c": "flat", "v": 0}
    return {"t": "%s%d%%" % ("+" if d > 0 else "", round(d * 100)), "c": "up" if d > 0 else "down", "v": round(d * 100)}


def project_stats(rows: list[dict], prev_rows: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for x in rows:
        by[x["project_id"]].append(x)
    pc = Counter(x["project_id"] for x in prev_rows)
    mx = max([len(v) for v in by.values()] or [1])
    out = []
    for pid, l in by.items():
        a = agg(l)
        att = round(35 * a["n"] / mx + 25 * min(1, (1 - a["res_rate"]) / .3) + 20 * min(1, a["rep_rate"] / .35)
                    + 20 * min(1, a["bad_rate"] / .45))
        rs = []
        if a["n"] / mx > .45:
            rs.append("%d ta murojaat" % a["n"])
        if 1 - a["res_rate"] > .12:
            rs.append("%s hal qilinmagan" % pctf(1 - a["res_rate"]))
        if a["rep_rate"] > .12:
            rs.append("%s takroriy" % pctf(a["rep_rate"]))
        if a["bad_rate"] > .3:
            rs.append("%s javob shablon yoki yo'q" % pctf(a["bad_rate"]))
        if a["avg_h"] is not None and a["avg_h"] > 36:
            rs.append("o'rtacha %sda hal qilinadi" % fh(a["avg_h"]))
        top = max(a["cl"].items(), key=lambda kv: kv[1]["n"], default=None)
        if top:
            rs.append("asosan «%s»" % TYPES.get(top[0], top[0]))
        out.append({"id": pid, "name": l[0]["project"] or "Tizim belgilanmagan", "n": a["n"], "prev": pc.get(pid, 0),
                    "delta": _delta(a["n"], pc.get(pid, 0)), "res_rate": a["res_rate"], "rep_rate": a["rep_rate"],
                    "bad_rate": a["bad_rate"], "avg_h": a["avg_h"], "open": a["open"], "att": att, "reasons": rs,
                    "top_type": top[0] if top else None})
    out.sort(key=lambda x: (-x["n"], x["name"]))
    return out


def insights(ps: list[dict], tot: dict, rows: list[dict]) -> list[list]:
    """Rahbar uchun xulosa: har gap haqiqiy raqamdan (qism: [matn, qalin]; loyiha va tur bosiladigan bo'ladi)."""
    out = []
    if not ps or not tot["n"]:
        return out
    t3 = ps[:3]
    share = sum(x["n"] for x in t3) / tot["n"]
    if len(ps) > 3:
        out.append([["Murojaatlarning ", 0], [pctf(share), 1], [" i %d ta loyihaga to'g'ri keladi: " % len(t3), 0],
                    [", ".join(x["name"] for x in t3), 1], [".", 0]])
    best = None
    for x in ps:
        for k, c in agg([r for r in rows if r["project_id"] == x["id"]])["cl"].items():
            if c["n"] >= 3 and c["rep"] and (best is None or c["rep"] > best[2]["rep"]):
                best = (x, k, c)
    if best:
        out.append([["Eng ko'p takrorlanayotgan muammo: ", 0], ["%s, «%s»" % (best[0]["name"], TYPES.get(best[1], best[1])), 1],
                    [". %d ta murojaatdan %d tasi takroriy." % (best[2]["n"], best[2]["rep"]), 0]])
    slow = sorted((x for x in ps if x["avg_h"] is not None and x["n"] >= 5), key=lambda x: -x["avg_h"])
    if slow and tot["avg_h"] and slow[0]["avg_h"] / tot["avg_h"] > 1.3:
        out.append([[slow[0]["name"], 1], ["da murojaatlar o'rtacha %sda hal qilinmoqda, bu umumiy o'rtachadan %s marta uzoq."
                                            % (fh(slow[0]["avg_h"]), ("%.1f" % (slow[0]["avg_h"] / tot["avg_h"])).replace(".0", "").replace(".", ",")), 0]])
    grow = sorted((x for x in ps if x["prev"] >= 5), key=lambda x: -(x["n"] - x["prev"]) / x["prev"])
    if grow and (grow[0]["n"] - grow[0]["prev"]) / grow[0]["prev"] > .15:
        g = grow[0]
        out.append([[g["name"], 1], ["da murojaatlar oldingi davrga nisbatan ", 0], ["%d%%" % round((g["n"] - g["prev"]) / g["prev"] * 100), 1],
                    [" ga ko'paygan. Yangi o'zgarish yoki nosozlik bilan bog'liqligini tekshirish kerak.", 0]])
    opened = sorted((x for x in rows if not x["resolved"] and x["status"] == "ochiq"), key=lambda x: x["created_at"])
    if opened:
        c = opened[0]["created_at"]
        out.append([["Javob kutayotgan murojaatlar: ", 0], ["%d ta" % len(opened), 1],
                    [", eng eskisi %s.%s.%s, soat %s dan beri." % (c[8:10], c[5:7], c[:4], c[11:16]), 0]])
    if tot["bad_rate"] is not None:
        fb = first_answer_bad(rows)
        seg = [["Murojaatlarning ", 0], [pctf(tot["bad_rate"]), 1], [" i shablon javob olgan yoki javobsiz qolgan.", 0]]
        if fb is not None:
            seg += [[" Takroriy murojaatlarda birinchi javobning ", 0], [pctf(fb), 1],
                    [" i shablon yoki qisman bo'lgan: muammo birinchi marta hal qilinmagani uchun odamlar qayta yozyapti.", 0]]
        out.append(seg)
    return out


def _chart(rows: list[dict], days: int, end_day) -> dict:
    start = end_day - timedelta(days=days - 1)
    c = [0] * days
    for x in rows:
        i = (datetime.strptime(x["created_at"][:10], "%Y-%m-%d").date() - start).days
        if 0 <= i < days:
            c[i] += 1
    mx = max(c) if c else 0
    return {"days": [[(start + timedelta(days=i)).isoformat(), v] for i, v in enumerate(c)], "avg": round(sum(c) / days, 1) if days else 0,
            "max": mx, "max_day": (start + timedelta(days=c.index(mx))).isoformat() if mx else None}


def _cls_rows(a: dict) -> list[dict]:
    out = []
    for k, c in sorted(a["cl"].items(), key=lambda kv: -kv[1]["n"]):
        out.append({"key": k, "name": TYPES.get(k, k), "n": c["n"], "share": c["n"] / a["n"] if a["n"] else 0,
                    "avg_h": c["h"] / c["hn"] if c["hn"] else None, "rep_rate": c["rep"] / c["n"], "bad_rate": c["bad"] / c["n"],
                    "open": c["open"], "rep": c["rep"]})
    return out


def _feed_item(x: dict) -> dict:
    return {"id": x["id"], "at": x["created_at"], "source": x["source"], "src_name": x["src_name"], "client": x["client"],
            "project_id": x["project_id"], "project": x["project"], "summary": x["summary"] or short(x["text"], 90),
            "type": x["type"], "type_name": TYPES.get(x["type"], x["type"]), "status": x["status"], "resolved": x["resolved"],
            "line": x["line"], "hours": x["hours"], "grade": x["q"], "rep": bool(x["rep"]), "ai": x["ai"]}


def _insight_for(conn, pid, typ) -> dict | None:
    if conn is None or not pid:
        return None
    r = conn.execute("SELECT cause, act, at FROM appeal_insights WHERE key LIKE ? ORDER BY at DESC LIMIT 1",
                     ("%d|%s|%%" % (pid, typ),)).fetchone()
    return dict(r) if r else None


def overview(conn: sqlite3.Connection, now: datetime, days: int = 30, src: str = "", project: int | None = None,
             typ: str = "", status: str = "", q: str = "", offset: int = 0, limit: int = 25, scope: set[int] | None = None,
             sample: bool | None = None) -> dict:
    """Murojaatlar bo'limi uchun hamma narsa bitta javobda (maket bloklari tartibida)."""
    days = days if days in (7, 30, 90) else 30
    end = now.replace(hour=23, minute=59, second=59) if now.time() == datetime.min.time() else now
    until, since, psince = _ts(end), _ts(end - timedelta(days=days)), _ts(end - timedelta(days=2 * days))
    use_sample = (not real_mode(conn)) if sample is None else sample
    if use_sample:
        from . import appeals_sample
        rows, prev_rows = appeals_sample.rows(end, since, until), appeals_sample.rows(end, psince, since)
    else:
        rows, prev_rows = load_rows(conn, since, until, scope), load_rows(conn, psince, since, scope)
    rows, prev_rows = _norm(rows, until), _norm(prev_rows, since)
    if src in ("tg", "bot"):
        rows = [x for x in rows if x["source"] == src]
        prev_rows = [x for x in prev_rows if x["source"] == src]
    tot, ptot = agg(rows), agg(prev_rows)
    ps = project_stats(rows, prev_rows)
    if project is not None and project != 0 and not any(x["id"] == project for x in ps):
        project = None
    sel = project if project is not None else (ps[0]["id"] if ps else 0)
    pl = [x for x in rows if x["project_id"] == sel] if sel else rows
    pa = agg(pl)
    fl_rows = [x for x in pl if x["type"] == typ] if typ else pl
    fl = agg(fl_rows)
    # takroriy murojaatlar: nega qaytib kelyapti (tanlangan loyiha bo'yicha)
    reps = []
    for c in sorted(_cls_rows(pa), key=lambda c: -c["rep"]):
        if c["rep"] < 2 or len(reps) >= 4:
            continue
        cl = [x for x in pl if x["type"] == c["key"]]
        chains = Counter(x["chain"] for x in cl if x["chain"])
        srcs = Counter(x["src_name"] for x in cl if x["rep"] and x["src_name"])
        pid = sel or (Counter(x["project_id"] for x in cl if x["rep"]).most_common(1) or [(None, 0)])[0][0]
        ins = (appeals_sample.insight(c["key"]) if use_sample else _insight_for(conn, pid, c["key"]))
        reps.append({"type": c["key"], "name": c["name"], "rep": c["rep"], "rate": c["rep_rate"], "users": len(chains),
                     "avg_len": round(sum(chains.values()) / len(chains), 1) if chains else 0, "first_bad": first_answer_bad(cl, pl),
                     "open": c["open"], "main_src": srcs.most_common(1)[0][0] if srcs else None,
                     "cause": ins["cause"] if ins else None, "act": ins["act"] if ins else None, "n": c["n"]})
    feed_rows = sorted(fl_rows, key=lambda x: x["created_at"], reverse=True)
    if status == "ochiq":
        feed_rows = [x for x in feed_rows if not x["resolved"]]
    elif status == "hal":
        feed_rows = [x for x in feed_rows if x["resolved"]]
    elif status == "takror":
        feed_rows = [x for x in feed_rows if x["rep"]]
    elif status == "yomon":
        feed_rows = [x for x in feed_rows if x["q"] in ("tpl", "none")]
    if q:
        f = fold(q)
        feed_rows = [x for x in feed_rows if f in fold(" ".join(str(x.get(k) or "") for k in ("summary", "text", "client", "project", "src_name")))]
    n_tg = sum(1 for x in rows if x["source"] == "tg")
    out = {
        "sample": use_sample, "days": days, "src": src, "end": end.date().isoformat(), "now": _ts(config.now()),
        "connected": None if use_sample else {
            "chats": [dict(r) for r in conn.execute("SELECT c.id, c.title FROM chats c WHERE c.kind = 'yordam' ORDER BY c.title")],
            "bots": [dict(r) for r in conn.execute("SELECT id, name, last_at FROM appeal_sources WHERE active = 1 ORDER BY name")]},
        "kpi": {"n": tot["n"], "prev_n": ptot["n"], "delta": _delta(tot["n"], ptot["n"]), "res_rate": tot["res_rate"], "open": tot["open"],
                "avg_h": tot["avg_h"], "prev_avg_h": ptot["avg_h"], "rep_rate": tot["rep_rate"], "rep": tot["rep"],
                "bad_rate": tot["bad_rate"], "tg": n_tg, "bot": tot["n"] - n_tg,
                "waiting": sum(1 for x in rows if not x["resolved"] and x["status"] in ("ochiq", "qayta")),
                "unknown": sum(1 for x in rows if x["project_id"] == UNKNOWN)},
        "unknown_id": UNKNOWN,
        "insights": insights(ps, tot, rows),
        "projects": ps,
        "selected": sel, "type": typ if typ in TYPES else "",
        "chart": _chart(pl, days, end.date()),
        "types": _cls_rows(pa),
        "flow": {"lines": [{"line": i, "name": LINES[i], "n": fl["line"][i], "share": fl["line"][i] / fl["n"] if fl["n"] else 0,
                            "res_rate": fl["line_res"][i] / fl["line"][i] if fl["line"][i] else None,
                            "avg_h": fl["line_h"][i] / fl["line_res"][i] if fl["line_res"][i] else None} for i in range(4)],
                 "buckets": fl["bucket"], "unanswered": fl["q"]["none"], "n": fl["n"]},
        "quality": {**fl["q"], "n": fl["n"], "first_bad": first_answer_bad(fl_rows, pl)},
        "repeats": reps,
        "feed": {"total": len(feed_rows), "offset": offset, "items": [_feed_item(x) for x in feed_rows[offset:offset + limit]]},
        "labels": {"types": TYPES, "lines": LINES, "grades": GRADES, "status": STATUS},
    }
    return out


def detail(conn: sqlite3.Connection, aid: int, scope: set[int] | None = None, sample: bool = False) -> dict | None:
    from .quality import tg_link
    if sample or aid < 0:
        from . import appeals_sample
        return appeals_sample.detail(aid)
    a = conn.execute("SELECT a.*, p.name AS project, cl.name AS client, cl.username, cl.ext AS client_ext, cl.source AS client_source, "
                     "cl.staff AS client_staff, ch.title AS chat, s.name AS bot FROM appeals a LEFT JOIN projects p ON p.id = a.project_id "
                     "LEFT JOIN clients cl ON cl.id = a.client_id LEFT JOIN chats ch ON ch.id = a.chat_id "
                     "LEFT JOIN appeal_sources s ON s.id = a.source_id WHERE a.id = ?", (aid,)).fetchone()
    if a is None or (scope is not None and a["project_id"] not in scope):
        return None
    a = dict(a)
    events = []
    for e in conn.execute("SELECT e.*, m.chat_id AS m_chat, m.msg_id AS m_tg, m.deleted_at FROM appeal_events e "
                          "LEFT JOIN messages m ON m.id = e.msg WHERE e.appeal_id = ? ORDER BY e.at, e.id", (aid,)):
        d = dict(e)
        d["link"] = tg_link(d.pop("m_chat"), d.pop("m_tg"))
        events.append(d)
    chain = []
    if a["chain"]:
        chain = [dict(r) for r in conn.execute(
            "SELECT id, created_at, coalesce(summary, text) AS summary, status, grade, first_grade FROM appeals WHERE id = ? OR chain = ? "
            "ORDER BY created_at", (a["chain"], a["chain"]))]
    history = conn.execute("SELECT count(*) FROM appeals WHERE client_id = ?", (a["client_id"],)).fetchone()[0] if a["client_id"] else 0
    ins = _insight_for(conn, a["project_id"], a["type"]) if a["chain"] else None
    return {"appeal": {**a, "type_name": TYPES.get(a["type"], a["type"]), "status_name": STATUS.get(a["status"], a["status"]),
                       "hours": _hours(a["created_at"], a["resolved_at"]) if a["status"] == "hal" else None,
                       "first_hours": _hours(a["created_at"], a["first_answer_at"])},
            "events": events, "chain": chain, "client_appeals": history, "insight": ins, "sample": False,
            "projects": [dict(r) for r in conn.execute("SELECT id, name FROM projects ORDER BY name")] if scope is None else
            [dict(r) for r in conn.execute("SELECT id, name FROM projects ORDER BY name") if r["id"] in scope],
            "labels": {"types": TYPES, "lines": LINES, "grades": GRADES, "status": STATUS}}


def dataset(conn: sqlite3.Connection, scope: set[int] | None = None):
    """Modelni o'rgatish uchun misollar: murojaat matni -> tizim va tur (va javoblar bahosi). Rahbar tuzatgani "checked":
    eng ishonchli misollar. Tizimi aniqlanmaganlari ham chiqadi (system: null) — model "bilmayman" deyishni ham o'rganadi."""
    for a in conn.execute(
            "SELECT a.id, a.text, a.summary, a.type, a.project_id, p.name AS project, a.source, coalesce(ch.title, s.name) AS kanal, "
            "a.created_at, a.fixed_by, a.ai, a.status FROM appeals a LEFT JOIN projects p ON p.id = a.project_id "
            "LEFT JOIN chats ch ON ch.id = a.chat_id LEFT JOIN appeal_sources s ON s.id = a.source_id ORDER BY a.id").fetchall():
        if scope is not None and a["project_id"] not in scope:
            continue
        answers = [{"text": e["text"], "grade": e["grade"], "line": e["line"]} for e in conn.execute(
            "SELECT text, grade, line FROM appeal_events WHERE appeal_id = ? AND kind = 'javob' ORDER BY at, id", (a["id"],))]
        yield {"id": a["id"], "text": a["text"], "summary": a["summary"], "system": a["project"], "type": a["type"],
               "channel": a["kanal"], "source": a["source"], "at": a["created_at"], "checked": bool(a["fixed_by"]),
               "read_by": a["ai"], "status": a["status"], "answers": answers}


def project_counts(conn: sqlite3.Connection, now: datetime, days: int = 30) -> dict[int, dict]:
    """Loyiha kartasi uchun: oxirgi 30 kunda nechta murojaat, nechtasi ochiq, nechtasi takroriy."""
    out: dict[int, dict] = {}
    for r in conn.execute("SELECT project_id, count(*) AS n, sum(CASE WHEN status IN ('ochiq', 'javob', 'qayta') THEN 1 ELSE 0 END) AS op, "
                          "sum(rep) AS rp FROM appeals WHERE created_at > ? AND created_at <= ? AND project_id IS NOT NULL "
                          "GROUP BY project_id", (_ts(now - timedelta(days=days)), _ts(now))):
        out[r["project_id"]] = {"n": r["n"], "open": r["op"] or 0, "rep": r["rp"] or 0}
    return out


def digest_line(conn: sqlite3.Connection, now: datetime) -> str | None:
    """Ertalabki brifing uchun bitta qator: kechagi (ish kuni) murojaatlar."""
    if not conn.execute("SELECT 1 FROM appeals LIMIT 1").fetchone():
        return None
    since = _ts(now - timedelta(days=1))
    rows = conn.execute("SELECT a.project_id, p.name, a.status FROM appeals a LEFT JOIN projects p ON p.id = a.project_id "
                        "WHERE a.created_at > ? AND a.created_at <= ?", (since, _ts(now))).fetchall()
    waiting = conn.execute("SELECT count(*) FROM appeals WHERE status IN ('ochiq', 'qayta')").fetchone()[0]
    if not rows and not waiting:
        return None
    top = Counter(r["name"] for r in rows if r["name"]).most_common(1)
    return "Murojaatlar (24 soat): %d ta%s; javob kutayotgani: %d ta." % (
        len(rows), (", eng ko'p: %s (%d)" % top[0]) if top else "", waiting)
