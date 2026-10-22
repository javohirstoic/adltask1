"""Telegram Bot API'ga to'g'ridan-to'g'ri so'rov: veb jarayon botning o'z jarayonisiz ham xabar yubora oladi."""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger("puls.telegram")


def send_message(chat_id: int, text: str) -> tuple[bool, str]:
    if not settings.BOT_TOKEN:
        return False, "Bot sozlanmagan"
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % settings.BOT_TOKEN,
        json.dumps({"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}).encode(),
        {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True, "Guruhga yuborildi"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.warning("guruhga yuborilmadi: %s", e)
        return False, "Telegramga yuborilmadi"
