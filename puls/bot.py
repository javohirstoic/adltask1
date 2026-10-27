"""Telegram bot (aiogram 3).

Guruhdagi har bir xabarni o'qiydi va tushunganini reaksiya bilan bildiradi:
✍ vazifa yozildi, 👍 bajarildi, 👀 muammo qayd etildi, 🫡 muddat saqlandi.
Guruhga ortiqcha xabar yozmaydi. Faqat uch holatda gapiradi: #task da loyiha yo'q bo'lsa,
ishi ko'p xodimga vazifa berilsa (bo'shroq hamkasbni tavsiya qiladi) va "Faqat rahbarlar"
sozlamasida oddiy xodim boshqaga vazifa yozsa (o'sha xodimdan qabul qilishni so'raydi).
"""
import asyncio
import logging
import re
import time
from datetime import timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, ReactionTypeEmoji, ReplyParameters)

from . import actions, analytics, appeals, board, config, db, ingest, load, settings
from . import report as day_report  # "report" nomi /hisobot buyrug'i funksiyasida band
from .ingest import Incoming, backfill_audit, backfill_report_days, clean_name, ensure_group_projects, process, welcome_back

log = logging.getLogger("puls.bot")
router = Router()
REACTION = {"task": "✍", "done": "👍", "blocker": "👀", "request": "👀", "deadline": "🫡", "reassign": "👌"}

REPORT_SAMPLE = ("<code>#hisobot #LoyihaNomi\n"
                 "Bajarildi:\n1. Login sahifasi API ga ulandi\n2. Hisobot eksporti tayyorlandi\n"
                 "Jarayonda:\n1. To'lov moduli\n"
                 "Reja:\n1. Yuklama testlari</code>")
GUIDE = (
    "<b>Puls qanday ishlaydi</b>\n\n"
    "Kunlik hisobotni <b>#hisobot</b> tegi bilan yozing, shunda u adashmasdan o'qiladi:\n\n"
    + REPORT_SAMPLE + "\n\n"
    "Vazifa berish: <code>#task #LoyihaNomi Login sahifasi @ali</code>\n"
    "Bitta ish bajarildi: <code>#done #LoyihaNomi Login sahifasi</code>\n"
    "Ishni to'xtatgan muammo: <code>#muammo #LoyihaNomi Serverga ruxsat yo'q</code>\n"
    "Loyiha muddati: <code>#deadline #LoyihaNomi 15.11.2026</code>\n\n"
    "Vazifa xabariga javob (reply) qilib <code>#done</code> desangiz, o'sha vazifa yopiladi, «25-oktyabrgacha» desangiz, "
    "muddat shu vazifaga yoziladi. Oddiy suhbat hisobotga kirmaydi.\n\n"
    "Buyruqlar: /hisobot — guruhning bugungi xulosasi, /bugun — bugun bajarilganlar Excel faylda, /loyihalar — loyihalar holati, /bolim — bo'limingiz, /panel — panel havolasi."
)
LINKED_ONLY = "Hisobot faqat shaxsiy havola orqali botga ulangan xodimdan qabul qilinadi: havolani rahbar beradi.\n\n"
CMD_REPORT_RE = re.compile(r"^/hisobot(?:@\w+)?(?=\s|$)", re.I)


def report_text(text: str) -> str | None:
    """"/hisobot" ortidan ish yozilgan bo'lsa — bu buyruq emas, xodimning hisoboti: #hisobot tegiga aylantiriladi."""
    if CMD_REPORT_RE.match(text) and CMD_REPORT_RE.sub("", text).strip():
        return CMD_REPORT_RE.sub("#hisobot", text, count=1)
    return None


def guide() -> str:
    """Yo'riqnoma joriy qabul qoidasiga mos: "faqat ulanganlar" gapi shu sozlama yoqilgandagina aytiladi."""
    with db.session() as conn:
        linked_only = settings.load(conn)["report_from"] == "ulangan"
    return GUIDE.replace("Buyruqlar:", LINKED_ONLY + "Buyruqlar:") if linked_only else GUIDE


def _panel_kb() -> InlineKeyboardMarkup | None:
    if not config.PANEL_URL.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Panelni ochish", url=config.PANEL_URL)]])


MEDIA_MAX = 20 * 1024 * 1024  # Bot API shundan katta faylni yuklab bermaydi


