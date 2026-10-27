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

from . import config
from .parser import MENTION_RE, Item, Parsed, clean_title

log = logging.getLogger("puls.ai")
_lock = threading.Lock()
_creds = None
_gcp_project = None

KINDS = ("task", "done", "blocker", "request", "deadline", "reassign", "none")
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "kind": {"type": "STRING", "enum": list(KINDS)},
        "project": {"type": "STRING", "nullable": True},
        "refs": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "solves": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "assignee": {"type": "STRING", "nullable": True},
                    "deadline": {"type": "STRING", "nullable": True},
                    "same_as": {"type": "INTEGER", "nullable": True},
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
- "blocker": a problem that stops the author's own work (no access, waiting for someone, server down for them).
- "request": an incoming issue for the project team: a bug or error someone reports ("kabinetda arizalar bo'sh chiqyapti",
  "pdf yuklanmayapti, 413 beryapti") or a request to fix or change something, without a named person who takes it.
  A request that names who must do it, or that someone accepts, is "task".
- "deadline": the message sets or moves a due date ("25-oktyabrgacha bajarilsin", "juma kuni tayyor bo'lsin",
  "muddatni keyingi haftaga suramiz"). If it is about specific existing tasks, put their ids in refs; if it is about the
  whole project, leave refs empty.
- "reassign": existing work is handed to another person ("buni Sardor qilsin", "Elyorga o'tkazamiz"). Put the task ids in
  refs and the new person as the assignee of a single item.
