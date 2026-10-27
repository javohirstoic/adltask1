"""Xabarni tushunish.

Ikki yo'l bor:
1. Format: xabarda #task, #done, #muammo yoki #deadline bo'lsa, qoida bilan aniq o'qiladi.
2. Erkin matn: format bo'lmasa, AI o'qiydi (ai.py). AI o'chiq yoki ishlamasa,
   shu fayldagi kalit so'zlar bilan taxmin qilinadi.
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

TYPE_TAGS = {
    "task": {"task", "tasks", "vazifa", "topshiriq", "reja", "todo", "задача", "задачи"},
    "done": {"done", "bajarildi", "bajardim", "tayyor", "tugadi", "готово", "сделано"},
    "deadline": {"deadline", "muddat", "dedlayn", "срок"},
    "blocker": {"muammo", "blok", "blocker", "problem", "проблема"},
}
TAG_KIND = {tag: kind for kind, tags in TYPE_TAGS.items() for tag in tags}
# "Bu kunlik hisobot" degan teg: loyiha nomi emas. Bo'lim sarlavhasi bo'lmasa ham qatorlar bajarilgan ish deb o'qiladi
REPORT_TAGS = {"hisobot", "kunlikhisobot", "kunlik_hisobot", "otchet", "отчет", "отчёт", "report"}
# Yo'riqnoma namunasidagi o'rinbosar: so'zma-so'z ko'chirilsa ham "LoyihaNomi" degan loyiha ochilmaydi
NOT_PROJECT = REPORT_TAGS | {"loyihanomi", "loyiha_nomi", "loyiha-nomi"}

HASHTAG_RE = re.compile(r"#([\w\-]+)", re.U)
MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{3,31})")
BULLET_RE = re.compile(r"^\s*(?:[-–—•*·▪►✓✔✅☑]️?|\d{1,2}[.)])\s*")
WORD_RE = re.compile(r"[^\W_]+", re.U)

MONTHS = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6, "iyul": 7,
    "avgust": 8, "sentyabr": 9, "sentabr": 9, "oktyabr": 10, "noyabr": 11, "dekabr": 12,
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7,
    "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

# Erkin matn uchun kalit so'zlar (AI bo'lmaganda ishlaydi)
BLOCKER_RE = re.compile(
    r"muammo|ishlamayapti|ishlamay qoldi|ishlamayap|xato chiqyapti|xatolik|to'xtab qoldi|tushib qoldi|"
    r"ruxsat\s+(?:hali\s+)?yo'q|ruxsat berilmagan|kirish yo'q|kutib turibmiz|kutyapmiz|javob yo'q|bloklandi|"
    r"ololmayapmiz|olmayapmiz|"
    r"не работает|проблем|ошибк|завис",
    re.I,
)
DONE_RE = re.compile(
    r"\b(?:bajar|tugat|tugall|yakunla|tuzat|topshir|ula|yop|o'rnat|yoz|qo'sh|chiqar|tekshir|sozla|jo'nat|bit)\w*"
    r"(?:(?<![ay])dim|(?<![ay])di|ldi|ndi|(?<![ay])dik|ildi|ilindi|ishdi)\b|"  # "tekshiradi", "ulaydi" — hozirgi zamon, bajarilgan emas
    r"tayyor bo'ldi|\btayyor\b[^\w\n]*$|tayyor,|bajarildi|deploy qilindi|deploy qildim|ishga tushdi|ishga tushirildi|"
    r"hal bo'ldi|hal qilindi|готово|сделал|сделано|закончил|выполнен|\bdone\b",
    re.I | re.M,
)
TASK_RE = re.compile(
    r"kerak|lozim|qilinsin|qiling\b|olsin\b|vazifa|topshiriq|rejada|rejamiz|qilamiz|qilaman|"
    r"boshlayman|boshlaymiz|ustida ishlayman|ustida ishlaymiz|нужно|надо|сделать",
    re.I,
)
# "Xatolik tuzatildi" muammo emas, bajarilgan ish
RESOLVED_RE = re.compile(r"tuzat\w*(?:di|dim|ildi)|hal bo'ldi|hal qilindi|to'g'irla\w*di|endi ishlayapti|ishladi\b", re.I)
# Sarlavhadan olib tashlanadigan "bajarildi" qo'shimchalari
DONE_TAIL_RE = re.compile(
    r"[\s,.:;—-]*(?:ni|ham)?\s*(?:tayyor bo'ldi|tayyor|bajarildi|bajardim|tugatdim|tugatildi|tugadi|yakunlandi|"
    r"tuzatildi|tuzatdim|qildim|qilindi|deploy qilindi|ishga tushirildi|hal bo'ldi|hal qilindi|done|готово)"
    r"[^\w\n]*(?:testga berdim|testga berildi)?[^\w\n]*$",
    re.I,
)
# Muddat belgisi: "25-oktyabrgacha", "ertagacha", "muddat: 15.11", "до 20.10". Bunday qatordagi sana vazifaning muddati
_MONTH_RE = r"(?:yanvar|fevral|mart|aprel|may|iyun|iyul|avgust|sentyabr|sentabr|oktyabr|noyabr|dekabr|январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)"
DEADLINE_CUE_RE = re.compile(r"gacha\b|muddat|deadline|dedlayn|срок|\bдо\s+\d|\d{1,2}[\s\-]*" + _MONTH_RE, re.I)
DATE_PHRASE_RE = re.compile(
    r"(?:\b(?:muddat\w*|deadline|dedlayn|срок)\s*[:\-—]?\s*)?(?:\bдо\s+)?"
    r"(?:\b\d{4}-\d{1,2}-\d{1,2}|\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|\b\d{1,2}[\s\-]*" + _MONTH_RE + r"\w*|\b(?:ertaga|indinga)\w*)"
    r"(?:\s*-?\s*(?:gacha|kuni|da))?\b",
    re.I,
)
# Hozir qilinayotgan ish: "ishlayapman", "yozyapmiz", "tayyorlanmoqda"
DOING_RE = re.compile(r"\w{3,}(?:yapman|yapmiz|yapti|moqda|moqdaman|moqdamiz)\b|в процессе|делаю|работаю", re.I)
PERCENT_RE = re.compile(r"\b\d{1,3}\s?%")
# Buyruq va yaqin muddat: "Sardor qilsin", "juma kuni tayyor bo'lsin", "ertaga topshir"
ORDER_RE = re.compile(r"\b\w{2,}(?:sin|sinlar)\b|\b(?:qil|yoz|ber|tayyorla|topshir|tekshir|yubor|tugat|bajar)\b", re.I)
SOON_RE = re.compile(r"\b(?:ertaga|indinga|dushanba|seshanba|chorshanba|payshanba|juma|shanba|yakshanba|haftaga)\w*"
                     r"|завтра|понедельник|вторник|сред[аеуы]|четверг|пятниц|суббот", re.I)
TASK_TAIL_RE = re.compile(r"[\s,.:;—-]*(?:ni|ham)?\s*(?:qilish kerak|kerak|lozim|qilinsin|qiling|olsin)[\s,.!]*$", re.I)
STOP = {"va", "bilan", "uchun", "ham", "ni", "bo'yicha", "boyicha", "bugun", "kecha", "ertaga", "the", "and"}


@dataclass
class Item:
    title: str
    assignee: str | None = None  # "@username" yoki None
    deadline: date | None = None  # shu vazifaning muddati
    note: str | None = None       # uzun bandning qolgan qismi (sabab, tafsilot)
    same_as: int | None = None    # AI: bugun shu guruhda allaqachon yozilgan aynan shu ish (tasks.id)
    progress: int | None = None   # "Jarayonda: ... — 90%" dagi foiz


@dataclass
class Parsed:
    kind: str                     # task | done | blocker | deadline | reassign | none
    project: str | None = None    # teg yoki loyiha kaliti
    items: list[Item] = field(default_factory=list)
    deadline: date | None = None
    source: str = "format"        # format | ai | taxmin
    refs: list[int] = field(default_factory=list)  # gap ketayotgan mavjud vazifalar (tasks.id), AI kontekstdan topadi
    solves: list[int] = field(default_factory=list)  # shu xabar hal qilgan ochiq muammolar (blockers.id), AI topadi
    # Kunlik hisobot (parse_report): bo'limlar bo'yicha bandlar, hisobot sanasi va yozgan xodimning bo'limi
    sections: dict = field(default_factory=dict)   # done | doing | plan | blocker -> [Item]
    day: date | None = None
    department: str | None = None
    holat: str | None = None      # hisobotdagi "Holat: Sariq" — xodimning o'zi bergan holat: yashil | sariq | qizil


def norm_key(text: str) -> str:
    """'Hujjat-Aylanishi' -> 'hujjataylanishi'"""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower().replace("'", "").replace("ʻ", "").replace("’", ""))


def clean_title(text: str) -> str:
    text = HASHTAG_RE.sub("", text)
    text = MENTION_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" \t-–—:;,.")
    if text:
        text = text[0].upper() + text[1:]
    return text[:160]


def line_deadline(line: str, today: date | None) -> tuple[date | None, str]:
    """Qatorda muddat bo'lsa: (sana, sanasiz qator). "Slaydlar 25-oktyabrgacha" -> (25.10, "Slaydlar")"""
    if today is None or not DEADLINE_CUE_RE.search(line):
        return None, line
    found = parse_date(line, today)
    if found is None:
        return None, line
    return found, re.sub(r"\s+", " ", DATE_PHRASE_RE.sub(" ", line)).strip()