def _media(m: Message):
    """(fayl, mime): ovozli xabar, audio, video-xabar yoki rasm. Boshqa fayllar o'qilmaydi."""
    if m.voice:
        return m.voice, m.voice.mime_type or "audio/ogg"
    if m.video_note:
        return m.video_note, "video/mp4"
    if m.audio:
        return m.audio, m.audio.mime_type or "audio/mpeg"
    if m.photo:
        return m.photo[-1], "image/jpeg"
    if m.document and (m.document.mime_type or "").startswith(("image/", "audio/")):
        return m.document, m.document.mime_type
    return None, None


def _incoming(m: Message, edited: bool = False) -> Incoming | None:
    text = m.text or m.caption or ""
    text = report_text(text) or text
    has_media = _media(m)[0] is not None
    if (not text and not has_media) or not m.from_user or m.from_user.is_bot or text.startswith("/"):
        return None
    user = m.from_user
    chat_title = m.chat.title or ("Shaxsiy: %s" % user.full_name)
    origin = getattr(m, "forward_origin", None)  # forward qilingan: asl vaqti (kechagi hisobot bugun forward qilinishi mumkin)
    fwd = origin.date.astimezone(config.TZ).replace(tzinfo=None) if origin is not None and getattr(origin, "date", None) else None
    return Incoming(
        chat_id=m.chat.id, chat_title=chat_title, msg_id=m.message_id, user_id=user.id,
        user_name=user.full_name, username=user.username,
        date=m.date.astimezone(config.TZ).replace(tzinfo=None),  # tahrirlansa ham asl yuborilgan vaqt
        text=text, reply_to=m.reply_to_message.message_id if m.reply_to_message else None, edited=edited, forwarded_at=fwd,
    )


def _db(fn, *args):
    """Bitta bazaviy amal o'z ulanishida (botning asinxron oqimidan tashqarida chaqiriladi)."""
    with db.session() as conn:
        return fn(conn, *args)


_ADMINS: dict[int, tuple[float, set[int]]] = {}


async def _is_admin(bot: Bot, chat_id: int | None, user_id: int) -> bool:
    """Guruh adminlari rahbar hisoblanadi. Ro'yxat 10 daqiqa eslab qolinadi."""
    if not chat_id or chat_id > 0:
        return False
    cached = _ADMINS.get(chat_id)
    if cached is None or time.monotonic() - cached[0] > 600:
        try:
            cached = (time.monotonic(), {a.user.id for a in await bot.get_chat_administrators(chat_id)})
        except Exception as e:  # noqa: BLE001
            log.debug("adminlar olinmadi: %s", e)
            cached = (time.monotonic(), set())
        _ADMINS[chat_id] = cached
    return user_id in cached[1]


