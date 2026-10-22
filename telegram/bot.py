"""Telegram bot (aiogram 3).

Guruhdagi har bir xabarni o'qiydi va tushunganini reaksiya bilan bildiradi:
✍ vazifa yozildi, 👍 bajarildi, 👀 muammo qayd etildi, 🫡 muddat saqlandi.
Guruhga ortiqcha xabar yozmaydi. Faqat uch holatda gapiradi: #task da loyiha yo'q bo'lsa,
ishi ko'p xodimga vazifa berilsa (bo'shroq hamkasbni tavsiya qiladi) va "Faqat rahbarlar"
sozlamasida oddiy xodim boshqaga vazifa yozsa (o'sha xodimdan qabul qilishni so'raydi).

Django ORM sinxron, shuning uchun bazaga tegadigan hamma narsa `db(...)` orqali alohida oqimda bajariladi.
"""
import asyncio
import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, ReactionTypeEmoji)
from django.conf import settings as dj
from django.db import close_old_connections

from actions import load
from analytics import services as analytics
from core import appsettings, conf
from core.models import DataVersion
from ingest.services import Incoming, process
from people.models import Department, Person
from people.services import clean_name, departments, is_lead, unique_name
from reports import services as day_report  # "report" nomi /hisobot buyrug'i funksiyasida band

log = logging.getLogger("puls.bot")
router = Router()
REACTION = {"task": "✍", "done": "👍", "blocker": "👀", "deadline": "🫡", "reassign": "👌"}
PANEL_URL = dj.PANEL_URL

GUIDE = (
    "<b>Puls qanday ishlaydi</b>\n\n"
    "Guruhda odatdagidek yozing. Aniq bo'lishi uchun teg qo'ying:\n\n"
    "<code>#task #LoyihaNomi Login sahifasi @ali</code> — yangi vazifa\n"
    "<code>#done #LoyihaNomi Login sahifasi</code> — bajarildi\n"
    "<code>#muammo #LoyihaNomi Serverga ruxsat yo'q</code> — ishni to'xtatgan muammo\n"
    "<code>#deadline #LoyihaNomi 15.11.2026</code> — loyiha muddati\n\n"
    "Bir nechta vazifani har birini yangi qatorga yozing. Vazifa xabariga javob (reply) qilib "
    "<code>#done</code> desangiz, o'sha vazifa yopiladi, «25-oktyabrgacha» desangiz, muddat shu vazifaga yoziladi.\n\n"
    "Teg qo'yilmasa ham AI odamdek tushunadi: «Portal: login sahifasi tayyor bo'ldi», "
    "«Ulug'bek, slaydlar juma kuni tayyor bo'lsin», «buni Sardor qilsin».\n\n"
    "Ishi ko'p xodimga vazifa berilsa, shu bo'limdan bo'shroq hamkasbni tavsiya qilaman.\n\n"
    "Buyruqlar: /hisobot — bugungi xulosa, /bugun — bugun bajarilganlar Excel faylda, /loyihalar — loyihalar holati, /bolim — bo'limingiz, /panel — panel havolasi."
)


def _panel_kb() -> InlineKeyboardMarkup | None:
    if not PANEL_URL.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Panelni ochish", url=PANEL_URL)]])


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
    has_media = _media(m)[0] is not None
    if (not text and not has_media) or not m.from_user or m.from_user.is_bot or text.startswith("/"):
        return None
    user = m.from_user
    chat_title = m.chat.title or ("Shaxsiy: %s" % user.full_name)
    return Incoming(
        chat_id=m.chat.id, chat_title=chat_title, msg_id=m.message_id, user_id=user.id,
        user_name=user.full_name, username=user.username,
        date=m.date.astimezone(conf.TZ).replace(tzinfo=None),  # tahrirlansa ham asl yuborilgan vaqt
        text=text, reply_to=m.reply_to_message.message_id if m.reply_to_message else None, edited=edited,
    )