def split_items(body: str, today: date | None = None) -> list[Item]:
    lines = [line for line in body.splitlines() if line.strip()]
    # Faqat @mention (va muddat) dan iborat qator, masalan "@ali 25-oktyabrgacha" — ro'yxatdagi hamma vazifaga tegishli
    alone, shared_due = [], None
    for line in lines:
        due, rest = line_deadline(line, today)
        if not clean_title(rest):
            alone += MENTION_RE.findall(line)
            shared_due = due or shared_due
    shared = "@" + alone[0] if len(set(alone)) == 1 else None
    items = []
    for line in lines:
        line = BULLET_RE.sub("", line)
        mentions = MENTION_RE.findall(line)
        due, line = line_deadline(line, today)
        title = clean_title(line)
        if not title:
            continue
        assignee = "@" + mentions[0] if mentions else shared
        items.append(Item(title, assignee, due or shared_due))
    return items


def parse_date(text: str, today: date) -> date | None:
    t = text.lower()
    candidates = []
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        candidates.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), True))
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", t)
    if m:
        year = m.group(3)
        y = int(year) + (2000 if year and len(year) == 2 else 0) if year else today.year
        candidates.append((y, int(m.group(2)), int(m.group(1)), bool(year)))
    m = re.search(r"\b(\d{1,2})[\s\-]*([a-zа-яё']{3,})", t)
    if m:
        for name, month in MONTHS.items():
            if m.group(2).startswith(name):
                candidates.append((today.year, month, int(m.group(1)), False))
                break
    for y, mo, d, has_year in candidates:
        try:
            result = date(y, mo, d)
        except ValueError:
            continue
        if not has_year and result < today - timedelta(days=60):
            result = date(y + 1, mo, d)
        return result
    if "indinga" in t:
        return today + timedelta(days=2)
    if "ertaga" in t:
        return today + timedelta(days=1)
    m = re.search(r"(\d{1,3})\s*(kun|hafta|oy)", t)
    if m:
        n = int(m.group(1)) * {"kun": 1, "hafta": 7, "oy": 30}[m.group(2)]
        return today + timedelta(days=n)
    return None