def _keyboard(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def _dm_of(conn, user_id: int) -> int | None:
    row = conn.execute("SELECT dm_chat_id FROM people WHERE id = ?", (user_id,)).fetchone()
    return row["dm_chat_id"] if row else None


async def _ask(m: Message, alert: dict, private: bool = False) -> None:
    """Savolni yuboradi: guruhda vazifa xabariga javob qilib yoki (sozlamaga ko'ra) vazifa berganga shaxsan."""
    dm = await asyncio.to_thread(_db, _dm_of, m.from_user.id) if private else None
    try:
        if dm:
            sent = await m.bot.send_message(dm, alert["text"] + "\n\nGuruh: %s" % analytics._esc(m.chat.title or ""),
                                            reply_markup=_keyboard(alert["buttons"]))
        else:
            sent = await m.reply(alert["text"], reply_markup=_keyboard(alert["buttons"]))
        await asyncio.to_thread(_db, load.sent, alert["id"], sent.chat.id, sent.message_id)
    except Exception as e:  # noqa: BLE001 — savol yuborilmasa ham vazifa yozilgan
        log.warning("savol yuborilmadi: %s", e)


async def _handle(m: Message, edited: bool = False) -> None:
    inc = _incoming(m, edited)
    if inc is None:
        return
    file, mime = _media(m)
    if file is not None and not edited and (getattr(file, "file_size", 0) or 0) <= MEDIA_MAX:
        try:
            inc.media, inc.mime = (await m.bot.download(file)).getvalue(), mime
        except Exception as e:  # noqa: BLE001 — fayl yuklanmasa, izohi bilan davom etamiz
            log.warning("fayl yuklanmadi: %s", e)
    if not inc.text and inc.media is None:
        return
    # Doskadan berilgan vazifa xabariga javob: "tushundim", "50%", "bajardim", savol yoki to'siq
    tid = await asyncio.to_thread(_db, board.find_by_message, m.chat.id, inc.reply_to) if inc.reply_to else None
    if tid and not edited:
        await _board_reply(m, tid, inc)
        return
    inc.admin = await _is_admin(m.bot, m.chat.id, inc.user_id)  # guruh admini: topshirig'i jamoaga, o'z ishi emas
    if (await asyncio.to_thread(_db, settings.load))["assign_policy"] == "rahbar":
        inc.lead = await asyncio.to_thread(_db, load.is_lead, inc.user_id) or inc.admin
    res = await asyncio.to_thread(process, inc)
    if res.duplicate or res.skipped:
        return  # akkaunt orqali allaqachon yozilgan yoki yozgan kishi botga ulanmagan: bot jim turadi
    # Eski ish qayta yozilgan bo'lsa ham bot odatdagidek qabul qiladi: xodim sezmaydi, rahbar panelda ko'radi.
    # Reaksiya sozlamada yoqilgan bo'lsagina qo'yiladi (standart: bot guruhda jim)
    if (await asyncio.to_thread(_db, settings.load))["bot_react"] == "on":
        emoji = "🤔" if res.missing_project else REACTION.get(res.kind)
        try:
            await m.bot.set_message_reaction(m.chat.id, m.message_id, [ReactionTypeEmoji(emoji=emoji)] if emoji else [])
        except Exception as e:  # reaksiya taqiqlangan guruh bo'lishi mumkin — ish to'xtamaydi
            log.debug("reaksiya qo'yilmadi: %s", e)
    if edited:
        return
    if res.missing_project and res.source == "format":
        await m.reply("Qaysi loyiha? Loyiha tegini qo'shing, masalan: <code>#hisobot #Portal</code> yoki <code>#task #Portal ...</code>")
    if res.proposed:
        for alert in await asyncio.to_thread(_db, load.propose, res.proposed, inc.user_id, inc.user_name, m.chat.id, m.message_id):
            await _ask(m, alert)
    if res.task_ids:
        for alert in await asyncio.to_thread(_db, load.check, res.task_ids, inc.user_id, m.chat.id, m.message_id):
            await _ask(m, alert, private=alert["mode"] == "shaxsan")


async def board_sync(bot: Bot, task_id: int, new: bool = False) -> str:
    """Vazifa xabarini guruhga yuboradi (new) yoki bor xabarni hozirgi holatga moslab tahrirlaydi."""
    text, rows, chat = await asyncio.to_thread(_db, board.message, task_id)
    if chat is None:
        return "Namuna guruh: Telegramga yuborilmadi"
    kb = _keyboard(rows) if rows else None
    t = await asyncio.to_thread(_db, lambda c: c.execute("SELECT tg_chat, tg_msg FROM tasks WHERE id = ?", (task_id,)).fetchone())
    try:
        if not new and t["tg_msg"]:
            await bot.edit_message_text(text, chat_id=t["tg_chat"], message_id=t["tg_msg"], reply_markup=kb)
            return "Guruhdagi xabar yangilandi"
        sent = await bot.send_message(chat, text, reply_markup=kb)
    except Exception as e:  # noqa: BLE001 — xabar o'zgarmagan bo'lsa ham Telegram xato qaytaradi
        if "not modified" in str(e):
            return "Guruhdagi xabar yangilandi"
        log.warning("doska xabari yuborilmadi: %s", e)
        return "Telegramga yuborilmadi"

    def save(conn):
        conn.execute("UPDATE tasks SET tg_chat = ?, tg_msg = ? WHERE id = ?", (sent.chat.id, sent.message_id, task_id))
        db.bump_version(conn)
    await asyncio.to_thread(_db, save)
    return "Guruhga yuborildi"


async def board_post(bot: Bot, task_id: int, text: str, who: str) -> str:
    """Menejerning paneldagi izohi guruhga: vazifa xabariga javob sifatida. Xodim unga javob yozsa ham shu vazifaga boradi."""
    t = await asyncio.to_thread(_db, lambda c: c.execute("SELECT tg_chat, tg_msg, assignee FROM tasks WHERE id = ?", (task_id,)).fetchone())
    if not t or not t["tg_msg"]:
        return "Vazifa guruhga yuborilmagan: izoh faqat panelda"
    to = await asyncio.to_thread(_db, board.mention, t["assignee"])
    body = "%s, %s: %s" % (analytics._esc(to), analytics._esc(who), analytics._esc(text))
    try:
        sent = await bot.send_message(t["tg_chat"], body,
                                      reply_parameters=ReplyParameters(message_id=t["tg_msg"], allow_sending_without_reply=True))
    except Exception as e:  # noqa: BLE001
        log.warning("izoh yuborilmadi: %s", e)
        return "Telegramga yuborilmadi"
    await asyncio.to_thread(_db, lambda c: c.execute(
        "UPDATE task_events SET msg = ? WHERE id = (SELECT max(id) FROM task_events WHERE task_id = ? AND kind = 'comment')",
        (sent.message_id, task_id)))
    return "Guruhga yuborildi"


async def board_cancel(bot: Bot, chat_id: int, msg_id: int, title: str, note: str = "Vazifa bekor qilindi") -> str:
    """O'chirilgan yoki boshqaga berilgan vazifa: guruhdagi eski xabarda tugmalar qolmaydi."""
    try:
        await bot.edit_message_text("<s>%s</s>\n%s" % (analytics._esc(title), note), chat_id=chat_id, message_id=msg_id)
        return "Guruhdagi xabarda bekor qilindi deb yozildi"
    except Exception as e:  # noqa: BLE001
        log.warning("bekor qilish yozilmadi: %s", e)
        return "Telegramdagi xabar o'zgarmadi"


async def board_reminder_loop(bot: Bot) -> None:
    """Har 5 daqiqada: "Tushundim" demagan va muddati ertaga bo'lgan vazifalar bo'yicha guruhda eslatma."""
    while True:
        await asyncio.sleep(300)
        try:
            due = await asyncio.to_thread(_db, board.reminders)
        except Exception as e:  # noqa: BLE001
            log.warning("eslatmalar olinmadi: %s", e)
            continue
        for tid, chat, msg, kind, text in due:
            sent = None
            try:
                sent = await bot.send_message(chat, analytics._esc(text),
                                              reply_parameters=ReplyParameters(message_id=msg, allow_sending_without_reply=True))
            except Exception as e:  # noqa: BLE001
                log.warning("eslatma yuborilmadi (%s): %s", tid, e)
            await asyncio.to_thread(_db, board.reminded, tid, kind, sent.message_id if sent else None)


async def _board_reply(m: Message, task_id: int, inc: Incoming) -> None:
    text = inc.text
    if inc.media is not None:
        from . import ai
        heard = await asyncio.to_thread(ai.transcribe, inc.media, inc.mime or "application/octet-stream", inc.text)
        text = " ".join(x for x in (heard, inc.text) if x)
    who = await asyncio.to_thread(_db, board.who_name, inc.user_id, inc.user_name)
    admin = await _is_admin(m.bot, m.chat.id, inc.user_id)
    if not await asyncio.to_thread(_db, board.may_act, task_id, inc.user_id, inc.username, admin):
        await asyncio.to_thread(_db, board.heard, task_id, text or "", who)
        return
    emoji = await asyncio.to_thread(_db, board.reply, task_id, text or "", who)
    if emoji:
        if (await asyncio.to_thread(_db, settings.load))["bot_react"] == "on":  # standart: reaksiyasiz
            try:
                await m.bot.set_message_reaction(m.chat.id, m.message_id, [ReactionTypeEmoji(emoji=emoji)])
            except Exception as e:  # noqa: BLE001
                log.debug("reaksiya qo'yilmadi: %s", e)
        await board_sync(m.bot, task_id)


@router.callback_query(F.data.regexp(r"^bd:\d+:(ok|q|25|50|75|done|blk)$"))
async def board_pick(q: CallbackQuery) -> None:
    """Doska vazifasidagi tugma: Tushundim, Savolim bor, foiz, Bajardim, To'siq bor."""
    _, tid, choice = q.data.split(":")
    chat_id = q.message.chat.id if q.message else None
    admin = await _is_admin(q.bot, chat_id, q.from_user.id) if chat_id else False
    if not await asyncio.to_thread(_db, board.may_act, int(tid), q.from_user.id, q.from_user.username, admin):
        await q.answer("Bu vazifa boshqa xodimga berilgan", show_alert=True)
        return
    who = await asyncio.to_thread(_db, board.who_name, q.from_user.id, q.from_user.full_name)
    answer = await asyncio.to_thread(_db, board.act, int(tid), choice, who)
    await q.answer(answer, show_alert=choice in ("q", "blk"))
    await board_sync(q.bot, int(tid))


@router.callback_query(F.data.regexp(r"^(yk|tk):\d+:\w+$"))
async def alert_pick(q: CallbackQuery) -> None:
    """Botning savoliga javob: yuklama (kimga berish) yoki taklif (qabul / rad)."""
    _, aid, choice = q.data.split(":")
    alert = await asyncio.to_thread(_db, load.get, int(aid))
    if alert is None:
        await q.answer("Bu savol eskirgan", show_alert=True)
        return
    admin = await _is_admin(q.bot, alert["chat_id"], q.from_user.id)
    if not await asyncio.to_thread(_db, load.may_decide, alert, q.from_user.id, q.from_user.username, admin):
        await q.answer("Buni vazifa bergan kishi yoki rahbar hal qiladi" if alert["kind"] == "yuklama"
                       else "Buni vazifa yozilgan xodim yoki rahbar hal qiladi", show_alert=True)
        return
    res = await asyncio.to_thread(_db, load.resolve, int(aid), choice, q.from_user.full_name)
    await q.answer(res.get("answer", ""))
    if res.get("text") and q.message:
        try:
            await q.message.edit_text(res["text"], reply_markup=None)
        except Exception as e:  # noqa: BLE001
            log.debug("savol tahrirlanmadi: %s", e)
    for chat_id, text in res.get("notify", []):
        try:
            await q.bot.send_message(chat_id, text)
        except Exception as e:  # noqa: BLE001
            log.warning("yangi mas'ulga xabar ketmadi: %s", e)


def _link_person(token: str, chat_id: int) -> str | None:
    """Shaxsiy havola orqali kelgan xodimni topib, chat id ni yozadi. Qayta bossa — yangilaydi.
    Ulanmasdan oldin guruhga yozgan hisobotlari darhol qayta o'qiladi (ular ham hisobga kiradi)."""
    with db.session() as conn:
        row = conn.execute("SELECT id, name FROM people WHERE invite_token = ?", (token,)).fetchone()
        if row is None:
            return None
        pid = actions.claim_person(conn, row, chat_id)  # panelda qo'lda qo'shilgan xodim: haqiqiy akkauntiga bog'lanadi
        conn.execute("UPDATE people SET dm_chat_id = ?, dm_linked_at = ?, status = CASE WHEN status = 'begona' THEN NULL "
                     "ELSE status END WHERE id = ?", (chat_id, config.now().strftime("%Y-%m-%d %H:%M:%S"), pid))
        db.bump_version(conn)
    welcome_back(pid)
    return row["name"]


@router.message(CommandStart(deep_link=True), F.chat.type == ChatType.PRIVATE)
async def start_linked(m: Message, command: CommandObject) -> None:
    name = await asyncio.to_thread(_link_person, (command.args or "").strip(), m.chat.id)
    if name is None:
        await m.answer("Havola eskirgan. Rahbardan yangi havola so'rang.")
        return
    await m.answer("%s, siz Puls'ga ulandingiz. Endi ish guruhiga yozgan hisobotlaringiz hisobga olinadi, "
                   "rahbarning shaxsiy eslatmalari esa shu yerga keladi.\n\n"
                   "Hisobotni har kuni shu ko'rinishda yozing:\n\n%s" % (analytics._esc(name.split()[0]), REPORT_SAMPLE))


@router.message(CommandStart())
async def start(m: Message) -> None:
    if await asyncio.to_thread(_support_chat, m.chat.id):
        return  # yordam guruhida bot jim
    await m.answer("Assalomu alaykum! Men <b>Puls</b> — ish guruhidagi vazifa va hisobotlardan loyihalar holatini "
                   "hisoblab beraman.\n\nMeni ish guruhiga qo'shing va admin qiling.\n\n" + await asyncio.to_thread(guide),
                   reply_markup=_panel_kb())


@router.message(Command("yordam", "help"))
async def help_(m: Message) -> None:
    if await asyncio.to_thread(_support_chat, m.chat.id):
        return  # yordam guruhida bot jim
    await m.answer(await asyncio.to_thread(guide))


@router.message(Command("panel"))
async def panel(m: Message) -> None:
    if await asyncio.to_thread(_support_chat, m.chat.id):
        return  # yordam guruhida bot jim
    kb = _panel_kb()
    await m.answer("Panel: %s" % config.PANEL_URL if kb is None else "Panel shu yerda:", reply_markup=kb)


@router.message(Command("hisobot"))
async def report(m: Message) -> None:
    if await asyncio.to_thread(_support_chat, m.chat.id):
        return  # yordam guruhida bot jim
    if report_text(m.text or m.caption or ""):
        await _handle(m)
        return
    chat = m.chat.id if m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else None
    with db.session() as conn:
        text = analytics.digest_text(conn, chat_id=chat)
    await m.answer(text, reply_markup=_panel_kb())


@router.message(Command("bugun"))
async def today_done(m: Message) -> None:
    """Shu guruhda bugun bajarilgan vazifalar, Excel fayl bilan (kechki yuborishni kutmasdan)."""
    if await asyncio.to_thread(_support_chat, m.chat.id):
        return  # yordam guruhida bot jim
    if m.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await m.answer("Bu buyruq ish guruhida ishlaydi.")
        return
    await _send_report(m.bot, m.chat.id, config.now().date(), empty_note=True)


async def _send_report(bot: Bot, chat_id: int, day, empty_note: bool = False) -> None:
    with db.session() as conn:
        built = day_report.build(conn, chat_id, day)
    if built is None:
        if empty_note:
            await bot.send_message(chat_id, "Bugun bu guruhda bajarilgan vazifa hali yo'q.")
        return
    data, name, caption = built
    await bot.send_document(chat_id, BufferedInputFile(data, filename=name), caption=caption)


@router.message(Command("loyihalar"))
async def projects(m: Message) -> None:
    if await asyncio.to_thread(_support_chat, m.chat.id):
        return  # yordam guruhida bot jim
    chat = m.chat.id if m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else None
    with db.session() as conn:
        data = analytics.compute(conn, "week", chat_id=chat)
    if not data["projects"]:
        await m.answer("Hali loyiha yo'q. Birinchi vazifani yozing: <code>#task #LoyihaNomi ...</code>")
        return
    lines = ["<b>Loyihalar — so'nggi 7 kun</b>", ""]
    for p in data["projects"][:15]:
        dl = (" · muddat %s" % p["deadline_label"]) if p["deadline_label"] else ""
        lines.append("<b>%s</b> — %s, %s%% bajarilgan%s" % (analytics._esc(p["name"]), p["status"].lower(), p["progress"], dl))
        if p["risks"]:
            lines.append("    " + analytics._esc(p["risks"][0]["text"]))
    await m.answer("\n".join(lines), reply_markup=_panel_kb())


@router.message(Command("bolim"))
async def department(m: Message, command: CommandObject) -> None:
    if await asyncio.to_thread(_support_chat, m.chat.id):
        return  # yordam guruhida bot jim
    if command.args:
        await _set_dept(m.from_user.id, m.from_user.full_name, m.from_user.username, command.args.strip())
        await m.answer("Bo'limingiz saqlandi: <b>%s</b>" % analytics._esc(command.args.strip()[:40]))
        return
    rows = [[InlineKeyboardButton(text=d, callback_data="bolim:" + d) for d in db.DEPARTMENTS[i:i + 3]]
            for i in range(0, len(db.DEPARTMENTS), 3)]
    await m.answer("Qaysi bo'limda ishlaysiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("bolim:"))
async def department_pick(q: CallbackQuery) -> None:
    dept = q.data.split(":", 1)[1]
    await _set_dept(q.from_user.id, q.from_user.full_name, q.from_user.username, dept)
    await q.answer("Saqlandi: " + dept)
    if q.message:
        await q.message.edit_text("%s — bo'lim: <b>%s</b>" % (analytics._esc(q.from_user.full_name), dept))


async def _set_dept(uid: int, name: str, username: str | None, dept: str) -> None:
    def save():
        with db.session() as conn:
            conn.execute("INSERT INTO people(id, name, username, department) VALUES(?, ?, ?, ?) "
                         "ON CONFLICT(id) DO UPDATE SET department = excluded.department",
                         (uid, clean_name(name), username, dept[:40]))
            db.bump_version(conn)
    await asyncio.to_thread(save)


def _chat_joined(chat_id: int, title: str) -> bool:
    """Bot guruhga qo'shilishi bilan guruh bazaga yoziladi: birinchi xabarni kutmasdan panelda ko'rinadi.
    Qaytaradi: yordam guruhimi (unda bot jim turadi, salomlashmaydi)."""
    with db.session() as conn:
        conn.execute("INSERT INTO chats(id, title, demo, added_at) VALUES(?, ?, 0, ?) ON CONFLICT(id) DO UPDATE SET title = excluded.title",
                     (chat_id, title, config.now().strftime("%Y-%m-%d %H:%M:%S")))
        support = appeals.is_support(conn, chat_id, title)
        if support:
            appeals.support_project(conn, chat_id, title)  # yordam guruhi: tizimi (loyihasi) darhol Murojaatlarda ko'rinadi
        else:
            ensure_group_projects(conn)  # "guruh" rejimida guruh darhol loyiha bo'lib Loyihalarda ko'rinadi
        db.bump_version(conn)
    return support


def _support_chat(chat_id: int) -> bool:
    """Yordam guruhida bot hech narsa yozmaydi: buyruqlarga ham javob bermaydi (ichki ma'lumot foydalanuvchilarga chiqmasin)."""
    if not chat_id or chat_id > 0:
        return False
    with db.session() as conn:
        return appeals.chat_kind(conn, chat_id) == "yordam"


def _migrated(old: int, new: int, title: str) -> None:
    """Oddiy guruh superguruhga aylandi (Telegram ID ni almashtiradi). Loyihalar va bot savollari yangi ID ga o'tadi.
    Eski xabarlar o'z joyida qoladi: superguruhda xabar raqamlari yangidan boshlanadi, ko'chirilsa to'qnashadi."""
    with db.session() as conn:
        conn.execute("INSERT INTO chats(id, title, demo, added_at) VALUES(?, ?, 0, ?) ON CONFLICT(id) DO UPDATE SET title = excluded.title",
                     (new, title, config.now().strftime("%Y-%m-%d %H:%M:%S")))
        for table in ("projects", "alerts", "decisions"):
            conn.execute("UPDATE %s SET chat_id = ? WHERE chat_id = ?" % table, (new, old))
        conn.execute("UPDATE chats SET title = ? WHERE id = ?", ("%s (oldingi)" % title, old))
        db.bump_version(conn)


@router.message(F.migrate_to_chat_id)
async def migrated(m: Message) -> None:
    log.info("guruh superguruhga aylandi: %s %s -> %s", m.chat.title, m.chat.id, m.migrate_to_chat_id)
    await asyncio.to_thread(_migrated, m.chat.id, m.migrate_to_chat_id, m.chat.title or "")


@router.message(F.new_chat_members)
async def members_joined(m: Message) -> None:
    """Guruhga odam qo'shildi: hali yozmagan bo'lsa ham panelda ko'rinadi va bugun yozmasa "yozmadi" ro'yxatiga tushadi."""
    when = m.date.astimezone(config.TZ).strftime("%Y-%m-%d %H:%M:%S")
    for u in m.new_chat_members:
        if not u.is_bot:
            log.info("guruhga qo'shildi: %s %s (%s)", m.chat.title, u.full_name, u.id)
            await asyncio.to_thread(_db, ingest.member_joined, m.chat.id, m.chat.title or "", u.id, u.full_name, u.username, when)


@router.message(F.left_chat_member)
async def member_left(m: Message) -> None:
    u = m.left_chat_member
    if not u.is_bot:
        log.info("guruhdan chiqdi: %s %s (%s)", m.chat.title, u.full_name, u.id)
        await asyncio.to_thread(_db, ingest.member_left, m.chat.id, u.id, m.date.astimezone(config.TZ).strftime("%Y-%m-%d %H:%M:%S"))


@router.my_chat_member()
async def added(event: ChatMemberUpdated) -> None:
    if event.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    old, new = event.old_chat_member.status, event.new_chat_member.status
    log.info("bot guruhda: %s (%s) %s -> %s, qo'shgan: %s", event.chat.title, event.chat.id, old, new,
             event.from_user.full_name if event.from_user else "?")
    if new in ("member", "administrator"):
        support = await asyncio.to_thread(_chat_joined, event.chat.id, event.chat.title or "")
        if old in ("left", "kicked") and not support:
            await event.bot.send_message(event.chat.id, "Salom! Men shu guruhdagi hisobot va vazifalarni kuzatib boraman.\n\n"
                                         + await asyncio.to_thread(guide))


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP, ChatType.PRIVATE}))
async def on_message(m: Message) -> None:
    await _handle(m)


