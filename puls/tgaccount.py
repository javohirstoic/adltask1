"""Ikkinchi ulanish usuli: Telegram akkaunt (guruhlarni oddiy a'zo sifatida o'qiydi).

Bot bilan farqi:
- bot guruhga qo'shilishidan oldingi tarixni ham o'qiydi: bir yil oldingi hisobot ham bazaga tushadi va yangi hisobot
  u bilan solishtiriladi (eski ishni qayta yozish shunda ko'rinadi);
- o'chirilgan xabarni biladi (bot bilmaydi): xodim hisobotini o'chirsa, rahbar buni ko'radi;
- tahrirlangan xabarni ikkalasi ham ko'radi.
Tavsiya: alohida xizmat akkaunti guruhlarga oddiy a'zo qilib qo'shiladi; bot ham qoladi, chunki tugmali vazifa, eslatma va
javoblarni bot yozadi. Ikkalasi bitta xabarni ko'rsa ham baza uni bir marta yozadi (chat_id va msg_id bo'yicha): akkaunt yangi
xabarni biroz kutib oladi, bot ulgurgan bo'lsa (yuklama savoli, reaksiya) qayta ishlanmaydi.
Sessiya fayli data/ ichida, faqat dastur o'qiydi; ikki bosqichli parol hech qayerda saqlanmaydi.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

from . import ai, appeals, board, config, db, load, settings
from .ingest import Incoming, accepted, deleted, ingest, load_projects, process, triage

log = logging.getLogger("puls.tgaccount")
MEDIA_MAX = 20 * 1024 * 1024
LIVE_DELAY = 12          # soniya: bot ulgursa, xabarni bot ishlaydi (reaksiya, yuklama savoli)
HISTORY_BATCH = 20       # tarixni AI'ga shuncha xabardan bitta so'rovda beramiz

LOOP: asyncio.AbstractEventLoop | None = None
S: dict = {"client": None, "step": "off", "error": "", "me": None, "phone_hash": None, "phone": None,
           "history": {}, "last": None, "chats": {}}


def _cfg_path():
    return config.DB_PATH.parent / "tg_account.json"


def _session_path() -> str:
    return str(config.DB_PATH.parent / "tg_account")


def load_cfg() -> dict:
    try:
        return json.loads(_cfg_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cfg(cfg: dict) -> None:
    p = _cfg_path()
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def call(coro, timeout: float = 60):
    """Veb so'rovi ipidan asosiy oqimdagi korutinni bajarish."""
    if LOOP is None:
        raise RuntimeError("Dastur hali ishga tushmagan")
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout)


def status() -> dict:
    cfg = load_cfg()
    return {"step": S["step"], "error": S["error"], "me": S["me"], "phone": cfg.get("phone") or S["phone"],
            "chats": [{"id": int(k), **v} for k, v in S["chats"].items()] or cfg.get("chat_list", []),
            "days": cfg.get("days"), "history": S["history"], "last": S["last"]}


# ---------- ulanish (4 qadam) ----------

def _new_client(api_id: int, api_hash: str):
    from telethon import TelegramClient
    return TelegramClient(_session_path(), api_id, api_hash, device_model="Puls server", system_version="Linux",
                          app_version="Puls 1.0", lang_code="uz", system_lang_code="uz")


async def start_login(api_id: int, api_hash: str, phone: str) -> dict:
    await _drop_client()
    client = _new_client(api_id, api_hash)
    await client.connect()
    S.update(client=client, error="", phone=phone)
    if await client.is_user_authorized():
        save_cfg({**load_cfg(), "api_id": api_id, "api_hash": api_hash, "phone": phone})
        return await _authorized()
    sent = await client.send_code_request(phone)
    S.update(phone_hash=sent.phone_code_hash, step="code")
    save_cfg({**load_cfg(), "api_id": api_id, "api_hash": api_hash, "phone": phone})
    return status()


async def submit_code(code: str) -> dict:
    from telethon.errors import SessionPasswordNeededError
    client = S["client"]
    if client is None or S["step"] != "code":
        raise ValueError("Avval telefon raqamini yuboring")
    try:
        await client.sign_in(S["phone"], code.strip().replace(" ", ""), phone_code_hash=S["phone_hash"])
    except SessionPasswordNeededError:
        S["step"] = "password"
        return status()
    return await _authorized()


async def submit_password(password: str) -> dict:
    client = S["client"]
    if client is None or S["step"] != "password":
        raise ValueError("Avval kodni kiriting")
    await client.sign_in(password=password)
    return await _authorized()


async def _authorized() -> dict:
    me = await S["client"].get_me()
    S.update(step="chats", me={"name": " ".join(x for x in (me.first_name, me.last_name) if x), "username": me.username,
                               "id": me.id}, phone_hash=None)
    return status()