def parse_format(text: str, today: date) -> Parsed | None:
    """#task / #done / #muammo / #deadline bo'lsa aniq o'qiydi, bo'lmasa None."""
    kind = project = None
    for tag in HASHTAG_RE.findall(text):
        tag = tag.strip("-")
        found = TAG_KIND.get(tag.lower())
        if found and kind is None:
            kind = found
        elif not found and project is None and tag.lower() not in NOT_PROJECT:
            project = tag
    if kind is None:
        return None
    body = HASHTAG_RE.sub("", text)
    if kind == "deadline":
        return Parsed(kind, project, [], parse_date(body, today), "format")
    return Parsed(kind, project, split_items(body, today if kind == "task" else None), None, "format")


# ---------- kunlik hisobot ----------
# Xodimlar aynan shunday yozadi:
#   #shajara #backend
#   Sana: 22.10.2026
#   Bajarildi:
#   1. Tadqiqot arizasi statuslarini ... qo'shish. Sabab ...;
#   2. ...
SECTION_WORDS = {
    "done": ["bajarildi", "bajarilgan ishlar", "bajarilgan", "bugun bajarildi", "qilingan ishlar", "qilindi", "tugallandi",
             "yakunlandi", "выполнено", "сделано", "done"],
    "doing": ["jarayonda", "davom etmoqda", "bajarilmoqda", "ishlanmoqda", "в процессе", "в работе", "in progress"],
    "plan": ["reja", "rejada", "rejalar", "ertaga", "ertangi reja", "keyingi qadamlar", "keyingi ishlar", "rejalashtirilgan",
             "план", "планы", "todo", "plan"],
    "blocker": ["muammo", "muammolar", "to'siq", "to'siqlar", "qiyinchiliklar", "bloker", "blokerlar", "блокер", "блокеры",
                "проблемы", "проблема", "blocker", "blockers"],
}
APOS_RE = re.compile(r"[‘’ʻʼ`]")  # o‘, o’, oʻ — hammasi o'
# "Bloker: yo'q" — muammo yo'q; "Bloker: Ha — fayl berilmadi" — muammo "fayl berilmadi"
NO_BLOCKER_RE = re.compile(r"^(?:yo'?q|yoq|mavjud emas|hech qanday|нет|no|none|-+|—)[.!]?$", re.I)
YES_PREFIX_RE = re.compile(r"^(?:ha|bor|да|yes)\s*[—\-:,.]+\s*", re.I)
_SECTION_OF = {w: k for k, ws in SECTION_WORDS.items() for w in ws}
SECTION_RE = re.compile(r"^[\s*_]*(" + "|".join(sorted((re.escape(w) for w in _SECTION_OF), key=len, reverse=True))
                        + r")[\s*_]*(?::[\s*_]*(.*)|$)", re.I)