async def db(fn, *args):
    """Bazaviy amal alohida oqimda bajariladi; eskirgan ulanishlar yopiladi."""
    def run():
        close_old_connections()
        try:
            return fn(*args)
        finally:
            close_old_connections()
    return await asyncio.to_thread(run)


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


def _dm_of(user_id: int) -> int | None:
    return Person.objects.filter(telegram_id=user_id).values_list("dm_chat_id", flat=True).first()


async def _ask(m: Message, alert: dict, private: bool = False) -> None:
    """Savolni yuboradi: guruhda vazifa xabariga javob qilib yoki (sozlamaga ko'ra) vazifa berganga shaxsan."""
    dm = await db(_dm_of, m.from_user.id) if private else None
    try:
        if dm:
            sent = await m.bot.send_message(dm, alert["text"] + "\n\nGuruh: %s" % analytics._esc(m.chat.title or ""),
                                            reply_markup=_keyboard(alert["buttons"]))
        else:
            sent = await m.reply(alert["text"], reply_markup=_keyboard(alert["buttons"]))
        await db(load.sent, alert["id"], sent.chat.id, sent.message_id)
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
    if (await db(appsettings.load))["assign_policy"] == "rahbar":
        inc.lead = await db(is_lead, inc.user_id) or await _is_admin(m.bot, m.chat.id, inc.user_id)
    res = await db(process, inc)
    if res.duplicate:
        return
    emoji = "🤔" if res.missing_project else REACTION.get(res.kind)
    try:
        await m.bot.set_message_reaction(m.chat.id, m.message_id, [ReactionTypeEmoji(emoji=emoji)] if emoji else [])
    except Exception as e:  # reaksiya taqiqlangan guruh bo'lishi mumkin — ish to'xtamaydi
        log.debug("reaksiya qo'yilmadi: %s", e)
    if edited:
        return
    if res.missing_project and res.source == "format":
        await m.reply("Qaysi loyiha? Xabarga loyiha tegini qo'shing, masalan: <code>#task #Portal ...</code>")
    if res.proposed:
        for alert in await db(load.propose, res.proposed, inc.user_id, inc.user_name, m.chat.id, m.message_id):
            await _ask(m, alert)
    if res.task_ids:
        for alert in await db(load.check, res.task_ids, inc.user_id, m.chat.id, m.message_id):
            await _ask(m, alert, private=alert["mode"] == "shaxsan")


@router.callback_query(F.data.regexp(r"^(yk|tk):\d+:\w+$"))
async def alert_pick(q: CallbackQuery) -> None:
    """Botning savoliga javob: yuklama (kimga berish) yoki taklif (qabul / rad)."""
    _, aid, choice = q.data.split(":")
    alert = await db(load.get, int(aid))
    if alert is None:
        await q.answer("Bu savol eskirgan", show_alert=True)
        return
    admin = await _is_admin(q.bot, alert.chat_id, q.from_user.id)
    if not await db(load.may_decide, alert, q.from_user.id, q.from_user.username, admin):
        await q.answer("Buni vazifa bergan kishi yoki rahbar hal qiladi" if alert.kind == "yuklama"
                       else "Buni vazifa yozilgan xodim yoki rahbar hal qiladi", show_alert=True)
        return
    res = await db(load.resolve, int(aid), choice, q.from_user.full_name)
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
    """Shaxsiy havola orqali kelgan xodimni topib, chat id ni yozadi. Qayta bossa — yangilaydi."""
    person = Person.objects.filter(invite_token=token).first() if token else None
    if person is None:
        return None
    person.dm_chat_id, person.dm_linked_at = chat_id, conf.now()
    person.save(update_fields=["dm_chat_id", "dm_linked_at"])
    DataVersion.bump()
    return person.name