async def dialogs() -> list[dict]:
    """Akkaunt a'zo bo'lgan guruhlar: tanlash uchun."""
    client = S["client"]
    if client is None:
        raise ValueError("Akkaunt ulanmagan")
    out = []
    async for d in client.iter_dialogs(limit=300):
        if d.is_group:
            ent = d.entity
            out.append({"id": d.id, "title": d.name, "members": getattr(ent, "participants_count", None),
                        "selected": str(d.id) in S["chats"]})
    return out


async def choose(chat_ids: list[int], days: int) -> dict:
    """Kuzatiladigan guruhlar va tarix chuqurligi. Yangi qo'shilgan guruh tarixi fonda yuklanadi."""
    found = {d["id"]: d for d in await dialogs()}
    chats = {str(i): {"title": found[i]["title"]} for i in chat_ids if i in found}
    if not chats:
        raise ValueError("Kamida bitta guruhni tanlang")
    old = set(S["chats"])
    S["chats"] = chats
    save_cfg({**load_cfg(), "chats": list(chats), "chat_list": [{"id": int(k), **v} for k, v in chats.items()], "days": days})
    S["step"] = "on"
    _listen()
    for cid in chats:
        if cid not in old:
            asyncio.get_running_loop().create_task(_history(int(cid), days))
    return status()


async def logout() -> dict:
    client = S["client"]
    if client is not None:
        try:
            await client.log_out()
        except Exception as e:  # noqa: BLE001 — sessiya baribir o'chiriladi
            log.warning("chiqishda xato: %s", e)
    await _drop_client()
    for p in (_session_path() + ".session", str(_cfg_path())):
        try:
            os.remove(p)
        except OSError:
            pass
    S.update(step="off", me=None, chats={}, history={}, error="", phone=None)
    return status()


async def _drop_client() -> None:
    c = S.get("client")
    S["client"] = None
    if c is not None:
        try:
            await c.disconnect()
        except Exception:  # noqa: BLE001
            pass


# ---------- o'qish ----------

def _listen() -> None:
    from telethon import events
    client = S["client"]
    if getattr(client, "_puls_listening", False):
        return
    client._puls_listening = True
    client.add_event_handler(_on_new, events.NewMessage())
    client.add_event_handler(_on_edit, events.MessageEdited())
    client.add_event_handler(_on_delete, events.MessageDeleted())


def _watched(chat_id: int | None) -> bool:
    return chat_id is not None and str(chat_id) in S["chats"]


async def _incoming(msg, edited: bool, media: bool = True) -> Incoming | None:
    sender = await msg.get_sender()
    if sender is None or getattr(sender, "bot", False) or not hasattr(sender, "first_name"):
        return None  # botlar (shu jumladan Puls boti) va kanal nomidan yozilganlar hisobot emas
    chat = await msg.get_chat()
    inc = Incoming(msg.chat_id, getattr(chat, "title", "") or "", msg.id, sender.id,
                   " ".join(x for x in (sender.first_name, sender.last_name) if x) or "Noma'lum", sender.username,
                   msg.date.astimezone(config.TZ).replace(tzinfo=None), msg.message or "",
                   msg.reply_to_msg_id, edited)
    if media and not edited and (msg.voice or msg.video_note or msg.photo or msg.audio):
        size = getattr(getattr(msg, "file", None), "size", 0) or 0
        if size <= MEDIA_MAX:
            try:
                inc.media = await msg.download_media(bytes)
                inc.mime = "image/jpeg" if msg.photo else (msg.file.mime_type or "audio/ogg")
            except Exception as e:  # noqa: BLE001
                log.warning("fayl yuklanmadi: %s", e)
    return inc if (inc.text or inc.media) else None


def _db(fn, *args):
    with db.session() as conn:
        return fn(conn, *args)


async def _live(msg, edited: bool) -> None:
    if not _watched(msg.chat_id):
        return
    inc = await _incoming(msg, edited)
    if inc is None:
        return
    if inc.reply_to and await asyncio.to_thread(_db, board.find_by_message, inc.chat_id, inc.reply_to):
        return  # doska vazifasiga javob: uni bot ishlaydi (tugma va holat)
    await asyncio.sleep(LIVE_DELAY)
    if not edited:
        exists = await asyncio.to_thread(_db, lambda c: c.execute(
            "SELECT 1 FROM messages WHERE chat_id = ? AND msg_id = ?", (inc.chat_id, inc.msg_id)).fetchone())
        if exists:
            return  # bot ulgurdi
    if (await asyncio.to_thread(_db, settings.load))["assign_policy"] == "rahbar":
        inc.lead = await asyncio.to_thread(_db, load.is_lead, inc.user_id)
    await asyncio.to_thread(process, inc)
    S["last"] = config.now().strftime("%Y-%m-%d %H:%M:%S")


