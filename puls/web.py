"""Veb panel va API (FastAPI)."""
import io
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import actions, analytics, auth, board, config, db, settings
from .ingest import Incoming, ingest

WEB = config.ROOT / "web"
COOKIE = "puls_kirish"
app = FastAPI(title="Puls", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=WEB), name="static")
_attempts: dict[str, list[float]] = defaultdict(list)
OPEN = ("/login", "/api/login", "/favicon.ico", "/api/appeals/push")  # push: chatbot o'z kaliti bilan kiradi (panel login emas)
# Faqat o'z kompyuterida sinash uchun (PANEL_OPEN=1 va bazada hali akkaunt yo'q): panel kirishsiz ochiladi
LOCAL = {"id": 0, "login": "local", "name": "Mahalliy rejim", "role": auth.ADMIN, "role_label": auth.ROLES[auth.ADMIN], "person": None,
         "active": True, "projects": [], "can": sorted(auth.PERMS[auth.ADMIN]), "local": True}


def _prefix(request: Request) -> str:
    return request.headers.get("x-forwarded-prefix", "").rstrip("/")


@app.middleware("http")
async def guard(request: Request, call_next):
    """Login va parolsiz na panel, na API ochiladi. Kim kirgani request.state.acc da (rol va loyihalari bilan)."""
    path = request.url.path
    acc = None
    if path not in OPEN and not path.startswith("/static/"):
        with db.session() as conn:
            acc = auth.account_by_token(conn, request.cookies.get(COOKIE))
            if acc is None and config.PANEL_OPEN and not auth.has_accounts(conn):
                acc = LOCAL
        if acc is None:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "kirish kerak"}, status_code=401)
            return RedirectResponse(_prefix(request) + "/login", status_code=302)
    request.state.acc = acc
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if path.startswith("/static/") and path.endswith((".js", ".css", ".html")):
        # brauzer har safar tekshirsin (o'zgarmagan bo'lsa 304): yangi versiyadan keyin eski kod qolib ketmaydi
        response.headers["Cache-Control"] = "no-cache"
    return response


def _page(name: str) -> FileResponse:
    return FileResponse(WEB / name, headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    """Asosiy panel: chap menyu, "Kunlik holat", loyihalar, xodimlar va biriktirilgan yordamchi."""
    return _page("v2.html")


@app.get("/v2")
def index_v2():
    return _page("v2.html")


@app.get("/v1")
def index_v1():
    """Birinchi variant (zaxira sifatida qoldirilgan)."""
    return _page("index.html")


@app.get("/taqdimot")
def slides():
    return _page("taqdimot.html")


@app.get("/login")
def login_page():
    return _page("login.html")


def me(request: Request) -> dict:
    return request.state.acc


def need(perm: str):
    """Rol ruxsati: auth.PERMS jadvali bo'yicha (panel ham shu jadvalga qarab tugmalarni ko'rsatadi)."""
    def check(request: Request) -> dict:
        if not auth.can(request.state.acc, perm):
            raise HTTPException(403, "Bu amal sizning rolingiz uchun ochiq emas")
        return request.state.acc
    return Depends(check)


def _scope(request: Request) -> set[int] | None:
    return auth.scope(request.state.acc)


def _dept(request: Request) -> str | None:
    """Bo'lim paneli: ?dept=Backend bo'lsa hamma hisob shu bo'lim bilan cheklanadi."""
    d = (request.query_params.get("dept") or "").strip()
    return d if d in db.DEPARTMENTS + ["Belgilanmagan"] else None


def _limit(key: str) -> None:
    now = time.time()
    _attempts[key] = [t for t in _attempts[key] if now - t < 300]
    if len(_attempts[key]) >= 8:
        raise HTTPException(429, "Ko'p urinish. 5 daqiqadan keyin qayta urinib ko'ring")


def _ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()


def _signed_in(request: Request, acc) -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, auth.make_token(acc), max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=request.headers.get("x-forwarded-proto") == "https", path=_prefix(request) + "/")
    return resp


class Credentials(BaseModel):
    login: str
    password: str


@app.post("/api/login")
def login(body: Credentials, request: Request):
    ip, who = _ip(request), "u:" + body.login.strip().lower()
    _limit(ip)
    _limit(who)
    with db.session() as conn:
        try:
            acc = auth.login(conn, body.login, body.password)
        except PermissionError as e:
            raise HTTPException(403, str(e))
    if acc is None:
        _attempts[ip].append(time.time())
        _attempts[who].append(time.time())
        raise HTTPException(401, "Login yoki parol noto'g'ri")
    return _signed_in(request, acc)


@app.post("/api/logout")
def logout(request: Request):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path=_prefix(request) + "/")
    return resp


@app.get("/api/me")
def get_me(acc=Depends(me)):
    return acc


class NewPassword(BaseModel):
    old: str
    new: str


@app.post("/api/me/password")
def my_password(body: NewPassword, request: Request, acc=Depends(me)):
    if acc.get("local"):
        raise HTTPException(400, "Mahalliy rejimda parol yo'q")
    key = "p:%d" % acc["id"]
    _limit(key)
    with db.session() as conn:
        try:
            row = auth.change_own(conn, acc["id"], body.old, body.new)
        except ValueError as e:
            _attempts[key].append(time.time())
            raise HTTPException(400, str(e))
    return _signed_in(request, row)  # boshqa qurilmalardagi eski sessiyalar yopiladi, bu qurilma kirgan holda qoladi


# ---------- Telegram ulanishi: bot va akkaunt (faqat admin) ----------

TG_ERRORS = {
    "PhoneNumberInvalidError": "Telefon raqami noto'g'ri: +998901234567 ko'rinishida yozing",
    "ApiIdInvalidError": "API ID yoki API hash noto'g'ri: my.telegram.org dagi qiymatlarni tekshiring",
    "PhoneCodeInvalidError": "Kod noto'g'ri",
    "PhoneCodeExpiredError": "Kodning muddati o'tdi: qaytadan boshlang",
    "PasswordHashInvalidError": "Ikki bosqichli parol noto'g'ri",
    "FloodWaitError": "Telegram juda ko'p urinish deb to'xtatdi: birozdan keyin qayta urinib ko'ring",
    "PhoneNumberBannedError": "Bu raqam Telegramda bloklangan",
}


def _tg(coro):
    from . import tgaccount
    try:
        return tgaccount.call(coro)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 — Telegram xatosini odam tiliga o'giramiz
        name = type(e).__name__
        raise HTTPException(400, TG_ERRORS.get(name, "Telegram xatosi: %s" % (str(e)[:160] or name)))