@router.message(CommandStart(deep_link=True), F.chat.type == ChatType.PRIVATE)
async def start_linked(m: Message, command: CommandObject) -> None:
    name = await db(_link_person, (command.args or "").strip(), m.chat.id)
    if name is None:
        await m.answer("Havola eskirgan. Rahbardan yangi havola so'rang.")
        return
    await m.answer("%s, siz Puls'ga ulandingiz.\n\nRahbarning shaxsiy eslatmalari endi shu yerga keladi. "
                   "Hisobotni odatdagidek ish guruhiga yozing." % analytics._esc(name.split()[0]))


@router.message(CommandStart())
async def start(m: Message) -> None:
    await m.answer("Assalomu alaykum! Men <b>Puls</b> — ish guruhidagi vazifa va hisobotlardan loyihalar holatini "
                   "hisoblab beraman.\n\nMeni ish guruhiga qo'shing va admin qiling.\n\n" + GUIDE,
                   reply_markup=_panel_kb())


@router.message(Command("yordam", "help"))
async def help_(m: Message) -> None:
    await m.answer(GUIDE)


@router.message(Command("panel"))
async def panel(m: Message) -> None:
    kb = _panel_kb()
    await m.answer("Panel: %s" % PANEL_URL if kb is None else "Panel shu yerda:", reply_markup=kb)


def _group_chat(m: Message) -> int | None:
    return m.chat.id if m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else None


@router.message(Command("hisobot"))
async def report(m: Message) -> None:
    text = await db(lambda: analytics.digest_text(chat_id=_group_chat(m)))
    await m.answer(text, reply_markup=_panel_kb())


@router.message(Command("bugun"))
async def today_done(m: Message) -> None:
    """Shu guruhda bugun bajarilgan vazifalar, Excel fayl bilan (kechki yuborishni kutmasdan)."""
    if m.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await m.answer("Bu buyruq ish guruhida ishlaydi.")
        return
    await _send_report(m.bot, m.chat.id, conf.now().date(), empty_note=True)


async def _send_report(bot: Bot, chat_id: int, day, empty_note: bool = False) -> None:
    built = await db(day_report.build, chat_id, day)
    if built is None:
        if empty_note:
            await bot.send_message(chat_id, "Bugun bu guruhda bajarilgan vazifa hali yo'q.")
        return
    data, name, caption = built
    await bot.send_document(chat_id, BufferedInputFile(data, filename=name), caption=caption)


@router.message(Command("loyihalar"))
async def projects(m: Message) -> None:
    data = await db(lambda: analytics.compute("week", chat_id=_group_chat(m)))
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
    if command.args:
        await db(_set_dept, m.from_user.id, m.from_user.full_name, m.from_user.username, command.args.strip())
        await m.answer("Bo'limingiz saqlandi: <b>%s</b>" % analytics._esc(command.args.strip()[:40]))
        return
    names = await db(departments)
    rows = [[InlineKeyboardButton(text=d, callback_data="bolim:" + d) for d in names[i:i + 3]] for i in range(0, len(names), 3)]
    await m.answer("Qaysi bo'limda ishlaysiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("bolim:"))
async def department_pick(q: CallbackQuery) -> None:
    dept = q.data.split(":", 1)[1]
    await db(_set_dept, q.from_user.id, q.from_user.full_name, q.from_user.username, dept)
    await q.answer("Saqlandi: " + dept)
    if q.message:
        await q.message.edit_text("%s — bo'lim: <b>%s</b>" % (analytics._esc(q.from_user.full_name), dept))


def _set_dept(uid: int, name: str, username: str | None, dept: str) -> None:
    department_obj = Department.objects.get_or_create(name=dept[:40])[0]
    person = Person.objects.filter(telegram_id=uid).first()
    if person is None:
        person = Person(telegram_id=uid, name=unique_name(clean_name(name), username=username), username=username)
    person.department = department_obj
    person.save()
    DataVersion.bump()


@router.my_chat_member()
async def added(event: ChatMemberUpdated) -> None:
    if event.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) and event.new_chat_member.status in ("member", "administrator") \
            and event.old_chat_member.status in ("left", "kicked"):
        await event.bot.send_message(event.chat.id, "Salom! Men shu guruhdagi vazifa va hisobotlarni hisoblab boraman.\n\n" + GUIDE)


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP, ChatType.PRIVATE}))
async def on_message(m: Message) -> None:
    await _handle(m)


