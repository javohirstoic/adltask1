"""Veb panel va API (FastAPI)."""
import hashlib
import hmac
import io
import json
import time
from collections import defaultdict
from datetime import datetime

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import actions, analytics, config, db, settings
from .ingest import Incoming, ingest

WEB = config.ROOT / "web"
COOKIE = "puls_kirish"
app = FastAPI(title="Puls", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=WEB), name="static")
_attempts: dict[str, list[float]] = defaultdict(list)


def _token() -> str:
    return hmac.new(config.PANEL_SECRET.encode(), config.PANEL_PIN.encode(), hashlib.sha256).hexdigest()


def _prefix(request: Request) -> str:
    return request.headers.get("x-forwarded-prefix", "").rstrip("/")


@app.middleware("http")
async def guard(request: Request, call_next):
    """Kirish kodi (PANEL_PIN) o'rnatilgan bo'lsa, kodsiz na panel, na API ochiladi."""
    path = request.url.path
    open_paths = path in ("/login", "/api/login") or path.startswith("/static/")
    if config.PANEL_PIN and not open_paths and not hmac.compare_digest(request.cookies.get(COOKIE, ""), _token()):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "kirish kerak"}, status_code=401)
        return RedirectResponse(_prefix(request) + "/login", status_code=302)
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _page(name: str) -> FileResponse:
    return FileResponse(WEB / name, headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return _page("index.html")


@app.get("/taqdimot")
def slides():
    return _page("taqdimot.html")


@app.get("/login")
def login_page():
    return _page("login.html")


class Pin(BaseModel):
    pin: str


@app.post("/api/login")
def login(body: Pin, request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
    now = time.time()
    _attempts[ip] = [t for t in _attempts[ip] if now - t < 300]
    if len(_attempts[ip]) >= 8:
        raise HTTPException(429, "Ko'p urinish. 5 daqiqadan keyin qayta urinib ko'ring.")
    if not config.PANEL_PIN or not hmac.compare_digest(body.pin.strip(), config.PANEL_PIN):
        _attempts[ip].append(now)
        raise HTTPException(401, "Kod noto'g'ri")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, _token(), max_age=30 * 86400, httponly=True, samesite="lax",
                    secure=request.headers.get("x-forwarded-proto") == "https", path=_prefix(request) + "/")
    return resp


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
def meta():
    with db.session() as conn:
        chats = [dict(r) for r in conn.execute("SELECT id, title, demo FROM chats ORDER BY demo, title")]
        projects = [dict(r) for r in conn.execute("SELECT id, name, chat_id FROM projects ORDER BY name")]
        return {"chats": chats, "projects": projects, "ai": config.ai_enabled(), "bot": config.BOT_USERNAME,
                "departments": db.DEPARTMENTS, "version": db.version(conn), "auth": bool(config.PANEL_PIN),
                "timeline": analytics.timeline_bounds(conn)}


@app.get("/api/version")
def version():
    with db.session() as conn:
        return {"v": db.version(conn), "ui": _ui_stamp()}


@app.get("/api/summary")
def summary(period: str = "week", start: str | None = None, end: str | None = None, chat: int | None = None,
            asof: str | None = None):
    kw = _params(period, start, end)
    now = _now(asof)
    with db.session() as conn:
        data = analytics.compute(conn, chat_id=chat or None, now=now, **kw)
        data["feed"] = analytics.feed(conn, chat or None, now)
        data["version"] = db.version(conn)
        data["ai"] = config.ai_enabled()
    data["decision_log"] = actions.recent(6)
    return data


@app.get("/api/project/{pid}")
def project(pid: int, period: str = "week", start: str | None = None, end: str | None = None, asof: str | None = None):
    with db.session() as conn:
        data = analytics.project_detail(conn, pid, now=_now(asof), **_params(period, start, end))
    if data is None:
        raise HTTPException(404, "Loyiha topilmadi")
    return data


@app.get("/api/person")
def person(name: str, period: str = "week", start: str | None = None, end: str | None = None, chat: int | None = None,
           asof: str | None = None):
    with db.session() as conn:
        data = analytics.person_detail(conn, name, chat_id=chat or None, now=_now(asof), **_params(period, start, end))
    if data is None:
        raise HTTPException(404, "Xodim topilmadi")
    return data


class Dept(BaseModel):
    name: str
    department: str


@app.post("/api/person/department")
def set_department(body: Dept):
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
def set_role(body: Role):
    """Rahbar: boshqalarga vazifa bera oladi va botning guruhdagi savollarini hal qiladi."""
    if body.role not in ("", "rahbar"):
        raise HTTPException(400, "Rol: rahbar yoki bo'sh")
    with db.session() as conn:
        cur = conn.execute("UPDATE people SET role = ? WHERE name = ?", (body.role or None, body.name))
        if not cur.rowcount:
            raise HTTPException(404, "Bu xodim hali guruhga yozmagan")
        db.bump_version(conn)
    return {"ok": True}


class Rename(BaseModel):
    name: str
    new_name: str


@app.post("/api/person/name")
def set_name(body: Rename):
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


class Who(BaseModel):
    name: str


@app.get("/api/person/link")
def person_link(name: str):
    try:
        return actions.invite(name)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/person/link/reset")
def person_link_reset(body: Who):
    try:
        return actions.invite(body.name, reset=True)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/links")
def links():
    return {"people": actions.invites()}


@app.get("/api/settings")
def get_settings():
    with db.session() as conn:
        return {"values": settings.load(conn), "schema": settings.schema()}


@app.put("/api/settings")
def put_settings(changes: dict):
    with db.session() as conn:
        try:
            values = settings.save(conn, changes)
        except ValueError as e:
            raise HTTPException(400, str(e))
        db.bump_version(conn)
    return {"values": values}


class Action(BaseModel):
    action: dict
    send: bool = True


@app.post("/api/actions/preview")
def action_preview(body: Action):
    try:
        return actions.preview(body.action)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/actions/execute")
def action_execute(body: Action):
    try:
        return actions.execute(body.action, body.send)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


class Correction(BaseModel):
    kind: str
    project_id: int | None = None


@app.post("/api/messages/{mid}/correct")
def correct(mid: int, body: Correction):
    try:
        return actions.correct(mid, body.kind, body.project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/export.xlsx")
def export(view: str = "projects", period: str = "week", start: str | None = None, end: str | None = None,
           chat: int | None = None, asof: str | None = None):
    """Har ekran o'z jadvalini bitta toza varaqli alohida faylga chiqaradi."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    kw = _params(period, start, end)
    with db.session() as conn:
        data = analytics.compute(conn, chat_id=chat or None, now=_now(asof), **kw)
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
async def import_history(file: UploadFile = File(...)):
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
