"""Puls'ni ishga tushirish: veb panel va Telegram bot bitta jarayonda.

    python run.py           # panel + bot
    python run.py --open    # brauzerda panelni ham ochadi
"""
import asyncio
import logging
import sys
import webbrowser

import uvicorn

from puls import config, db
from puls.web import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
for noisy in ("aiogram.event", "httpx", "uvicorn.access"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


async def demo_refresh() -> None:
    """Namuna guruhlar har kuni bugungi kunga nisbatan qayta yasaladi, bugungi xabarlari esa vaqti kelganda
    birma-bir tushadi (har daqiqada tekshiriladi). Haqiqiy guruhlar ma'lumotiga tegilmaydi."""
    from puls import seed

    while True:
        try:
            if seed.seeded_day() != config.now().date().isoformat():
                stats = await asyncio.to_thread(seed.run, False, None, True)
                logging.info("Namuna ma'lumot yangilandi: %d xabar, %d tasi navbatda", stats["messages"], stats["queued"])
            await asyncio.to_thread(seed.release)
        except Exception:  # noqa: BLE001 — namuna xatosi panel va botni to'xtatmasin
            logging.exception("namuna ma'lumot")
        await asyncio.sleep(60)


async def main() -> None:
    db.init()
    server = uvicorn.Server(uvicorn.Config(app, host=config.WEB_HOST, port=config.WEB_PORT, log_level="warning",
                                           proxy_headers=True, forwarded_allow_ips="*", access_log=False))
    jobs = [server.serve()]
    if config.DEMO_DATA:
        jobs.append(demo_refresh())
    if config.BOT_TOKEN and config.BOT_ENABLED:
        from puls.bot import run_bot
        jobs.append(run_bot())
        logging.info("Bot: @%s", config.BOT_USERNAME)
    logging.info("Panel: http://%s:%d/  (AI: %s)", config.WEB_HOST, config.WEB_PORT, "yoqilgan" if config.ai_enabled() else "o'chiq")
    if "--open" in sys.argv:
        asyncio.get_running_loop().call_later(1.5, webbrowser.open, "http://127.0.0.1:%d/" % config.WEB_PORT)
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