@router.edited_message()
async def on_edit(m: Message) -> None:
    await _handle(m, edited=True)


def _plus(hhmm: str, minutes: int) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    total = min(23 * 60 + 59, h * 60 + m + minutes)
    return "%02d:%02d" % (total // 60, total % 60)


async def digest_loop(bot: Bot) -> None:
    """Har ish kuni ertalab va kechqurun (vaqti Sozlamalarda) rahbarga (DIGEST_CHAT_ID) brifing."""
    sent: set[str] = set()
    while True:
        await asyncio.sleep(30)
        now = conf.now()
        if now.weekday() >= 5 or not dj.DIGEST_CHAT_ID:
            continue
        S = await db(appsettings.load)
        for key, morning in (("digest_morning", True), ("digest_evening", False)):
            stamp = "%s %s" % (now.date(), key)
            if stamp in sent or now.strftime("%H:%M") < S[key] or now.strftime("%H:%M") > _plus(S[key], 20):
                continue
            sent.add(stamp)
            try:
                text = await db(lambda: analytics.digest_text(morning=morning))
                await bot.send_message(dj.DIGEST_CHAT_ID, text, reply_markup=_panel_kb())
            except Exception as e:  # noqa: BLE001
                log.warning("brifing yuborilmadi: %s", e)


async def group_report_loop(bot: Bot) -> None:
    """Har ish kuni belgilangan vaqtda har bir ish guruhiga o'sha guruhda bugun bajarilgan vazifalar (Excel)."""
    sent: set[str] = set()
    while True:
        await asyncio.sleep(30)
        now = conf.now()
        if now.weekday() >= 5:
            continue
        S = await db(appsettings.load)
        hhmm = now.strftime("%H:%M")
        stamp = str(now.date())
        if S["group_report"] == "off" or stamp in sent or hhmm < S["group_report_time"] or hhmm > _plus(S["group_report_time"], 20):
            continue
        sent.add(stamp)
        for chat_id in await db(day_report.chats):
            try:
                await _send_report(bot, chat_id, now.date())
            except Exception as e:  # noqa: BLE001 — bitta guruh xatosi boshqalarini to'xtatmaydi
                log.warning("guruh hisoboti yuborilmadi (%s): %s", chat_id, e)


async def demo_refresh() -> None:
    """Namuna guruhlar har kuni bugungi kunga nisbatan qayta yasaladi, bugungi xabarlari esa vaqti kelganda
    birma-bir tushadi (har daqiqada tekshiriladi). Haqiqiy guruhlar ma'lumotiga tegilmaydi."""
    from core import demo

    while True:
        try:
            if await db(demo.seeded_day) != conf.now().date().isoformat():
                stats = await db(lambda: demo.run(False, None, True))
                log.info("Namuna ma'lumot yangilandi: %d xabar, %d tasi navbatda", stats["messages"], stats["queued"])
            await db(demo.release)
        except Exception:  # noqa: BLE001 — namuna xatosi botni to'xtatmasin
            log.exception("namuna ma'lumot")
        await asyncio.sleep(60)


async def run_bot() -> None:
    bot = Bot(dj.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
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
    tasks = [asyncio.create_task(digest_loop(bot)), asyncio.create_task(group_report_loop(bot))]
    if dj.DEMO_DATA:
        tasks.append(asyncio.create_task(demo_refresh()))
    while True:
        try:
            await dp.start_polling(bot, allowed_updates=["message", "edited_message", "callback_query", "my_chat_member"],
                                   handle_signals=False)
            return
        except Exception as e:  # internet uzilsa — kutib qayta ulanadi
            log.warning("bot to'xtadi, 10 soniyadan keyin qayta ulanadi: %s", e)
            await asyncio.sleep(10)
