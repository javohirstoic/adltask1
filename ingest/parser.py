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
    r"\b(?:bajar|tugat|tugall|yakunla|tuzat|topshir|ula|yop|o'rnat|yoz|qo'sh|chiqar|tekshir|sozla|jo'nat)\w*"
    r"(?:dim|di|ldi|ndi|dik|ildi|ilindi|ishdi)\b|"
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
TASK_TAIL_RE = re.compile(r"[\s,.:;—-]*(?:ni|ham)?\s*(?:qilish kerak|kerak|lozim|qilinsin|qiling|olsin)[\s,.!]*$", re.I)
STOP = {"va", "bilan", "uchun", "ham", "ni", "bo'yicha", "boyicha", "bugun", "kecha", "ertaga", "the", "and"}


@dataclass
class Item:
    title: str
    assignee: str | None = None  # "@username" yoki None
    deadline: date | None = None  # shu vazifaning muddati


@dataclass
class Parsed:
    kind: str                     # task | done | blocker | deadline | reassign | none
    project: str | None = None    # teg yoki loyiha kaliti
    items: list[Item] = field(default_factory=list)
    deadline: date | None = None
    source: str = "format"        # format | ai | taxmin
    refs: list[int] = field(default_factory=list)  # gap ketayotgan mavjud vazifalar (tasks.id), AI kontekstdan topadi


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
        elif not found and project is None:
            project = tag
    if kind is None:
        return None
    body = HASHTAG_RE.sub("", text)
    if kind == "deadline":
        return Parsed(kind, project, [], parse_date(body, today), "format")
    return Parsed(kind, project, split_items(body, today if kind == "task" else None), None, "format")


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