@app.get("/api/telegram")
def tg_status(acc=need("settings")):
    from . import tgaccount
    return {"bot": {"username": config.BOT_USERNAME, "on": bool(config.BOT_TOKEN and config.BOT_ENABLED)},
            "account": tgaccount.status()}


class TgLogin(BaseModel):
    api_id: int
    api_hash: str
    phone: str


@app.post("/api/telegram/login")
def tg_login(body: TgLogin, acc=need("settings")):
    from . import tgaccount
    phone = "+" + "".join(ch for ch in body.phone if ch.isdigit())
    return _tg(tgaccount.start_login(body.api_id, body.api_hash.strip(), phone))


class TgCode(BaseModel):
    code: str


@app.post("/api/telegram/code")
def tg_code(body: TgCode, acc=need("settings")):
    from . import tgaccount
    return _tg(tgaccount.submit_code(body.code))


class TgPassword(BaseModel):
    password: str


@app.post("/api/telegram/password")
def tg_password(body: TgPassword, acc=need("settings")):
    from . import tgaccount
    return _tg(tgaccount.submit_password(body.password))


@app.get("/api/telegram/chats")
def tg_chats(acc=need("settings")):
    from . import tgaccount
    return {"chats": _tg(tgaccount.dialogs())}


class TgChoose(BaseModel):
    ids: list[int]
    days: int = 365


@app.post("/api/telegram/chats")
def tg_choose(body: TgChoose, acc=need("settings")):
    from . import tgaccount
    return _tg(tgaccount.choose(body.ids, max(0, min(body.days, 1500))))


@app.post("/api/telegram/logout")
def tg_logout(acc=need("settings")):
    from . import tgaccount
    return _tg(tgaccount.logout())


# ---------- foydalanuvchilar va rollar (faqat admin) ----------

@app.get("/api/accounts")
def accounts_list(acc=need("accounts")):
    with db.session() as conn:
        return {"accounts": auth.listing(conn),
                "roles": [{"key": k, "label": v, "text": auth.ROLE_TEXT[k]} for k, v in auth.ROLES.items()],
                "people": [r["name"] for r in conn.execute("SELECT name FROM people WHERE name IS NOT NULL ORDER BY name")],
                "projects": [dict(r) for r in conn.execute(
                    "SELECT p.id, p.name, c.demo FROM projects p LEFT JOIN chats c ON c.id = p.chat_id ORDER BY c.demo, p.name")]}


class Account(BaseModel):
    login: str | None = None
    name: str | None = None
    password: str | None = None
    role: str | None = None
    person: str | None = None
    projects: list[int] | None = None
    active: bool | None = None


@app.post("/api/accounts")
def accounts_create(body: Account, acc=need("accounts")):
    with db.session() as conn:
        try:
            aid = auth.create(conn, body.login or "", body.name or "", body.password or "", body.role or "", body.person,
                              body.projects, acc["name"])
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"id": aid}


@app.post("/api/accounts/{aid}")
def accounts_update(aid: int, body: Account, acc=need("accounts")):
    with db.session() as conn:
        try:
            auth.update(conn, aid, acc["id"], **body.model_dump(exclude={"login"}))
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/accounts/{aid}")
def accounts_delete(aid: int, acc=need("accounts")):
    with db.session() as conn:
        try:
            auth.remove(conn, aid, acc["id"])
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True}


def _params(period: str, start: str | None, end: str | None) -> dict:
    if period not in ("day", "week", "month", "custom"):
        raise HTTPException(400, "period: day | week | month | custom")
    try:
        if period == "custom":
            datetime.strptime(start or "", "%Y-%m-%d"); datetime.strptime(end or "", "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Sana YYYY-MM-DD ko'rinishida bo'lsin")
    return {"period": period, "start": start, "end": end}


def _now(asof: str | None):
    try:
        return analytics.resolve_now(asof)
    except ValueError:
        raise HTTPException(400, "asof: YYYY-MM-DD")


def _ui_stamp() -> int:
    """Panel fayllari o'zgarsa brauzer o'zi yangilanadi (dizayn ustida ishlaganda jonli ko'rish uchun)."""
    return int(max(f.stat().st_mtime for f in WEB.iterdir() if f.is_file()))


@app.get("/api/meta")
def meta(request: Request):
    sc = _scope(request)
    with db.session() as conn:
        allp = [dict(r) for r in conn.execute("SELECT id, name, chat_id, coalesce(yordam, 0) AS yordam FROM projects ORDER BY name")
                if sc is None or r["id"] in sc]
        projects = [p for p in allp if not p["yordam"]]  # ish loyihalari; tizimlar (yordam guruhidan) — systems da
        seen = {p["chat_id"] for p in projects}
        links = defaultdict(list)
        for r in conn.execute("SELECT chat_id, project_id FROM chat_projects"):
            links[r["chat_id"]].append(r["project_id"])
        chats = [{**dict(r), "kind": r["kind"] or "ish", "projects": links.get(r["id"], [])}
                 for r in conn.execute("SELECT id, title, demo, kind FROM chats ORDER BY demo, title")
                 if sc is None or r["id"] in seen or set(links.get(r["id"], [])) & sc]
        S = settings.load(conn)
        last = conn.execute("SELECT max(date) FROM messages").fetchone()[0]
        return {"chats": chats, "projects": projects, "systems": allp, "ai": config.ai_enabled(), "bot": config.BOT_USERNAME,
                "departments": db.DEPARTMENTS, "version": db.version(conn), "auth": True, "me": request.state.acc,
                "timeline": analytics.timeline_bounds(conn), "last_message": last,
                "report_deadline": S["report_deadline"], "digest_morning": S["digest_morning"], "project_mode": S["project_mode"],
                "blocker_high_days": S["blocker_high_days"]}


@app.get("/api/version")
def version():
    with db.session() as conn:
        return {"v": db.version(conn), "ui": _ui_stamp()}


_ver = {"v": 0, "at": 0.0}


def _version_now() -> int:
    """Hamma ochiq panellar uchun bitta qiymat: bazaga soniyasiga ko'pi bilan 2 marta murojaat (panellar soni muhim emas)."""
    if time.time() - _ver["at"] > 0.4:
        with db.session() as conn:
            _ver["v"] = db.version(conn)
        _ver["at"] = time.time()
    return _ver["v"]


@app.get("/api/events")
async def events(request: Request):
    """Realtime: bazada o'zgarish bo'lishi bilan panelga darhol xabar (Server-Sent Events). Panel so'rab turmaydi,
    server o'zi aytadi; har 15 soniyada bo'sh "ping" (proksi ulanishni uzib qo'ymasin)."""
    import asyncio

    async def stream():
        last, idle = None, 0
        while not await request.is_disconnected():
            v = await asyncio.to_thread(_version_now)
            if v != last:
                last, idle = v, 0
                yield "data: %d\n\n" % v
            else:
                idle += 1
                if idle % 30 == 0:
                    yield ": ping\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/summary")