@router.edited_message()
async def on_edit(m: Message) -> None:
    await _handle(m, edited=True)


async def digest_loop(bot: Bot) -> None:
    """Har ish kuni ertalab va kechqurun (vaqti Sozlamalarda) rahbarga (DIGEST_CHAT_ID) brifing."""
    sent: set[str] = set()
    while True:
        await asyncio.sleep(30)
        now = config.now()
        if now.weekday() >= 5 or not config.DIGEST_CHAT_ID:
            continue
        with db.session() as conn:
            S = settings.load(conn)
        for key, morning in (("digest_morning", True), ("digest_evening", False)):
            stamp = "%s %s" % (now.date(), key)
            if stamp in sent or now.strftime("%H:%M") < S[key] or now.strftime("%H:%M") > _plus(S[key], 20):
                continue
            sent.add(stamp)
            try:
                with db.session() as conn:
                    text = analytics.digest_text(conn, morning=morning)
                await bot.send_message(config.DIGEST_CHAT_ID, text, reply_markup=_panel_kb())
            except Exception as e:
                log.warning("brifing yuborilmadi: %s", e)


async def group_report_loop(bot: Bot) -> None:
    """Har ish kuni belgilangan vaqtda har bir ish guruhiga o'sha guruhda bugun bajarilgan vazifalar (Excel)."""
    sent: set[str] = set()
    while True:
        await asyncio.sleep(30)
        now = config.now()
        if now.weekday() >= 5:
            continue
        with db.session() as conn:
            S = settings.load(conn)
            targets = day_report.chats(conn)
        hhmm = now.strftime("%H:%M")
        stamp = str(now.date())
        if S["group_report"] == "off" or stamp in sent or hhmm < S["group_report_time"] or hhmm > _plus(S["group_report_time"], 20):
            continue
        sent.add(stamp)
        for chat_id in targets:
            try:
                await _send_report(bot, chat_id, now.date())
            except Exception as e:  # noqa: BLE001 — bitta guruh xatosi boshqalarini to'xtatmaydi
                log.warning("guruh hisoboti yuborilmadi (%s): %s", chat_id, e)