DATE_LINE_RE = re.compile(r"^[\s*_]*(?:sana|дата|date|kun)[\s*_]*[:\-—][\s*_]*(.+)$", re.I)
DEPT_TAGS = {"backend": "Backend", "frontend": "Frontend", "fullstack": "Fullstack", "devops": "DevOps", "ai": "AI", "ml": "AI",
             "dizayn": "Dizayn", "design": "Dizayn", "dizayner": "Dizayn", "uiux": "Dizayn", "qa": "Test (QA)", "tester": "Test (QA)",
             "testing": "Test (QA)", "mobile": "Fullstack"}


# Guruh nomidagi bo'lim: "Backend jamoasi", "Дизайн отдел", "QA guruhi" -> shu guruhda yozgan, bo'limi yo'q xodimga beriladi
TITLE_DEPTS = {**DEPT_TAGS, "бэкенд": "Backend", "бекенд": "Backend", "фронтенд": "Frontend", "фулстек": "Fullstack",
               "девопс": "DevOps", "дизайн": "Dizayn", "тест": "Test (QA)", "тестирование": "Test (QA)", "ии": "AI"}


def title_department(title: str | None) -> str | None:
    for w in re.findall(r"[^\W_]+", (title or "").lower()):
        if w in TITLE_DEPTS:
            return TITLE_DEPTS[w]
    return None


HOLAT_RE = re.compile(r"^[\s*_]*(?:holat|holati|статус|status)[\s*_]*[:\-—][\s*_]*(\w+)", re.I)
HOLAT_OF = {"yashil": "yashil", "green": "yashil", "зеленый": "yashil", "зелёный": "yashil",
            "sariq": "sariq", "yellow": "sariq", "желтый": "sariq", "жёлтый": "sariq",
            "qizil": "qizil", "red": "qizil", "красный": "qizil"}
