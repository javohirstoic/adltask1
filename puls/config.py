"""Sozlamalar. Hammasi .env faylidan o'qiladi, kod ichida maxfiy kalit yo'q."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env(name: str) -> None:
    path = ROOT / name
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_env(".env")
_load_env(".env.bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

DB_PATH = ROOT / os.getenv("DB_PATH", "data/puls.db")

# AI: "gemini" yoki "off". off bo'lsa faqat format va kalit so'zlar ishlaydi.
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()
GEMINI_SA = os.getenv("GEMINI_SA", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_FALLBACK = os.getenv("GEMINI_FALLBACK", "gemini-2.5-flash")  # asosiy model band bo'lsa
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")  # AI Studio kaliti: bo'lsa asosiy model shu orqali, zaxira Vertex

# Kunlik xulosa: qaysi chatga va soat nechada
DIGEST_CHAT_ID = int(os.getenv("DIGEST_CHAT_ID", "0") or 0) or OWNER_ID
DIGEST_TIME = os.getenv("DIGEST_TIME", "19:00")

WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8700"))
PANEL_URL = os.getenv("PANEL_URL", "http://127.0.0.1:%d/" % WEB_PORT)
# Panelga kirish kodi. Bo'sh bo'lsa panel kodsiz ochiladi (faqat o'z kompyuteringizda shunday qiling).
PANEL_PIN = os.getenv("PANEL_PIN", "")
PANEL_SECRET = os.getenv("PANEL_SECRET", "puls-local")
# Bot faqat bitta joyda ishlashi kerak (Telegram ikki joydan bir vaqtda o'qishga ruxsat bermaydi)
BOT_ENABLED = os.getenv("BOT_ENABLED", "1") == "1"
# Namuna (demo) guruhlarni har kuni bugungi sanaga yangilash — taqdimot va sinov uchun
DEMO_DATA = os.getenv("DEMO_DATA", "0") == "1"

# O'zbekistonda yozgi vaqt yo'q, shuning uchun doimiy +05:00
TZ = timezone(timedelta(hours=5), "Asia/Tashkent")


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def ai_enabled() -> bool:
    return AI_PROVIDER == "gemini" and bool(GEMINI_SA) and Path(GEMINI_SA).exists()
