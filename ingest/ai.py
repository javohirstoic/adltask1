"""AI: format bo'lmagan erkin xabarni tushunadi (Gemini, Vertex AI orqali).

Model faqat JSON qaytaradi va loyihani faqat berilgan ro'yxatdan tanlay oladi:
o'zidan loyiha to'qiy olmaydi. Xato yoki internet bo'lmasa None qaytadi,
shunda dastur kalit so'zlar bilan ishlashda davom etadi.
"""
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import date

from django.conf import settings

from core import conf

from .parser import MENTION_RE, Item, Parsed, clean_title

log = logging.getLogger("puls.ai")
_lock = threading.Lock()
_creds = None
_gcp_project = None

KINDS = ("task", "done", "blocker", "deadline", "reassign", "none")
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "kind": {"type": "STRING", "enum": list(KINDS)},
        "project": {"type": "STRING", "nullable": True},
        "refs": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "assignee": {"type": "STRING", "nullable": True},
                    "deadline": {"type": "STRING", "nullable": True},
                },
                "required": ["title"],
            },
        },
        "deadline": {"type": "STRING", "nullable": True},
    },
    "required": ["kind", "items"],
}

HEAD = """You read messages from a work chat of an Uzbek government IT team. People write the way they talk: Uzbek (Latin or
Cyrillic), Russian or mixed, with typos, without tags, often as a reply to an earlier message, or naming a colleague by first
name instead of @username. Understand each message the way an experienced team lead would and return JSON.

kind:
- "task": new work is assigned or planned.
- "done": work has been completed (past tense: tugatdim, bajarildi, tayyor bo'ldi, qildim, yakunlandi, ishga tushirildi,
  topshirdim, готово). A completed item is "done" even when its title contains words like "testlar" or "xatolarni tuzatish".
- "blocker": a problem that stops the work (server down, no access, waiting for someone, error).
- "deadline": the message sets or moves a due date ("25-oktyabrgacha bajarilsin", "juma kuni tayyor bo'lsin",
  "muddatni keyingi haftaga suramiz"). If it is about specific existing tasks, put their ids in refs; if it is about the
  whole project, leave refs empty.
- "reassign": existing work is handed to another person ("buni Sardor qilsin", "Elyorga o'tkazamiz"). Put the task ids in
  refs and the new person as the assignee of a single item.
- "none": greetings, thanks, questions, jokes, meeting notes, anything that is not a work report.

project: choose ONLY one key from the list below, or null if the project is not clear. Never invent a key.
{projects}

refs: ids of existing open tasks (from "Open tasks" below) that this message is about: the tasks it completes, gives a
deadline to, or hands over. A reply to a task message is about that message's tasks. Use only listed ids. If you are not
sure which task is meant, leave refs empty: never guess.
items: for "task" every separate new piece of work, for "done" every completed piece of work, as a short title in the
original language, at most 80 characters, without the project name, the date, and words like "tugatdim" or "kerak".
Write the title as a complete noun phrase in the base form that a manager understands out of context: "Hisobot shaklini
yangilash" or "Hisobot shakli", never a cut object form like "Hisobot shaklini".
Use an empty list for "none" and "deadline".
assignee: who must do the item: the @username written in the message, or the @username of a team member mentioned by
name (see Team). null if nobody is named.
deadline (item and top level): YYYY-MM-DD. Resolve relative dates ("ertaga", "juma kuni", "keyingi haftaga",
"oy oxirigacha") from today, {today}, {weekday}. Item deadline only when the message gives a date for that work.

Examples:
"Portal: login sahifasi tayyor bo'ldi, testga berdim" -> {{"kind":"done","project":"portal","refs":[],"items":[{{"title":"Login sahifasi","assignee":null,"deadline":null}}],"deadline":null}}
"Arxiv uchun skaner modulini @demo_aziz qilsin, OCR ham kerak" -> {{"kind":"task","project":"arxiv","refs":[],"items":[{{"title":"Skaner moduli","assignee":"@demo_aziz","deadline":null}},{{"title":"OCR","assignee":null,"deadline":null}}],"deadline":null}}
"test serverga ruxsat hali yo'q, ishlay olmayapmiz" -> {{"kind":"blocker","project":null,"refs":[],"items":[{{"title":"Test serverga ruxsat yo'q","assignee":null,"deadline":null}}],"deadline":null}}
"Rahmat, ertaga 10:00 da yig'ilish" -> {{"kind":"none","project":null,"refs":[],"items":[],"deadline":null}}
"""

PROMPT = HEAD + """
Context of this chat:
{context}

Author: {author}
Message:
\"\"\"{text}\"\"\"
"""

WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]