- "none": greetings, thanks, questions, jokes, meeting notes, anything that is not a work report.
A polite request to do work is "task" even as a question ("sms modulini siz davom ettira olasizmi?", "vaqtingiz bormi,
pdf ni qarab bering"); its assignee is the person asked (the author of the replied message, or the one named), else null.
Agreeing to take such work ("mayli olaman", "men qilaman", "jumagacha bitkazaman" as a reply) is "task" for the author
with the same title as the requested work and the promised date as its deadline.
Read the earlier messages of the chat like a colleague who follows it: they tell what a short message is about.

project: choose ONLY one key from the list below, or null if the project is not clear. Never invent a key.
{projects}

refs: ids of existing open tasks (from "Open tasks" below) that this message is about: the tasks it completes, gives a
deadline to, or hands over. A reply to a task message is about that message's tasks. Use only listed ids. If you are not
sure which task is meant, leave refs empty: never guess. For "done", refs are only tasks the message says are finished:
taking a task over, starting it or reading its code ("oldim", "boshladim", "kodini ko'rib chiqdim") does not finish it.
solves: ids from "Open problems and requests" that this message reports as fixed, even when a colleague reported the
problem and the author does not reply to it ("arizalar bo'sh chiqyapti" earlier, "api ni to'g'riladim, filtr noto'g'ri
ekan" now). A reply to a problem message is about that problem. When the author only says that others removed their own
problem ("dostup berishdi", "server ishladi"), it is not their work: kind "none", no items, but the id still goes to solves.
Use only listed ids; empty when unsure.
items: for "task" every separate new piece of work, for "done" every completed piece of work, as a short title in the
original language, at most 80 characters, without the project name, the date, and words like "tugatdim" or "kerak".
Write the title as a complete noun phrase in the base form that a manager understands out of context: "Hisobot shaklini
yangilash" or "Hisobot shakli", never a cut object form like "Hisobot shaklini". Keep what the person really did:
"xatoni ko'rib chiqdim" gives "Xatoni ko'rib chiqish", never "Xatoni tuzatish".
Use an empty list for "none" and "deadline".
assignee: who must do the item: the @username written in the message, or the @username of a team member mentioned by
name (see Team). null if nobody is named.
deadline (item and top level): YYYY-MM-DD. Resolve relative dates ("ertaga", "juma kuni", "keyingi haftaga",
"oy oxirigacha") from today, {today}, {weekday}. Item deadline only when the message gives a date for that work.
same_as (only for "done" items): the id from "Already reported today" when this item is the same piece of work that is
already there under other words: an evening summary repeating what the author wrote in the chat earlier, or a result a
colleague already reported. Read the chat context: "api filtrini tuzatdim" earlier and "arizalar bo'sh chiqayotgan edi,
tuzatdim" in the evening can be the same fix. A next stage, a different part or the author's own review or testing of a
colleague's work is not the same: then null. null when unsure.

Examples:
"Portal: login sahifasi tayyor bo'ldi, testga berdim" -> {{"kind":"done","project":"portal","refs":[],"items":[{{"title":"Login sahifasi","assignee":null,"deadline":null}}],"deadline":null}}
"Arxiv uchun skaner modulini @demo_aziz qilsin, OCR ham kerak" -> {{"kind":"task","project":"arxiv","refs":[],"items":[{{"title":"Skaner moduli","assignee":"@demo_aziz","deadline":null}},{{"title":"OCR","assignee":null,"deadline":null}}],"deadline":null}}
"test serverga ruxsat hali yo'q, ishlay olmayapmiz" -> {{"kind":"blocker","project":null,"refs":[],"items":[{{"title":"Test serverga ruxsat yo'q","assignee":null,"deadline":null}}],"deadline":null}}
"Rahmat, ertaga 10:00 da yig'ilish" -> {{"kind":"none","project":null,"refs":[],"items":[],"deadline":null}}
"""

PROMPT = HEAD + """
Context of this chat:
{context}

Author: {author}{role}
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
                config.GEMINI_SA, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            with open(config.GEMINI_SA, encoding="utf-8") as f:
                _gcp_project = json.load(f)["project_id"]
        if not _creds.valid:
            from google.auth.transport.requests import Request

            _creds.refresh(Request())
        return _creds.token


def _call(prompt: str | list, schema: dict = SCHEMA, think: int = 0) -> dict:
    """prompt: matn yoki tayyor qismlar ro'yxati (masalan, ovoz fayli + ko'rsatma)."""
    return _call_model(config.GEMINI_MODEL, prompt, schema, think)


def _call_model(model: str, prompt: str | list, schema: dict, think: int, timeout: float | None = None,
                studio: bool = False) -> dict:
    """studio=True: AI Studio kaliti (GEMINI_API_KEY) orqali; aks holda Vertex xizmat hisobi orqali."""
    if studio:
        url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
        auth = {"x-goog-api-key": config.GEMINI_API_KEY}
    else:
        auth = {"Authorization": "Bearer " + _token()}  # avval token: loyiha nomi (_gcp_project) shu yerda o'qiladi
        url = (
            "https://aiplatform.googleapis.com/v1/projects/%s/locations/global/publishers/google/models/%s:generateContent"
            % (_gcp_project, model)
        )
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


def _ask(prompt: str | list, retries: int, schema: dict = SCHEMA, think: int = 0, first_timeout: float | None = None) -> dict | None:
    """Asosiy model band bo'lsa yoki javob bermasa (429, 5xx, timeout), navbatdagi urinish zaxira modelda bo'ladi.
    AI Studio kaliti bo'lsa asosiy model shu kalit orqali, zaxira esa doim Vertex orqali (kalit limiti tugasa ham ishlaydi)."""
    studio = bool(config.GEMINI_API_KEY)
    routes = [(config.GEMINI_MODEL, studio)]
    if config.GEMINI_FALLBACK != config.GEMINI_MODEL or studio:
        routes.append((config.GEMINI_FALLBACK, False))
    for attempt in range(retries + 1):
        model, via_studio = routes[min(attempt, len(routes) - 1)]
        try:
            # jonli xabarda bot kuttirmasin: asosiy modelga 20 soniya, keyin zaxira
            # birinchi urinish qotib qolsa uzoq kutilmaydi: rahbar jonli kutayotgan joyda (agent) qisqa vaqt beriladi
            first = first_timeout or (20 if schema is SCHEMA else None)
            return _call_model(model, prompt, schema, think, first if attempt == 0 else None, via_studio)
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


# ---------- lokal model (llama.cpp / Ollama / vLLM): OpenAI'ga mos /v1/chat/completions ----------

def json_schema(s: dict) -> dict:
    """Gemini sxemasi (OBJECT, STRING, nullable) -> JSON Schema: lokal server javobni shu qolipga majburan soladi."""
    t = (s.get("type") or "").lower()
    if t == "object":
        out = {"type": "object", "properties": {k: json_schema(v) for k, v in (s.get("properties") or {}).items()}}
        if s.get("required"):
            out["required"] = list(s["required"])
    elif t == "array":
        out = {"type": "array", "items": json_schema(s.get("items") or {"type": "STRING"})}
    else:
        out = {"type": {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}.get(t, "string")}
    if s.get("enum"):
        out["enum"] = list(s["enum"]) + ([None] if s.get("nullable") else [])
    if s.get("nullable"):
        out["type"] = [out["type"], "null"]
    return out


def _call_local(prompt: str, schema: dict, max_tokens: int = 600, timeout: float | None = None) -> dict:
    body = {
        "model": config.LOCAL_AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_schema", "json_schema": {"name": "javob", "schema": json_schema(schema)}},
        "chat_template_kwargs": {"enable_thinking": False},  # o'ylash yoqilsa, tokenlar o'ylashga ketib javob bo'sh qoladi
        "cache_prompt": True,  # ko'rsatmaning o'zgarmas boshi qayta hisoblanmaydi (sekin protsessorda muhim)
    }
    auth = {"Authorization": "Bearer " + config.LOCAL_AI_KEY} if config.LOCAL_AI_KEY else {}
    req = urllib.request.Request(config.LOCAL_AI_URL.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **auth})
    with urllib.request.urlopen(req, timeout=timeout or config.LOCAL_AI_TIMEOUT) as resp:
        data = json.loads(resp.read())
    return json.loads(data["choices"][0]["message"]["content"])


LOADING_WAIT = 240  # model yuklanayotganda (llama.cpp 503 qaytaradi) shuncha soniyagacha kutiladi


def ask_local(prompt: str, schema: dict, retries: int = 1, max_tokens: int = 600) -> dict | None:
    if not config.LOCAL_AI_URL:
        return None
    attempt, waited = 0, 0
    while attempt <= retries:
        try:
            return _call_local(prompt, schema, max_tokens)
        except urllib.error.HTTPError as e:
            if e.code == 503 and waited < LOADING_WAIT:  # qayta ishga tushgan model hali yuklanmoqda: bu xato emas, kutiladi
                time.sleep(5)
                waited += 5
                continue
            log.warning("lokal model javob bermadi (%s/%s): %s", attempt + 1, retries + 1, e)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.warning("lokal model javob bermadi (%s/%s): %s", attempt + 1, retries + 1, e)
        except (KeyError, IndexError, ValueError) as e:
            log.warning("lokal model javobi o'qilmadi: %s", e)
        attempt += 1
    return None


def ask_appeals(prompt: str, schema: dict, retries: int = 1, max_tokens: int = 600) -> dict | None:
    """Murojaatlar (fuqarolar yozgan matn) uchun: APPEALS_AI=local bo'lsa faqat lokal model — matn serverdan chiqmaydi."""
    if config.APPEALS_AI == "local":
        return ask_local(prompt, schema, retries, max_tokens)
    if config.APPEALS_AI == "gemini" and config.ai_enabled():
        return _ask(prompt, retries, schema)
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
    if not config.ai_enabled() or not data:
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
    if ctx.get("chat"):
        out.append("Earlier messages in this chat today (time | who | text):")
        out += ["- %s | %s | %s" % (m["time"], m["who"], m["text"]) for m in ctx["chat"]]
    if ctx.get("problems"):
        out.append("Open problems and requests in this chat (id | kind | text | who reported | when):")
        out += ["- %d | %s | %s | %s | %s" % (b["id"], b.get("kind") or "muammo", b["text"], b["author"] or "-", b["at"])
                for b in ctx["problems"]]
    if ctx.get("today"):
        out.append("Already reported today in this chat (id | title | who did it | time | their message | problem it fixed):")
        out += ["- %d | %s | %s | %s | %s | %s" % (t["id"], t["title"], t["assignee"] or "-", t["time"], t.get("said") or "-",
                                                  "; ".join(t.get("solved") or []) or "-") for t in ctx["today"]]
    r = ctx.get("reply")
    if r:
        out.append('This message is a reply to %s: """%s"""%s' % (
            r["author"] or "someone", r["text"][:600],
            " (tasks of that message: %s)" % ", ".join(map(str, r["task_ids"])) if r.get("task_ids") else ""))
    return "\n".join(out)


LEAD = (" (the team lead: an instruction from them is an order to the team. A task they give without naming a person has "
        "assignee null, it is not their own work; only work they say they will do themselves is theirs)")


def extract(text: str, author: str, projects: list[dict], today: date, retries: int = 1,
            context: dict | None = None, lead: bool = False) -> Parsed | None:
    if not config.ai_enabled():
        return None
    ctx = context or {}
    prompt = PROMPT.format(projects=_plist(projects), today=today.isoformat(), weekday=WEEKDAYS[today.weekday()],
                           context=context_text(ctx), author=author, role=LEAD if lead else "", text=text[:2000])
    raw = _ask(prompt, retries, think=1024)  # bitta jonli xabar: kontekstni o'ylab ko'rishga imkon beramiz
    valid = {t["id"] for t in ctx.get("tasks", [])}
    return None if raw is None else _normalize(raw, projects, valid, {t["id"] for t in ctx.get("today", [])},
                                                {b["id"] for b in ctx.get("problems", [])})


def extract_many(messages: list[tuple[str, str]], projects: list[dict], today: date, retries: int = 5) -> list[Parsed | None]:
    """messages: [(matn, muallif), ...]. Natija shu tartibda; o'qilmagani None."""
    out: list[Parsed | None] = [None] * len(messages)
    if not config.ai_enabled() or not messages:
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


def _normalize(raw: dict, projects: list[dict], valid_refs: set[int] | None = None, today_ids: set[int] | None = None,
               problem_ids: set[int] | None = None) -> Parsed:
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
        same = it.get("same_as")
        same = same if kind == "done" and isinstance(same, int) and today_ids and same in today_ids else None
        if title:
            items.append(Item(title, assignee, _date(it.get("deadline")) if kind in ("task", "reassign") else None, same_as=same))
    deadline = _date(raw.get("deadline")) if kind in ("deadline", "reassign") else None
    if kind == "deadline" and deadline is None:
        kind = "none"
    if kind == "reassign" and not (refs and items and items[0].assignee):
        kind = "none"  # kimga yoki qaysi ish ekani aniq bo'lmasa, hech narsa o'zgartirilmaydi
    solves = [b for b in raw.get("solves") or [] if isinstance(b, int) and problem_ids and b in problem_ids] \
        if kind in ("done", "none") else []
    return Parsed(kind, project, items if kind not in ("none", "deadline") else [], deadline, "ai", refs, solves=solves)
