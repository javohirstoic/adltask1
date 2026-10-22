"""Umumiy yordamchilar: Toshkent vaqti va AI yoqilganligi."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings

# O'zbekistonda yozgi vaqt yo'q, shuning uchun doimiy +05:00
TZ = timezone(timedelta(hours=5), "Asia/Tashkent")
FMT = "%Y-%m-%d %H:%M:%S"


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def ai_enabled() -> bool:
    return settings.AI_PROVIDER == "gemini" and bool(settings.GEMINI_SA) and Path(settings.GEMINI_SA).exists()