# Ko'p xabarni bitta so'rovda o'qish (namuna keshini to'ldirish uchun: so'rovlar soni kvotaga sig'sin)
BATCH_PROMPT = HEAD + """Several separate messages follow, each with its number and author. Read every message on its own.
Return {{"results": [...]}}: one object per message, in the same order, where "i" is the message number.

{messages}
"""
BATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {"results": {"type": "ARRAY", "items": {
        "type": "OBJECT", "properties": {"i": {"type": "INTEGER"}, **SCHEMA["properties"]}, "required": ["i", "kind", "items"]}}},
    "required": ["results"],
}


def _token() -> str:
    global _creds, _gcp_project
    with _lock:
        if _creds is None:
            from google.oauth2 import service_account

            _creds = service_account.Credentials.from_service_account_file(
                settings.GEMINI_SA, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            with open(settings.GEMINI_SA, encoding="utf-8") as f:
                _gcp_project = json.load(f)["project_id"]
        if not _creds.valid:
            from google.auth.transport.requests import Request

            _creds.refresh(Request())
        return _creds.token


def _call(prompt: str | list, schema: dict = SCHEMA, think: int = 0) -> dict:
    """prompt: matn yoki tayyor qismlar ro'yxati (masalan, ovoz fayli + ko'rsatma)."""
    return _call_model(settings.GEMINI_MODEL, prompt, schema, think)


def _call_model(model: str, prompt: str | list, schema: dict, think: int, timeout: float | None = None,
                studio: bool = False) -> dict:
    """studio=True: AI Studio kaliti (GEMINI_API_KEY) orqali; aks holda Vertex xizmat hisobi orqali."""
    if studio:
        url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
        auth = {"x-goog-api-key": settings.GEMINI_API_KEY}
    else:
        url = (
            "https://aiplatform.googleapis.com/v1/projects/%s/locations/global/publishers/google/models/%s:generateContent"
            % (_gcp_project, model)
        )
        auth = {"Authorization": "Bearer " + _token()}
    parts = prompt if isinstance(prompt, list) else [{"text": prompt}]
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": schema,
            # Gemini 3.x da o'ylash darajasi so'z bilan beriladi (ovozli kirishda raqamli budjet rad etiladi)
            "thinkingConfig": ({"thinkingLevel": "low" if think else "minimal"} if model.startswith("gemini-3")
                               else {"thinkingBudget": think}),
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **auth},
    )
    timeout = timeout or (90 if schema in (BATCH_SCHEMA, MEDIA_SCHEMA) else 30)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])


def _plist(projects: list[dict]) -> str:
    return "\n".join(
        "- %s: %s%s" % (p["key"], p["name"], " (also called: %s)" % p["aliases"] if p.get("aliases") else "")
        for p in projects
    ) or "- (no projects yet)"


def _ask(prompt: str | list, retries: int, schema: dict = SCHEMA, think: int = 0) -> dict | None:
    """Asosiy model band bo'lsa yoki javob bermasa (429, 5xx, timeout), navbatdagi urinish zaxira modelda bo'ladi.
    AI Studio kaliti bo'lsa asosiy model shu kalit orqali, zaxira esa doim Vertex orqali (kalit limiti tugasa ham ishlaydi)."""
    studio = bool(settings.GEMINI_API_KEY)
    routes = [(settings.GEMINI_MODEL, studio)]
    if settings.GEMINI_FALLBACK != settings.GEMINI_MODEL or studio:
        routes.append((settings.GEMINI_FALLBACK, False))
    for attempt in range(retries + 1):
        model, via_studio = routes[min(attempt, len(routes) - 1)]
        try:
            # jonli xabarda bot kuttirmasin: asosiy modelga 20 soniya, keyin zaxira
            return _call_model(model, prompt, schema, think, 20 if attempt == 0 and schema is SCHEMA else None, via_studio)
        except urllib.error.HTTPError as e:
            # 429 — so'rov ko'p, 5xx — Google tomonda vaqtinchalik xato; AI Studio kalitining har qanday xatosi (limit,
            # bekor qilingan kalit) — darhol Vertex zaxirasiga
            if (e.code == 429 or e.code >= 500 or via_studio) and attempt < retries:
                if via_studio:
                    log.info("AI Studio kaliti ishlamadi (HTTP %s), Vertex zaxirasiga o'tiladi", e.code)
                    continue
                time.sleep(1 if attempt == 0 else 2 * attempt ** 2)
                continue
            log.warning("AI ishlamadi (%s, HTTP %s), kalit so'zlarga o'tiladi", model, e.code)
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries:
                log.info("%s javob bermadi (%s), zaxira modelga o'tiladi", model, e)
                continue
            log.warning("AI ishlamadi, kalit so'zlarga o'tiladi: %s", e)
            return None
        except (KeyError, ValueError) as e:
            log.warning("AI javobi o'qilmadi, kalit so'zlarga o'tiladi: %s", e)
            return None
    return None