PCT_TAIL_RE = re.compile(r"[\s(]*[—–\-:,]?\s*(\d{1,3})\s*%\s*\)?\s*$")
SPLIT_RE = re.compile(r"\s[—–]\s|;\s|:\s")  # uzun bandni ma'no chegarasidan bo'lish: tire, nuqtali vergul, ikki nuqta


def _title_note(text: str) -> tuple[str, str | None]:
    """Uzun bandning birinchi gapi sarlavha, qolgani izoh: "X qo'shish. Sabab ..." -> ("X qo'shish", "Sabab ...").
    Gap yo'q bo'lsa tire, nuqtali vergul yoki ikki nuqtadan bo'linadi: natija raqamlari ("5% → 79%") izohda butun qoladi."""
    text = re.sub(r"\s+", " ", text).strip().rstrip(";.")
    m = re.search(r"(?<=[^\s]{3})\.\s+(?=[A-ZА-ЯЎҚҒҲ'])", text)
    if m and m.start() >= 20 and len(text) > 90:
        return clean_title(text[:m.start()]), text[m.end():].strip()[:600] or None
    if len(text) > 90:
        cut = next((x for x in SPLIT_RE.finditer(text) if 20 <= x.start() <= 140), None)
        if cut:
            return clean_title(text[:cut.start()]), text[cut.end():].strip()[:600] or None
    if len(text) > 160:
        cut = text.rfind(" ", 0, 150)
        return clean_title(text[:cut if cut > 60 else 150]), text[cut if cut > 60 else 150:].strip()[:600] or None
    return clean_title(text), None


