import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change_me_random_string").strip()
PORT = int(os.getenv("PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
MAX_PLAYLIST_TRACKS = int(os.getenv("MAX_PLAYLIST_TRACKS", "20"))

ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]

# ==== Подписка / триал ====
# FREE_MODE=True — все считаются оплаченными (для тестов)
FREE_MODE = os.getenv("FREE_MODE", "false").lower() in ("1", "true", "yes", "on")

# ==== Лимиты скачиваний ====
# free — сколько треков в день без подписки, paid — с подпиской (-1 = без лимита)
DEFAULT_DOWNLOAD_LIMITS = {
    "free": 3,
    "paid": -1,
}

# ==== Тарифы по умолчанию (Telegram Stars) ====
DEFAULT_PRICING = {
    "7":  {"days": 7,  "stars": 99},
    "30": {"days": 30, "stars": 299},
    "90": {"days": 90, "stars": 699},
}

# ==== Триал по умолчанию ====
DEFAULT_TRIAL = {
    "enabled": True,
    "days": 3,
}

# ==== Реклама по умолчанию ====
DEFAULT_ADS_CONFIG = {
    "enabled": False,
    "frequency": "daily",        # always | daily | every_n
    "frequency_value": 5,        # для every_n
    "max_per_day": 3,
    "show_to_admins": False,
}

# ==== Бэкап / автодействия ====
CACHE_CLEANUP_ENABLED_DEFAULT = True
CACHE_TTL_DAYS = {
    "temporary": 7,
    "permanent": 90,
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set in .env")