def _plus(hhmm: str, minutes: int) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    total = min(23 * 60 + 59, h * 60 + m + minutes)
    return "%02d:%02d" % (total // 60, total % 60)


async def run_bot() -> None:
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="hisobot", description="Bugungi xulosa"),
        BotCommand(command="bugun", description="Bugun bajarilgan vazifalar (Excel)"),
        BotCommand(command="loyihalar", description="Loyihalar holati"),
        BotCommand(command="bolim", description="Bo'limingizni belgilash"),
        BotCommand(command="panel", description="Panel havolasi"),
        BotCommand(command="yordam", description="Qanday yozish kerak"),
    ])
    actions.BOT, actions.LOOP = bot, asyncio.get_running_loop()
    await asyncio.to_thread(_db, ensure_group_projects)  # loyihasi hali yo'q guruhlar ("guruh" rejimida)
    await asyncio.to_thread(_db, backfill_report_days)  # eski hisobotlarga hisobot kuni va holat (bir marta)
    await asyncio.to_thread(_db, backfill_audit)  # 25.10 tekshiruvi: nusxa, davom etayotgan ish, forward kuni (bir marta)
    asyncio.create_task(digest_loop(bot))
    asyncio.create_task(group_report_loop(bot))
    asyncio.create_task(board_reminder_loop(bot))
    while True:
        try:
            await dp.start_polling(bot, allowed_updates=["message", "edited_message", "callback_query", "my_chat_member"],
                                   handle_signals=False)
            return
        except Exception as e:  # internet uzilsa — kutib qayta ulanadi, panel ishlashda davom etadi
            log.warning("bot to'xtadi, 10 soniyadan keyin qayta ulanadi: %s", e)
            await asyncio.sleep(10)
