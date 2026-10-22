import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from telegram.bot import run_bot


class Command(BaseCommand):
    help = "Telegram botni ishga tushiradi (brifinglar va, DEMO_DATA=1 bo'lsa, namuna ma'lumot yangilanishi bilan birga)"

    def handle(self, *args, **options):
        if not settings.BOT_TOKEN:
            raise CommandError("BOT_TOKEN .env da yo'q")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
        for noisy in ("aiogram.event", "httpx"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        self.stdout.write("Bot: @%s" % settings.BOT_USERNAME)
        try:
            asyncio.run(run_bot())
        except KeyboardInterrupt:
            pass