def parse_report(text: str, today: date) -> Parsed | None:
    """Bo'limli kunlik hisobot. Kamida bitta bo'lim sarlavhasi ("Bajarildi:") va unda band bo'lsa o'qiladi."""
    sections: dict[str, list[str]] = {}
    heads: dict[str, list[str]] = {}  # bandning birinchi qatori: qisqa bo'lsa (nomi), keyingi qatorlar uning tavsifi
    cur, day, holat = None, None, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        d = DATE_LINE_RE.match(line)
        if d and day is None:
            day = parse_date(d.group(1), today)
            continue
        hm = HOLAT_RE.match(line)
        if hm and cur is None:
            holat = HOLAT_OF.get(hm.group(1).lower(), holat)
            continue
        h = SECTION_RE.match(APOS_RE.sub("'", line))
        if h:
            cur = _SECTION_OF[h.group(1).lower()]
            sections.setdefault(cur, []); heads.setdefault(cur, [])
            if (h.group(2) or "").strip():
                sections[cur].append(h.group(2)); heads[cur].append(h.group(2))
            continue
        if cur is None:
            continue  # teglar qatori, salom va boshqalar
        body = HASHTAG_RE.sub("", line).strip()
        if not body:
            continue
        if BULLET_RE.match(raw) or not sections[cur]:
            sections[cur].append(BULLET_RE.sub("", line)); heads[cur].append(BULLET_RE.sub("", line))
        else:
            sections[cur][-1] += " " + body  # band davomi keyingi qatorda
    if sections.get("blocker"):
        sections["blocker"] = [YES_PREFIX_RE.sub("", b.strip()) for b in sections["blocker"]
                               if not NO_BLOCKER_RE.match(APOS_RE.sub("'", b.strip()))]
    sections = {k: v for k, v in sections.items() if v}
    tags = [t.strip("-") for t in HASHTAG_RE.findall(text)]
    # "#hisobot" faqat birinchi qator teglardan iborat bo'lsa hisobot belgisi ("#hisobot #Shajara"). Gap ichida tilga olinsa
    # ("#hisobot teg bilan yozilganda bot adashmaydi ...") bu tushuntirish, hisobot emas
    lead = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    lead_tags = HASHTAG_RE.findall(lead) if len(WORD_RE.findall(HASHTAG_RE.sub("", lead))) <= 2 else []
    tagged = any(t.strip("-").lower() in REPORT_TAGS for t in lead_tags)
    if not sections and tagged:
        # "#hisobot" bilan, lekin "Bajarildi:" sarlavhasisiz yozilgan: har band (yoki qator) bajarilgan ish
        done = []
        for raw in text.splitlines():
            body = HASHTAG_RE.sub("", raw).strip()
            if not body or DATE_LINE_RE.match(body):
                continue
            if BULLET_RE.match(raw) or not done:
                done.append(BULLET_RE.sub("", body))
            else:
                done[-1] += " " + body
        if done:
            sections["done"] = done
    if not sections:
        return None
    project = department = None
    for tag in tags:
        low = tag.lower()
        if low in DEPT_TAGS:
            department = department or DEPT_TAGS[low]
        elif low not in TAG_KIND and low not in NOT_PROJECT and project is None:
            project = tag
    parsed_sections = {}
    for k, raw_items in sections.items():
        items = []
        for n, it in enumerate(raw_items):
            mentions = MENTION_RE.findall(it)
            pct = None
            if k == "doing" and (pm := PCT_TAIL_RE.search(it)) and 0 <= int(pm.group(1)) <= 100:
                pct, it = int(pm.group(1)), it[:pm.start()]
            head = (heads.get(k) or [None] * len(raw_items))[n] if n < len(heads.get(k, [])) else None
            if head and len(head) <= 70 and len(it) - len(head) >= 60:
                # "1. 2000 ta xat sinovi" + keyingi qatorda uzun tafsilot: nomi birinchi qator, tafsiloti izoh
                # (qisqa davom — "Login sahifasi / mobil ko'rinishi ham tayyor" — bitta gapning qatorga sig'magan qismi)
                title, note = clean_title(head.rstrip(".:;")), re.sub(r"\s+", " ", it[len(head):]).strip()[:600] or None
            else:
                title, note = _title_note(it)
            if any(ch.isalnum() for ch in title):
                items.append(Item(title, "@" + mentions[0] if mentions and k in ("plan", "doing") else None, None, note, progress=pct))
        if items:
            parsed_sections[k] = items
    if not parsed_sections:
        return None
    if project is None and department is None and not tagged and sum(len(v) for v in parsed_sections.values()) == 1:
        return None  # tegsiz bitta qator ("Muammo: server ishlamayapti"): erkin matn, uni AI kontekst bilan yaxshiroq tushunadi
    kind = "done" if "done" in parsed_sections else "task" if ("plan" in parsed_sections or "doing" in parsed_sections) else "blocker"
    if day is not None and (day > today or day < today - timedelta(days=45)):
        day = None  # yozishda xato bo'lgan sana: xabar sanasi olinadi
    return Parsed(kind, project, parsed_sections.get("done") or parsed_sections.get("doing") or parsed_sections.get("plan") or [],
                  None, "format", sections=parsed_sections, day=day, department=department, holat=holat)


def detect_project(text: str, projects: list[dict]) -> str | None:
    """Erkin matnda qaysi loyiha haqida gap ketyapti. Bir nechtasi teng chiqsa None."""
    for tag in HASHTAG_RE.findall(text):
        key = norm_key(tag)
        if any(p["key"] == key for p in projects):
            return key
    tokens = words(text)
    best, best_score, tie = None, 0, False
    for p in projects:
        phrases = [p["name"], p["key"]] + [a for a in (p.get("aliases") or "").split(",") if a.strip()]
        score = 0
        for phrase in phrases:
            pt = [w for w in words(phrase) if len(w) >= 3]
            if not pt:
                continue
            for i in range(len(tokens) - len(pt) + 1):
                if all(tokens[i + j].startswith(pt[j]) for j in range(len(pt))):
                    # Xabar loyiha nomi bilan boshlansa ("Bulut bo'yicha: Monitoring agentlari"), gap o'sha loyiha haqida
                    score = max(score, sum(len(w) for w in pt) + (100 if i == 0 else 0))
                    break
        if score > best_score:
            best, best_score, tie = p["key"], score, False
        elif score and score == best_score:
            tie = True
    return None if tie else best