MEDIA_PROMPT = """This file was posted in a work chat of an Uzbek government IT team{caption}.
Return JSON {{"text": ...}} with what the file says, so that a colleague who cannot open it understands it:
- voice or video message: the exact words in the original language (Uzbek in Latin script, Russian as spoken). No comments.
- image: if it shows text, an error, a document, a schedule or a task list, write that content briefly in Uzbek;
  otherwise describe in one short Uzbek sentence what is shown.
Empty string if nothing can be understood."""
MEDIA_SCHEMA = {"type": "OBJECT", "properties": {"text": {"type": "STRING"}}, "required": ["text"]}


def transcribe(data: bytes, mime: str, caption: str = "") -> str | None:
    """Ovozli xabar, video-xabar yoki rasmni matnga aylantiradi (Gemini o'zi eshitadi va ko'radi)."""
    if not conf.ai_enabled() or not data:
        return None
    import base64
    prompt = MEDIA_PROMPT.format(caption=' with the caption "%s"' % caption[:500] if caption else "")
    parts = [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}, {"text": prompt}]
    raw = _ask(parts, 2, MEDIA_SCHEMA)
    return ((raw or {}).get("text") or "").strip() or None


def context_text(ctx: dict) -> str:
    """ctx: team [(ism, username)], tasks [dict], reply {author, text, task_ids} — modelga o'qiladigan matn."""
    out = ["Team (name -> @username):"]
    out += ["- %s -> @%s" % (n, u) for n, u in ctx.get("team", []) if u] or ["- (unknown)"]
    out.append("Open tasks, including old ones (id | title | who does it | project | given on | due date):")
    out += ["- %d | %s | %s | %s | %s | %s" % (t["id"], t["title"], t["assignee"] or "-", t["project"] or "-",
                                             t.get("created") or "-", t["deadline"] or "-")
            for t in ctx.get("tasks", [])] or ["- (none)"]
    r = ctx.get("reply")
    if r:
        out.append('This message is a reply to %s: """%s"""%s' % (
            r["author"] or "someone", r["text"][:600],
            " (tasks of that message: %s)" % ", ".join(map(str, r["task_ids"])) if r.get("task_ids") else ""))
    return "\n".join(out)


def extract(text: str, author: str, projects: list[dict], today: date, retries: int = 1,
            context: dict | None = None) -> Parsed | None:
    if not conf.ai_enabled():
        return None
    ctx = context or {}
    prompt = PROMPT.format(projects=_plist(projects), today=today.isoformat(), weekday=WEEKDAYS[today.weekday()],
                           context=context_text(ctx), author=author, text=text[:2000])
    raw = _ask(prompt, retries, think=1024)  # bitta jonli xabar: kontekstni o'ylab ko'rishga imkon beramiz
    valid = {t["id"] for t in ctx.get("tasks", [])}
    return None if raw is None else _normalize(raw, projects, valid)


def extract_many(messages: list[tuple[str, str]], projects: list[dict], today: date, retries: int = 5) -> list[Parsed | None]:
    """messages: [(matn, muallif), ...]. Natija shu tartibda; o'qilmagani None."""
    out: list[Parsed | None] = [None] * len(messages)
    if not conf.ai_enabled() or not messages:
        return out
    body = "\n\n".join('%d. Author: %s\n\"\"\"%s\"\"\"' % (i + 1, a, t[:1500]) for i, (t, a) in enumerate(messages))
    raw = _ask(BATCH_PROMPT.format(projects=_plist(projects), today=today.isoformat(), weekday=WEEKDAYS[today.weekday()],
                                   messages=body), retries, BATCH_SCHEMA)
    for r in (raw or {}).get("results") or []:
        i = r.get("i")
        if isinstance(i, int) and 1 <= i <= len(messages) and out[i - 1] is None:
            out[i - 1] = _normalize(r, projects)
    return out


def _date(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _normalize(raw: dict, projects: list[dict], valid_refs: set[int] | None = None) -> Parsed:
    kind = raw.get("kind") if raw.get("kind") in KINDS else "none"
    keys = {p["key"] for p in projects}
    project = raw.get("project") if raw.get("project") in keys else None
    # Model faqat unga ko'rsatilgan vazifalarga ishora qila oladi: to'qilgan raqam qabul qilinmaydi
    refs = [r for r in raw.get("refs") or [] if isinstance(r, int) and valid_refs and r in valid_refs]
    items = []
    for it in raw.get("items") or []:
        title = clean_title(str(it.get("title") or ""))[:120]
        assignee = it.get("assignee")
        if assignee and not assignee.startswith("@"):
            assignee = "@" + assignee
        if assignee and not MENTION_RE.fullmatch(assignee):
            assignee = None
        if title:
            items.append(Item(title, assignee, _date(it.get("deadline")) if kind == "task" else None))
    deadline = _date(raw.get("deadline")) if kind == "deadline" else None
    if kind == "deadline" and deadline is None:
        kind = "none"
    if kind == "reassign" and not (refs and items and items[0].assignee):
        kind = "none"  # kimga yoki qaysi ish ekani aniq bo'lmasa, hech narsa o'zgartirilmaydi
    return Parsed(kind, project, items if kind not in ("none", "deadline") else [], deadline, "ai", refs)