async def _on_new(event) -> None:
    try:
        await _live(event.message, False)
    except Exception:  # noqa: BLE001 — bitta xabar xatosi kuzatishni to'xtatmasin
        log.exception("akkaunt: yangi xabar")


async def _on_edit(event) -> None:
    try:
        await _live(event.message, True)
    except Exception:  # noqa: BLE001
        log.exception("akkaunt: tahrir")


async def _on_delete(event) -> None:
    """Superguruhda chat ma'lum; oddiy guruhda Telegram faqat xabar raqamini beradi."""
    chat = event.chat_id
    if chat is not None and not _watched(chat):
        return
    try:
        n = await asyncio.to_thread(_db, deleted, chat, list(event.deleted_ids))
        if n:
            log.info("akkaunt: %d ta xabar o'chirildi", n)
    except Exception:  # noqa: BLE001
        log.exception("akkaunt: o'chirish")


async def _history(chat_id: int, days: int) -> None:
    """Guruh tarixini eskidan yangiga o'qib bazaga yozadi: AI har 20 xabarni bitta so'rovda tushunadi."""
    client = S["client"]
    since = datetime.now(config.TZ) - timedelta(days=days)
    key = str(chat_id)
    S["history"][key] = {"title": S["chats"].get(key, {}).get("title", ""), "read": 0, "added": 0, "done": False}
    batch: list[Incoming] = []

    async def flush():
        if not batch:
            return
        title = S["history"][key]["title"]
        if await asyncio.to_thread(_db, lambda c: appeals.is_support(c, chat_id, title)):
            # yordam guruhi: har xabar suhbat konteksti bilan murojaat sifatida o'qiladi (tartib muhim: savol -> javob)
            def write_support(conn):
                return sum(0 if appeals.handle(conn, i, True).duplicate else 1 for i in batch)
            S["history"][key]["added"] += await asyncio.to_thread(_db, write_support)
            batch.clear()
            return
        projects = await asyncio.to_thread(_db, load_projects)
        today = config.now().date()

        def sort(conn):
            S = settings.load(conn)
            # ulanmaganning xabari ingest'da saqlanib o'tkaziladi; tegli hisobot va suhbat AI'siz o'qiladi
            return [False if not accepted(conn, i, S) else triage(conn, i, S) for i in batch]
        parsed = await asyncio.to_thread(_db, sort)
        need = [n for n, p in enumerate(parsed) if p is None]
        if need and config.ai_enabled():
            got = await asyncio.to_thread(ai.extract_many, [(batch[n].text, batch[n].user_name) for n in need], projects, today)
            for n, p in zip(need, got):
                parsed[n] = p
        parsed = [p or None for p in parsed]

        def write(conn):
            added = 0
            for inc, pre in zip(batch, parsed):
                if not ingest(conn, inc, use_ai=False, pre=pre).duplicate:
                    added += 1
            return added
        S["history"][key]["added"] += await asyncio.to_thread(_db, write)
        batch.clear()

    try:
        async for msg in client.iter_messages(chat_id, offset_date=since, reverse=True):
            S["history"][key]["read"] += 1
            inc = await _incoming(msg, False, media=False)
            if inc is None or not inc.text:
                continue
            batch.append(inc)
            if len(batch) >= HISTORY_BATCH:
                await flush()
        await flush()
    except Exception as e:  # noqa: BLE001
        log.exception("akkaunt: tarix")
        S["history"][key]["error"] = str(e)[:200]
    S["history"][key]["done"] = True


async def run() -> None:
    """Dastur bilan birga: avval ulangan akkaunt bo'lsa, qayta ulanadi va kuzatishni davom ettiradi."""
    global LOOP
    LOOP = asyncio.get_running_loop()
    cfg = load_cfg()
    if not (cfg.get("api_id") and cfg.get("api_hash") and os.path.exists(_session_path() + ".session")):
        return
    try:
        client = _new_client(int(cfg["api_id"]), cfg["api_hash"])
        await client.connect()
        if not await client.is_user_authorized():
            S.update(step="off", error="Sessiya bekor qilingan: akkauntni qayta ulang")
            await client.disconnect()
            return
        S["client"] = client
        await _authorized()
        S["chats"] = {str(c): {"title": next((x["title"] for x in cfg.get("chat_list", []) if x["id"] == int(c)), "")}
                      for c in cfg.get("chats", [])}
        if S["chats"]:
            S["step"] = "on"
            _listen()
        log.info("Telegram akkaunt: %s, %d guruh kuzatilmoqda", S["me"]["name"], len(S["chats"]))
    except Exception as e:  # noqa: BLE001 — akkaunt ulanmasa ham panel va bot ishlaydi
        log.warning("Telegram akkaunt ulanmadi: %s", e)
        S.update(step="off", error=str(e)[:200])