def summary(request: Request, period: str = "week", start: str | None = None, end: str | None = None, chat: int | None = None,
            asof: str | None = None):
    kw = _params(period, start, end)
    now = _now(asof)
    sc = _scope(request)
    with db.session() as conn:
        data = analytics.compute(conn, chat_id=chat or None, now=now, scope=sc, dept=_dept(request), **kw)
        data["feed"] = analytics.feed(conn, chat or None, now, scope=sc, dept=_dept(request))
        data["dept"] = _dept(request)
        # Rahbar (panel egasi) xodimlar reytingiga kirmaydi, lekin qidiruvda topilishi kerak
        head = conn.execute("SELECT name, department FROM people WHERE id = ?", (config.OWNER_ID,)).fetchone() if config.OWNER_ID else None
        data["head"] = {"name": head["name"], "department": head["department"]} if head else None
        # Guruhga yozayotgan, lekin botga ulanmagan xodimlar: xabarlari hisobot sifatida qabul qilinmayapti (14 kun)
        data["unlinked"] = [dict(r) for r in conn.execute(
            "SELECT pe.name, count(*) AS n, max(m.date) AS last, sum(CASE WHEN m.source = 'ulanmagan' THEN 1 ELSE 0 END) AS skipped "
            "FROM messages m JOIN people pe ON pe.id = m.user_id "
            "WHERE pe.dm_chat_id IS NULL AND pe.status IS NULL AND coalesce(pe.role, '') != 'rahbar' AND pe.id != %d "
            "AND (pe.id < %d OR pe.id > %d) "
            "AND m.date >= ?" % (int(config.OWNER_ID or 0), db.DEMO_LO, db.DEMO_HI)
            + (" AND coalesce(pe.department, 'Belgilanmagan') = ?" if _dept(request) else "")
            + " GROUP BY pe.name ORDER BY max(m.date) DESC",
            [(now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")] + ([_dept(request)] if _dept(request) else []))] \
            if auth.can(request.state.acc, "people") else []
        if auth.can(request.state.acc, "people"):
            # guruhga qo'shilgan, lekin hali hech narsa yozmagan yangi odamlar ham tasdiqlashga chiqadi
            seen = {u["name"] for u in data["unlinked"]}
            data["unlinked"] += [dict(r) for r in conn.execute(
                "SELECT pe.name, 0 AS n, max(mb.joined_at) AS last, 0 AS skipped FROM members mb JOIN people pe ON pe.id = mb.user_id "
                "WHERE mb.left_at IS NULL AND mb.joined_at >= ? AND pe.dm_chat_id IS NULL AND pe.status IS NULL "
                "AND coalesce(pe.role, '') != 'rahbar' AND pe.id != %d AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.user_id = pe.id)"
                % int(config.OWNER_ID or 0)
                + (" AND coalesce(pe.department, 'Belgilanmagan') = ?" if _dept(request) else "")
                + " GROUP BY pe.name ORDER BY max(mb.joined_at) DESC",
                [(now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")] + ([_dept(request)] if _dept(request) else []))
                if r["name"] not in seen]
        # rahbar "Keyinroq" degan masalalar bugun ko'rsatilmaydi (ertaga yana chiqadi, agar hali dolzarb bo'lsa)
        row = conn.execute("SELECT value FROM meta WHERE key = ?", ("snooze:" + config.now().date().isoformat(),)).fetchone()
        snoozed = set(json.loads(row["value"])) if row else set()
        data["snoozed"] = sum(1 for d in data["decisions"] if d["id"] in snoozed)
        data["decisions"] = [d for d in data["decisions"] if d["id"] not in snoozed]
        data["version"] = db.version(conn)
        data["ai"] = config.ai_enabled()
    data["decision_log"] = actions.recent(6) if auth.can(request.state.acc, "decide") else []
    return data


@app.get("/api/project/{pid}")
def project(request: Request, pid: int, period: str = "week", start: str | None = None, end: str | None = None,
            asof: str | None = None):
    sc = _scope(request)
    if sc is not None and pid not in sc:
        raise HTTPException(403, "Bu loyiha sizga biriktirilmagan")
    with db.session() as conn:
        data = analytics.project_detail(conn, pid, now=_now(asof), **_params(period, start, end))
    if data is None:
        raise HTTPException(404, "Loyiha topilmadi")
    return data


@app.get("/api/project/{pid}/feed")
def project_feed(request: Request, pid: int, until: str | None = None, days: int = 14):
    """Loyiha xabarlari va bot ulardan nimani ajratib olgani: loyiha sahifasidagi "Kunlar" va "Xabarlar"."""
    sc = _scope(request)
    if sc is not None and pid not in sc:
        raise HTTPException(403, "Bu loyiha sizga biriktirilmagan")
    try:
        day = datetime.strptime(until, "%Y-%m-%d").date() if until else config.now().date()
    except ValueError:
        raise HTTPException(400, "until: YYYY-MM-DD")
    with db.session() as conn:
        return {"messages": analytics.project_feed(conn, pid, day, max(1, min(days, 60)))}


@app.get("/api/repeat/{tid}")
def repeat_proof(request: Request, tid: int):
    """Qayta yozilgan ish dalili: hozirgi va oldingi ishning asl xabarlari yonma-yon."""
    from . import quality
    with db.session() as conn:
        data = quality.repeat_proof(conn, tid, _scope(request))
    if data is None:
        raise HTTPException(404, "Bu ish qayta yozilgan deb belgilanmagan")
    return data


@app.get("/api/blockers")
def blockers(request: Request, days: int = 30, asof: str | None = None):
    with db.session() as conn:
        return analytics.blockers_list(conn, _now(asof), max(1, min(days, 120)), _scope(request), _dept(request))


# ---------- murojaatlar: yordam guruhlari va chatbotlar ----------

@app.get("/api/appeals")
def appeals_overview(request: Request, days: int = 30, src: str = "", project: int | None = None, type: str = "", status: str = "",
                     q: str = "", offset: int = 0, limit: int = 25, asof: str | None = None):
    """Murojaatlar bo'limi: ko'rsatkichlar, loyihalar, turlar, hal qilish tartibi, javob sifati, takroriylar va lenta.
    Haqiqiy manba hali ulanmagan bo'lsa namuna (bazaga yozilmaydi, "sample": true)."""
    from . import appeals
    with db.session() as conn:
        return appeals.overview(conn, _now(asof), days, src, project, type, status, q[:100], max(0, offset),
                                max(1, min(limit, 100)), _scope(request))


@app.get("/api/appeals/dataset.jsonl")
def appeals_dataset(request: Request, acc=need("correct")):
    """O'quv to'plami: har qatorda bitta murojaat (matn, tizim, tur, javoblar bahosi). Lokal modelni o'rgatish uchun."""
    from . import appeals
    sc = _scope(request)

    def lines():
        with db.session() as conn:
            for row in appeals.dataset(conn, sc):
                yield json.dumps(row, ensure_ascii=False) + "\n"
    name = "murojaatlar_%s.jsonl" % config.now().strftime("%Y%m%d")
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@app.get("/api/appeals/{aid}")
def appeal_detail(request: Request, aid: int):
    from . import appeals
    with db.session() as conn:
        data = appeals.detail(conn, aid, _scope(request), sample=aid < 0)
    if data is None:
        raise HTTPException(404, "Murojaat topilmadi")
    return data


class AppealFix(BaseModel):
    type: str | None = None
    project_id: int | None = None
    status: str | None = None


@app.post("/api/appeals/{aid}/fix")
def appeal_fix(request: Request, aid: int, body: AppealFix, acc=need("correct")):
    """Rahbar AI xulosasini tuzatadi: turi, tizimi yoki holati (hal qilindi / qayta ochish)."""
    from . import appeals
    if aid < 0:
        raise HTTPException(400, "Namuna murojaatni o'zgartirib bo'lmaydi")
    sc = _scope(request)
    with db.session() as conn:
        row = conn.execute("SELECT project_id FROM appeals WHERE id = ?", (aid,)).fetchone()
        if row is None or (sc is not None and (row["project_id"] not in sc or (body.project_id and body.project_id not in sc))):
            raise HTTPException(404, "Murojaat topilmadi")
        try:
            return appeals.correct(conn, aid, acc["name"], body.type, body.project_id, body.status)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/appeals/push")
async def appeals_push(request: Request):
    """Chatbot murojaatlarini qabul qiladi. Sarlavha: Authorization: Bearer <manba kaliti> (panelda "Chatbot ulash").
    Tana: {"items": [{"id", "user", "user_name", "text", "at", "system", "answers": [{"text", "at", "by", "line", "bot"}],
    "status": "hal"|null, "resolved_at"}]}. Bir xil id qayta yuborilsa o'sha murojaat yangilanadi."""
    from . import appeals
    token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    _limit("push:" + _ip(request)) if not token else None
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(400, "JSON noto'g'ri")
    with db.session() as conn:
        src = appeals.source_by_token(conn, token)
        if src is None:
            _attempts["push:" + _ip(request)].append(time.time())
            raise HTTPException(401, "Manba kaliti noto'g'ri yoki o'chirilgan")
        try:
            return appeals.push(conn, src, body.get("items") if isinstance(body, dict) else body)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/appeals/import")
async def appeals_import(source: int, file: UploadFile = File(...), acc=need("import")):
    """Chatbot jurnalini fayldan yuklash: JSON (push bilan bir xil "items") yoki CSV (id, user, text, at, system, answer,
    answer_at, answer_by, status)."""
    import csv
    from . import appeals
    raw = await file.read()
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "Fayl 30 MB dan katta")
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        if text.lstrip().startswith(("{", "[")):
            data = json.loads(text)
            items = data.get("items") if isinstance(data, dict) else data
        else:
            items = []
            for r in csv.DictReader(io.StringIO(text)):
                it = {k: (v or "").strip() for k, v in r.items() if k}
                if it.get("answer"):
                    it["answers"] = [{"text": it.pop("answer"), "at": it.pop("answer_at", "") or it.get("at"), "by": it.pop("answer_by", "")}]
                items.append(it)
    except (ValueError, csv.Error):
        raise HTTPException(400, "Fayl o'qilmadi: JSON yoki CSV bo'lsin")
    with db.session() as conn:
        src = conn.execute("SELECT * FROM appeal_sources WHERE id = ?", (source,)).fetchone()
        if src is None:
            raise HTTPException(404, "Manba topilmadi")
        out = {"added": 0, "updated": 0, "errors": []}
        try:
            for i in range(0, len(items or []), 500):
                r = appeals.push(conn, src, items[i:i + 500])
                out["added"] += r["added"]
                out["updated"] += r["updated"]
                out["errors"] += r["errors"][:50]
        except ValueError as e:
            raise HTTPException(400, str(e))
    return out


@app.get("/api/appeal-sources")
def appeal_sources(acc=need("settings")):
    from . import appeals
    with db.session() as conn:
        return {"sources": appeals.sources(conn), "push_url": config.PANEL_URL.rstrip("/") + "/api/appeals/push"}


class SourceNew(BaseModel):
    name: str
    project_id: int | None = None


@app.post("/api/appeal-sources")
def appeal_source_new(body: SourceNew, acc=need("settings")):
    """Chatbot ulash: kalit faqat shu javobda bir marta ko'rsatiladi (bazada xeshi turadi)."""
    from . import appeals
    with db.session() as conn:
        try:
            return appeals.new_source(conn, body.name, body.project_id, acc["name"])
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/appeal-sources/{sid}/reset")
def appeal_source_reset(sid: int, acc=need("settings")):
    from . import appeals
    with db.session() as conn:
        try:
            return appeals.reset_source(conn, sid)
        except ValueError as e:
            raise HTTPException(404, str(e))


class SourceState(BaseModel):
    active: bool | None = None
    project_id: int | None = None
    name: str | None = None


@app.post("/api/appeal-sources/{sid}")
def appeal_source_set(sid: int, body: SourceState, acc=need("settings")):
    with db.session() as conn:
        if not conn.execute("SELECT 1 FROM appeal_sources WHERE id = ?", (sid,)).fetchone():
            raise HTTPException(404, "Manba topilmadi")
        if body.active is not None:
            conn.execute("UPDATE appeal_sources SET active = ? WHERE id = ?", (1 if body.active else 0, sid))
        if body.project_id is not None:
            conn.execute("UPDATE appeal_sources SET project_id = ? WHERE id = ?", (body.project_id or None, sid))
        if body.name and body.name.strip():
            conn.execute("UPDATE appeal_sources SET name = ? WHERE id = ?", (" ".join(body.name.split())[:80], sid))
        db.bump_version(conn)
    return {"ok": True}


class ChatKind(BaseModel):
    kind: str
    project_ids: list[int] | None = None
    new_name: str | None = None


@app.post("/api/chats/{cid}/kind")
def chat_kind(cid: int, body: ChatKind, acc=need("settings")):
    """Guruh turi: ish guruhi (jamoa hisobotlari) yoki yordam guruhi (tizim foydalanuvchilarining murojaatlari)."""
    import threading
    from . import appeals
    with db.session() as conn:
        try:
            out = appeals.set_chat_kind(conn, cid, body.kind, body.project_ids, body.new_name)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if body.kind == "yordam":  # oxirgi 30 kundagi xabarlari murojaat sifatida qayta o'qiladi (fonda)
        threading.Thread(target=appeals.reread, args=(cid, 30), daemon=True).start()
    return out


class ClientLine(BaseModel):
    line: int | None = None


@app.post("/api/clients/{cid}/staff")
def client_staff(cid: int, body: ClientLine, acc=need("people")):
    """Yordam guruhidagi odam: 0 — foydalanuvchi, 1 operator, 2 mutaxassis, 3 dasturchi (javoblari shu liniyada sanaladi)."""
    from . import appeals
    with db.session() as conn:
        try:
            appeals.set_client_staff(conn, cid, body.line)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True}


class PersonLine(BaseModel):
    name: str
    line: int | None = None


@app.post("/api/person/line")
def person_line(body: PersonLine, acc=need("people")):
    """Puls xodimi yordam guruhida javob berganda qaysi liniya hisoblanadi (bo'sh — avtomatik)."""
    if body.line is not None and body.line not in (1, 2, 3):
        raise HTTPException(400, "Liniya: 1, 2 yoki 3")
    with db.session() as conn:
        if not conn.execute("UPDATE people SET line = ? WHERE name = ?", (body.line, body.name)).rowcount:
            raise HTTPException(404, "Xodim topilmadi")
        db.bump_version(conn)
    return {"ok": True}


class ParseTest(BaseModel):
    text: str


@app.post("/api/parse-test")
def parse_test(body: ParseTest):
    """Botni sinash: xabar guruhga yozilsa bot uni qanday tushunishi (bazaga hech narsa yozilmaydi, AI chaqirilmaydi)."""
    from . import parser
    text = body.text.strip()[:4000]
    if not text:
        raise HTTPException(400, "Xabar matnini yozing")
    today = config.now().date()
    with db.session() as conn:
        projects = [dict(r) for r in conn.execute("SELECT key, name, aliases FROM projects")]
    p = parser.parse_report(text, today) or parser.parse_format(text, today)
    if p is None:
        p = parser.parse_free(text, projects, today)
    sec = {k: [{"title": i.title, "progress": i.progress} for i in v] for k, v in (p.sections or {}).items()}
    if not sec and p.items:
        sec = {{"done": "done", "task": "task", "blocker": "blocker"}.get(p.kind, "task"): [{"title": i.title, "progress": i.progress} for i in p.items]}
    return {"kind": p.kind, "source": p.source, "project": p.project, "department": p.department, "holat": p.holat,
            "day": p.day.isoformat() if p.day else None, "deadline": p.deadline.isoformat() if p.deadline else None,
            "sections": sec, "ai": config.ai_enabled(), "work": parser.looks_like_work(text)}


@app.get("/api/person")
def person(request: Request, name: str, period: str = "week", start: str | None = None, end: str | None = None,
           chat: int | None = None, asof: str | None = None):
    with db.session() as conn:
        data = analytics.person_detail(conn, name, chat_id=chat or None, now=_now(asof), scope=_scope(request),
                                       dept=_dept(request), **_params(period, start, end))
    if data is None:
        raise HTTPException(404, "Xodim topilmadi")
    return data


class Snooze(BaseModel):
    id: str
    undo: bool = False


@app.post("/api/decisions/snooze")
def snooze(body: Snooze, acc=need("decide")):
    """"Keyinroq": masala bugun boshqa ko'rsatilmaydi. undo=True — qaytarish."""
    key = "snooze:" + config.now().date().isoformat()
    with db.session() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        ids = set(json.loads(row["value"])) if row else set()
        ids = ids - {body.id} if body.undo else ids | {body.id[:120]}
        conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, json.dumps(sorted(ids))))
        db.bump_version(conn)
    return {"ok": True}


class RepeatMark(BaseModel):
    task_id: int
    kind: str


@app.post("/api/task/repeat")
def repeat_mark(body: RepeatMark, acc=need("decide")):
    """Rahbar AI belgisini tuzatadi: "rad" — takror emas (ish reytingga qaytadi); takror/nusxa — belgini qaytarish."""
    if body.kind not in ("rad", "takror", "nusxa"):
        raise HTTPException(400, "Belgi noto'g'ri")
    with db.session() as conn:
        row = conn.execute("SELECT dup_kind, dup_of FROM tasks WHERE id = ?", (body.task_id,)).fetchone()
        if row is None or row["dup_of"] is None:
            raise HTTPException(404, "Bu ish takror deb belgilanmagan")
        note = "Rahbar: takror emas" if body.kind == "rad" else None
        conn.execute("UPDATE tasks SET dup_kind = ?, dup_note = COALESCE(?, dup_note) WHERE id = ?", (body.kind, note, body.task_id))
        db.bump_version(conn)
    return {"ok": True}


@app.get("/api/person/days")
def person_days(request: Request, name: str, days: int = 30, until: str | None = None):
    """Xodimning kunma-kun hisobotlari: rahbar har bir xodimni alohida, kunlar kesimida ko'radi."""
    from . import quality
    until = until or config.now().date().isoformat()
    try:
        datetime.strptime(until, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "until: YYYY-MM-DD")
    with db.session() as conn:
        return {"name": name, "days": quality.person_days(conn, name, until, max(1, min(days, 120)), _scope(request))}


@app.get("/api/person/growth")
def person_growth(request: Request, name: str, days: int = 90):
    """Xodim vaqt o'tib qanday o'zgargani: davrma-davr ish hajmi, og'irlik, qayta yozish, muntazamlik."""
    from . import quality
    with db.session() as conn:
        return quality.person_growth(conn, name, config.now().date().isoformat(), max(14, min(days, 730)), _scope(request))


@app.get("/api/assistant/brief")
def assistant_brief(request: Request, refresh: int = 0):
    """Rahbar yordamchisi: hozir bilish kerak bo'lgan xulosalar (bir soat keshlanadi)."""
    from . import assistant
    acc = request.state.acc
    if refresh:
        _limit("yb:%s" % acc["id"])
        _attempts["yb:%s" % acc["id"]].append(time.time())
    with db.session() as conn:
        return assistant.brief(conn, _scope(request), bool(refresh), _dept(request))


class Question(BaseModel):
    question: str


@app.post("/api/assistant/ask")
def assistant_ask(request: Request, body: Question):
    from . import assistant
    key = "ys:%s" % request.state.acc["id"]
    _limit(key)
    _attempts[key].append(time.time())
    with db.session() as conn:
        try:
            return assistant.ask(conn, body.question, _scope(request), _dept(request))
        except ValueError as e:
            raise HTTPException(400, str(e))


class AgentAsk(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/agent")
def agent_ask(request: Request, body: AgentAsk):
    """Yordamchi agent: qadamlar (qaysi ma'lumotni ko'ryapti) jonli oqimda keladi, oxirida javob va amal tugmalari."""
    from . import agent
    acc = request.state.acc
    _limit("ag:%s" % acc["id"])
    _attempts["ag:%s" % acc["id"]].append(time.time())
    sc, dp = _scope(request), _dept(request)

    def events():
        try:
            for ev in agent.run(body.question, body.history[-6:], sc, dp, allow_sql=acc.get("role") in ("admin", "rahbar")):
                yield "data: %s\n\n" % json.dumps(ev, ensure_ascii=False)
        except Exception:  # noqa: BLE001 — oqim uzilmasin, rahbar sababini ko'rsin
            logging.getLogger("puls.web").exception("agent")
            yield "data: %s\n\n" % json.dumps({"type": "error", "text": "Yordamchida xato yuz berdi, qayta urinib ko'ring"})
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/reports")
def reports(request: Request, day: str | None = None, last_for: str | None = None):
    """Hisobotlar: kunlik ish (har ish bahosi bilan), shubhali takrorlar va hisobot bermaganlar.
    last_for: kun berilmasa, shu xodimning oxirgi hisobot kuni ochiladi (brifing va qidiruvdan o'tilganda)."""
    from . import quality
    today = config.now().date().isoformat()
    if not day and last_for:
        with db.session() as conn:
            r = conn.execute("SELECT max(substr(done_at, 1, 10)) FROM tasks WHERE assignee = ? AND status = 'done'", (last_for,)).fetchone()
        day = r[0] if r and r[0] else None
    day = day or today
    try:
        since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
    except ValueError:
        raise HTTPException(400, "day: YYYY-MM-DD")
    sc, dp = _scope(request), _dept(request)
    with db.session() as conn:
        people = quality.day_report(conn, day, sc, dp)
        now = config.now()
        # Bugungi kun 18:00 gacha tugamagan: hisobot bermaganlar "hali yozmagan" deb ko'rsatiladi
        return {"day": day, "today": today, "people": people, "final": day < today or now.hour >= 18,
                "missing": quality.missing(conn, day, {p["name"] for p in people}, sc, dp),
                "suspicious": [x for x in quality.suspicious(conn, since, sc, dp) if x["done_at"][:10] <= day][:60],
                "days": quality.days(conn, day, 14, sc, dp),
                "pending": conn.execute("SELECT count(*) FROM tasks WHERE weight IS NULL AND status = 'done'").fetchone()[0],
                "weights": quality.WEIGHTS, "categories": quality.CATS, "ai": config.ai_enabled()}


class Dept(BaseModel):
    name: str
    department: str


@app.post("/api/person/department")
def set_department(body: Dept, acc=need("people")):
    with db.session() as conn:
        cur = conn.execute("UPDATE people SET department = ? WHERE name = ?", (body.department.strip()[:40] or None, body.name))
        if not cur.rowcount:
            raise HTTPException(404, "Bu xodim hali guruhga yozmagan")
        db.bump_version(conn)
    return {"ok": True}


class Role(BaseModel):
    name: str
    role: str = ""


@app.post("/api/person/role")
def set_role(body: Role, acc=need("people")):
    """Rahbar: boshqalarga vazifa bera oladi va botning guruhdagi savollarini hal qiladi."""
    if body.role not in ("", "rahbar"):
        raise HTTPException(400, "Rol: rahbar yoki bo'sh")
    with db.session() as conn:
        # "" — rahbar emasligi aniq aytilgan: guruh admini bo'lsa ham bot uni qayta rahbar deb belgilamaydi
        cur = conn.execute("UPDATE people SET role = ? WHERE name = ?", (body.role, body.name))
        if not cur.rowcount:
            raise HTTPException(404, "Bu xodim hali guruhga yozmagan")
        db.bump_version(conn)
    return {"ok": True}


class Rename(BaseModel):
    name: str
    new_name: str


@app.post("/api/person/name")
def set_name(body: Rename, acc=need("people")):
    """Rahbar xodimning haqiqiy ism-familiyasini yozadi: hamma joyda (panel, Excel, bot) shu ko'rinadi."""
    new = " ".join(body.new_name.split())[:60]
    if len(new) < 2:
        raise HTTPException(400, "Ism-familiyani yozing")
    with db.session() as conn:
        if not conn.execute("SELECT 1 FROM people WHERE name = ?", (body.name,)).fetchone():
            raise HTTPException(404, "Bu xodim hali guruhga yozmagan")
        if new != body.name and conn.execute("SELECT 1 FROM people WHERE name = ?", (new,)).fetchone():
            raise HTTPException(409, "Bu ism boshqa xodimda bor")
        db.rename_person(conn, body.name, new)
        conn.execute("UPDATE people SET name_locked = 1 WHERE name = ?", (new,))
        db.bump_version(conn)
    return {"ok": True, "name": new}


class NewPerson(BaseModel):
    name: str
    department: str | None = None


@app.post("/api/person/add")
def add_person(body: NewPerson, acc=need("people")):
    """Xodimni qo'lda qo'shish: ism va bo'lim yoziladi, shaxsiy havola qaytadi — xodim bossa Telegram akkauntiga bog'lanadi."""
    try:
        return actions.add_person(body.name, body.department)
    except ValueError as e:
        raise HTTPException(400, str(e))


class Who(BaseModel):
    name: str


@app.get("/api/person/link")
def person_link(name: str, acc=need("people")):
    try:
        return actions.invite(name)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/person/link/reset")
def person_link_reset(body: Who, acc=need("people")):
    try:
        return actions.invite(body.name, reset=True)
    except ValueError as e:
        raise HTTPException(404, str(e))


class PersonStatus(BaseModel):
    name: str
    status: str


@app.post("/api/person/status")
def person_status(body: PersonStatus, acc=need("people")):
    """Guruhdagi odamni xodim qilish (havolasiz ham qabul, oldingi hisobotlari qayta o'qiladi) yoki begona deb belgilash."""
    import threading
    from .ingest import welcome_back
    if body.status not in ("xodim", "begona", ""):
        raise HTTPException(400, "Holat: xodim yoki begona")
    with db.session() as conn:
        row = conn.execute("SELECT id FROM people WHERE name = ?", (body.name,)).fetchone()
        if row is None:
            raise HTTPException(404, "Xodim topilmadi")
        conn.execute("UPDATE people SET status = ? WHERE id = ?", (body.status or None, row["id"]))
        db.bump_version(conn)
    if body.status == "xodim":  # oldin yozgan hisobotlarini fonda o'qiydi: panel kutib qolmaydi
        threading.Thread(target=welcome_back, args=(row["id"],), daemon=True).start()
    return {"ok": True}


@app.get("/api/links")
def links(acc=need("people")):
    return {"people": actions.invites()}


@app.get("/api/settings")
def get_settings():
    with db.session() as conn:
        return {"values": settings.load(conn), "schema": settings.schema()}


@app.put("/api/settings")
def put_settings(changes: dict, acc=need("settings")):
    with db.session() as conn:
        try:
            values = settings.save(conn, changes)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if changes.get("project_mode") == "guruh":
            from .ingest import ensure_group_projects
            ensure_group_projects(conn)  # bitta guruh — bitta loyiha: ortiqchalari birlashadi, loyihasiz guruh loyiha oladi
        db.bump_version(conn)
    return {"values": values}


class Action(BaseModel):
    action: dict
    send: bool = True


@app.post("/api/actions/preview")
def action_preview(body: Action, acc=need("decide")):
    try:
        return actions.preview(body.action)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/actions/execute")
def action_execute(body: Action, acc=need("decide")):
    try:
        return actions.execute(body.action, body.send)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


# ---------- menejer doskasi ----------

def _tg(name: str, *args) -> str:
    """Bot ishlayotgan ipda bot.<name>(bot, *args) ni boshlaydi: vazifa xabari, izoh yoki bekor qilish.
    Panel Telegramni kutib qolmaydi: 1,5 soniyada tugamasa javob darhol qaytadi, xabar esa fonda yuboriladi."""
    import asyncio
    import concurrent.futures
    from . import bot as tgbot
    if actions.BOT is None or actions.LOOP is None:
        return "Bot ishlamayapti: xabar yuborilmadi"
    fut = asyncio.run_coroutine_threadsafe(getattr(tgbot, name)(actions.BOT, *args), actions.LOOP)
    try:
        return fut.result(timeout=1.5)
    except concurrent.futures.TimeoutError:
        return "Guruhga yuborilmoqda"
    except Exception:  # noqa: BLE001
        return "Telegramga yuborilmadi"


def _board_tg(task_id: int, new: bool = False) -> str:
    return _tg("board_sync", task_id, new)


def _board_refresh(task_id: int) -> str:
    """Guruhdagi xabar bor bo'lsa, uni hozirgi holatga moslaydi (ro'yxat, muddat, foiz)."""
    with db.session() as conn:
        sent = conn.execute("SELECT tg_msg FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _board_tg(task_id) if sent and sent["tg_msg"] else ""


def _board_do(fn, *args):
    with db.session() as conn:
        try:
            return fn(conn, *args)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))


def _who(conn, acc: dict) -> str:
    """Doska tarixi va guruhdagi izohda kim: panelga kirgan odamning ismi."""
    return board.manager(conn) if acc.get("local") else acc["name"]


def _task_of_check(conn, cid: int) -> int | None:
    r = conn.execute("SELECT task_id FROM task_checks WHERE id = ?", (cid,)).fetchone()
    return r["task_id"] if r else None


@app.get("/api/board")
def board_get(request: Request, project: int | None = None, dept: str | None = None, q: str = "", acc=need("board")):
    with db.session() as conn:
        return board.board(conn, project, dept or None, q.strip(), _scope(request))


@app.get("/api/board/people")
def board_people(project: int | None = None, acc=need("board")):
    with db.session() as conn:
        return board.candidates(conn, project)


class BoardTask(BaseModel):
    title: str
    project_id: int
    assignee: str | None = None
    assignees: list[str] | None = None   # bir nechta xodim: har biriga o'z vazifasi
    deadline: str | None = None
    priority: str | None = None
    note: str | None = None
    checklist: list[str] | None = None


@app.post("/api/board/task")
def board_create(request: Request, body: BoardTask, acc=need("board")):
    sc = _scope(request)

    who_list = body.assignees or ([body.assignee] if body.assignee else [])

    def make(c):
        board.allowed(c, None, sc, body.project_id)
        return board.create_many(c, body.title, body.project_id, who_list, body.deadline, body.priority, body.note,
                                 _who(c, acc), body.checklist)
    ids = _board_do(make)
    tid = ids[0]
    if len(ids) > 1:
        sent = [_board_tg(i, new=True) for i in ids]
        return {"id": tid, "ids": ids, "telegram": sent[0] if len(set(sent)) == 1 else "; ".join(dict.fromkeys(sent))}
    return {"id": tid, "ids": ids, "telegram": _board_tg(tid, new=True) if who_list else "Ijrochi tanlanmagan"}


def _mine(request: Request, tid: int | None, cid: int | None = None) -> int:
    """Menejer faqat o'z loyihasidagi kartochkaga tegadi. Qaytaradi: vazifa id."""
    def check(c):
        t = _task_of_check(c, cid) if cid is not None else tid
        board.allowed(c, t, _scope(request))
        return t
    return _board_do(check)


@app.get("/api/board/task/{tid}")
def board_detail(request: Request, tid: int, acc=need("board")):
    _mine(request, tid)
    return _board_do(board.detail, tid)


@app.delete("/api/board/task/{tid}")
def board_delete(request: Request, tid: int, acc=need("board")):
    _mine(request, tid)
    chat, msg, title = _board_do(board.remove, tid)
    return {"ok": True, "telegram": _tg("board_cancel", chat, msg, title) if chat and msg else ""}


@app.post("/api/board/task/{tid}/copy")
def board_copy(request: Request, tid: int, acc=need("board")):
    _mine(request, tid)
    return {"id": _board_do(lambda c: board.copy(c, tid, _who(c, acc)))}


class BoardText(BaseModel):
    text: str


@app.post("/api/board/task/{tid}/comment")
def board_comment(request: Request, tid: int, body: BoardText, acc=need("board")):
    _mine(request, tid)
    who = _board_do(lambda c: _who(c, acc))
    text = _board_do(board.comment, tid, who, body.text)
    return {"ok": True, "telegram": _tg("board_post", tid, text, who)}


@app.post("/api/board/task/{tid}/check")
def board_check_add(request: Request, tid: int, body: BoardText, acc=need("board")):
    _mine(request, tid)
    _board_do(lambda c: board.check_add(c, tid, body.text, _who(c, acc)))
    return {"ok": True, "telegram": _board_refresh(tid)}


class CheckState(BaseModel):
    done: bool


@app.post("/api/board/check/{cid}")
def board_check_set(request: Request, cid: int, body: CheckState, acc=need("board")):
    _mine(request, None, cid)
    tid = _board_do(lambda c: board.check_set(c, cid, body.done, _who(c, acc)))
    return {"ok": True, "telegram": _board_refresh(tid)}


@app.delete("/api/board/check/{cid}")
def board_check_del(request: Request, cid: int, acc=need("board")):
    _mine(request, None, cid)
    tid = _board_do(board.check_del, cid)
    return {"ok": True, "telegram": _board_refresh(tid)}


class BoardChange(BaseModel):
    stage: str | None = None
    progress: int | None = None
    title: str | None = None
    deadline: str | None = None
    priority: str | None = None
    note: str | None = None
    assignee: str | None = None
    flag: str | None = None


@app.post("/api/board/task/{tid}")
def board_change(request: Request, tid: int, body: BoardChange, acc=need("board")):
    _mine(request, tid)
    fields = body.model_dump(exclude_unset=True)

    def change(conn):
        who = _who(conn, acc)
        old = conn.execute("SELECT tg_chat, tg_msg, assignee, title FROM tasks WHERE id = ?", (tid,)).fetchone()
        if "stage" in fields:
            board.move(conn, tid, fields.pop("stage"), fields.pop("progress", None), who)
        if fields:
            board.update(conn, tid, who, **fields)
        return old
    old = _board_do(change)
    # yangi ijrochi: eski xabardagi tugmalar olinadi, guruhga yangi xabar; boshqa o'zgarish: bor xabar yangilanadi
    if fields.get("assignee") and old and fields["assignee"] != old["assignee"]:
        if old["tg_msg"]:
            _tg("board_cancel", old["tg_chat"], old["tg_msg"], old["title"], "Vazifa boshqa xodimga berildi")
        return {"ok": True, "telegram": _board_tg(tid, new=True)}
    return {"ok": True, "telegram": _board_refresh(tid)}


class Correction(BaseModel):
    kind: str
    project_id: int | None = None


@app.post("/api/messages/{mid}/correct")
def correct(mid: int, body: Correction, acc=need("correct")):
    try:
        return actions.correct(mid, body.kind, body.project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/export.xlsx")
def export(request: Request, view: str = "projects", period: str = "week", start: str | None = None, end: str | None = None,
           chat: int | None = None, asof: str | None = None):
    """Har ekran o'z jadvalini bitta toza varaqli alohida faylga chiqaradi."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    kw = _params(period, start, end)
    with db.session() as conn:
        data = analytics.compute(conn, chat_id=chat or None, now=_now(asof), scope=_scope(request), dept=_dept(request), **kw)
    if view == "people":
        title, header, widths = "Xodimlar", ["Xodim", "Bo'lim", "Holat", "Fakt", "Ochiq", "Bajardi", "Bajarish % (30 kun)", "O'rtacha kun", "Baho"], [24, 13, 14, 34, 9, 10, 18, 13, 8]
        rows = [[p["name"], p["department"], p["state_label"], p["fact"], p["open"], p["done"], p["completion"], p["cycle"], p["score"]] for p in data["people"]]
    elif view == "tasks":
        title, header, widths = "Ochiq vazifalar", ["Xodim", "Loyiha", "Vazifa", "Necha kundan beri"], [24, 28, 56, 18]
        rows = [[p["name"], t["project"], t["title"], t["age"]] for p in data["people"] for t in p["open_tasks"]]
    elif view == "departments":
        title, header, widths = "Bo'limlar", ["Bo'lim", "Odamlar", "Ochiq", "Yangi", "Bajarildi", "Bajarilish %", "O'rtacha baho"], [16, 10, 9, 9, 11, 13, 14]
        rows = [[d["name"], d["count"], d["open"], d["created"], d["done"], d["pct"], d["score"]] for d in data["departments"]]
    else:
        title, header, widths = "Loyihalar", ["Loyiha", "Holat", "Asosiy sabab", "Progress %", "Ochiq", "Muddat", "Prognoz", "Yangi", "Bajarildi"], [28, 11, 52, 12, 9, 13, 13, 9, 11]
        rows = [[p["name"], p["status"], p["risks"][0]["text"] if p["risks"] else "", p["progress"], p["open_total"],
                 p["deadline_label"], p["eta_label"], p["created"], p["done"]] for p in data["projects"]]
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(["Puls · %s · %s" % (title, data["period"]["range_label"])])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(header)
    for c in ws[3]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="4F46E5"), Alignment(vertical="center")
    for i, r in enumerate(rows):
        ws.append(r)
        if i % 2:
            for c in ws[ws.max_row]:
                c.fill = PatternFill("solid", fgColor="F5F6FA")
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    ws.freeze_panes = "A4"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = "puls_%s_%s.xlsx" % (view, data["period"]["to"])
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % name})


def _export_text(value) -> str:
    if isinstance(value, str):
        return value
    return "".join(part if isinstance(part, str) else part.get("text", "") for part in value or [])


@app.post("/api/import")
async def import_history(file: UploadFile = File(...), acc=need("import")):
    """Telegram Desktop -> Export chat history -> JSON (result.json). Bot qo'shilmasdan oldingi tarix uchun."""
    raw = await file.read()
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "Fayl 30 MB dan katta")
    try:
        data = json.loads(raw)
        messages = data["messages"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Bu Telegram eksport fayli emas (result.json kerak)")
    cid = int(data.get("id") or 0)
    kind = str(data.get("type", ""))
    chat_id = -int("100%d" % cid) if ("supergroup" in kind or "channel" in kind) else -cid
    title = data.get("name") or "Import qilingan guruh"
    added = skipped = 0
    with db.session() as conn:
        for m in messages:
            if m.get("type") != "message":
                continue
            text = _export_text(m.get("text"))
            if not text.strip():
                continue
            uid = int("".join(ch for ch in str(m.get("from_id") or "") if ch.isdigit()) or 0)
            inc = Incoming(chat_id, title, int(m["id"]), uid, m.get("from") or "Noma'lum", None,
                           datetime.fromisoformat(m["date"]).replace(tzinfo=None), text, m.get("reply_to_message_id"))
            if ingest(conn, inc, use_ai=False).duplicate:
                skipped += 1
            else:
                added += 1
    return {"chat": title, "added": added, "skipped": skipped}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)