def strip_project(text: str, project: dict | None) -> str:
    if not project:
        return text
    for phrase in sorted([project["name"]] + (project.get("aliases") or "").split(","), key=len, reverse=True):
        phrase = phrase.strip()
        if len(phrase) < 3:
            continue
        pattern = r"^\s*" + r"\s*".join(map(re.escape, phrase.split())) + r"\w*(?:\s*(?:bo'yicha|uchun|loyihasi|loyihasida))?\s*[:\-—,]?\s*"
        new = re.sub(pattern, "", text, count=1, flags=re.I)
        if new != text:
            return new
    return text


def looks_like_work(text: str) -> bool:
    """Tegsiz xabar ishga oidmi. Qisqa xabar (5 so'zgacha) faqat ish belgisi bo'lsa: bajarildi / qilyapman / kerak /
    muammo / muddat / buyruq / ro'yxat / @xodim / foiz / teg. Belgisiz qisqa xabar ("marojna yedim", "ok", "rahmat",
    "tushlikka boramizmi") AI'ga yuborilmaydi. Uzunroq xabar har doim AI'ga boradi: ishni yo'qotgandan ko'ra
    bitta ortiqcha so'rov arzon. parse_free ish deb biladigan har belgi bu yerda ham bor."""
    t = text or ""
    if len(WORD_RE.findall(t)) >= 6:
        return True
    if HASHTAG_RE.search(t) or MENTION_RE.search(t) or PERCENT_RE.search(t):
        return True
    if any(r.search(t) for r in (DONE_RE, TASK_RE, BLOCKER_RE, RESOLVED_RE, DOING_RE, DEADLINE_CUE_RE, ORDER_RE, SOON_RE)):
        return True
    return sum(1 for line in t.splitlines() if BULLET_RE.match(line) and len(line.strip()) > 3) >= 2


def parse_free(text: str, projects: list[dict], today: date | None = None) -> Parsed:
    """AI bo'lmaganda: kalit so'zlar bilan taxmin."""
    due, rest = line_deadline(text, today)
    if BLOCKER_RE.search(text) and not RESOLVED_RE.search(text):
        kind = "blocker"
    elif DONE_RE.search(text):
        kind = "done"
    elif TASK_RE.search(rest) and any(len(w) > 3 for w in words(TASK_TAIL_RE.sub("", rest))):
        kind = "task"
    elif due is not None:
        # "25-oktyabrgacha bajarilsin": vazifa nomi yo'q, faqat muddat
        return Parsed("deadline", detect_project(text, projects), [], due, "taxmin")
    else:
        return Parsed("none", source="taxmin")
    key = detect_project(text, projects)
    project = next((p for p in projects if p["key"] == key), None)
    return Parsed(kind, key, extract_items(text, kind, project, today), None, "taxmin")


def extract_items(text: str, kind: str, project: dict | None, today: date | None = None) -> list[Item]:
    """Erkin matndan vazifa nomlari: loyiha nomi va "tugatdim / kerak" kabi qo'shimchalar olib tashlanadi."""
    lines = [line for line in HASHTAG_RE.sub("", text).splitlines() if line.strip()]
    if len(lines) > 1 and lines[0].rstrip().endswith(":"):
        lines = lines[1:]  # "Portal bo'yicha bugungi vazifalar:" sarlavha, vazifa emas
    items = []
    for item in split_items("\n".join(lines), today if kind == "task" else None):
        title = strip_project(item.title, project)
        tail = DONE_TAIL_RE if kind == "done" else TASK_TAIL_RE if kind == "task" else None
        while tail is not None:
            shorter = tail.sub("", title)
            if shorter == title:
                break
            title = shorter
        title = clean_title(title)
        if any(ch.isalnum() for ch in title):
            items.append(Item(title, item.assignee, item.deadline))
    return items


def stems(text: str) -> set[str]:
    return {w[:5] for w in words(text) if len(w) >= 3 and w not in STOP}


def match_score(task_title: str, text: str) -> float:
    """Bajarildi xabari qaysi ochiq vazifaga tegishli: 0..1"""
    t, m = stems(task_title), stems(text)
    if not t:
        return 0.0
    coverage = len(t & m) / len(t)
    ratio = SequenceMatcher(None, norm_key(task_title), norm_key(text)).ratio()
    return max(coverage, ratio)
