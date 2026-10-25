"""
Конфигурация бота «Правильный Вектор».
Читает настройки из .env и хранит общие константы (справочники, статусы, ссылки).
"""
import logging
import os
from pathlib import Path

import pytz
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)


def _parse_admin_ids(raw: str) -> set[int]:
    """Превращает строку вида "123,456" в множество Telegram ID."""
    result: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            result.add(int(part))
        else:
            logger.warning("Некорректный ID администратора в .env: %r", part)
    return result


# --- Настройки из .env ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "pravilny_vektor.db"))
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Europe/Minsk"))
PAYMENT_URL = os.getenv("PAYMENT_URL", "https://pravilny-vektor.by")
# Сообщения об оплате ученикам и родителям (напоминание за 3 дня и «оплата получена»).
# По умолчанию выключены. Сами платежи при этом всё равно записываются и попадают в статистику.
NOTIFY_PAYMENTS = os.getenv("NOTIFY_PAYMENTS", "false").strip().lower() in ("1", "true", "yes", "on")
LOG_FILE = BASE_DIR / "bot.log"

# --- Ссылки школы ---
SITE_URL = "https://pravilny-vektor.by"
TEACHER_URL = "https://t.me/Alexander_Balash"
CHANNEL_URL = "https://t.me/pravilniy_vektor"

# --- Правила работы ---
PAYMENT_REMIND_DAYS = 3        # за сколько дней напоминать об окончании пакета
DEFAULT_PACKAGE_DAYS = 30      # срок действия пакета по умолчанию (подсказка админу)

# --- Справочники ---
SUBJECTS = {"math": "Математика", "english": "Английский", "other": "Другой"}
FORMATS = {"ind": "Индивидуально", "group": "Мини-группа"}
GOALS = {
    "base": "Подтянуть базу",
    "ct": "Подготовка к ЦТ",
    "hard": "Разбор сложных тем",
}

# --- Статусы домашних заданий ---
HW_STATUS_LABELS = {
    None: "🆕 Не сдано",
    "pending": "⏳ На проверке",
    "accepted": "✅ Принято",
    "rework": "🔁 На доработку",
    "excellent": "🌟 Отлично",
}
# Баллы (10-балльная шкала) для среднего балла в отчётах.
# «На доработку» балла не получает — оценка появится после пересдачи.
HW_SCORES = {"accepted": 8, "excellent": 10, "rework": None}


def is_admin(user_id: int) -> bool:
    """Проверяет, что Telegram ID входит в список администраторов."""
    return user_id in ADMIN_IDS


# Username бота БЕЗ @ — нужен для ссылки https://t.me/<BOT_USERNAME>?start=b_<token>
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "").strip().lstrip("@")

# Секрет для заголовка X-Api-Token (>= 32 символов)
API_TOKEN: str = os.getenv("API_TOKEN", "").strip()

# HTTP-API слушает только локальный интерфейс; наружу его отдаёт Caddy/nginx
API_HOST: str = os.getenv("API_HOST", "127.0.0.1").strip()
API_PORT: int = int(os.getenv("API_PORT", "8080"))

# --- CORS для сайта ---
# Список origin'ов, с которых разрешены запросы к /lead.
# В .env можно перечислить несколько через запятую:
#   SITE_ORIGIN=http://localhost:3000,http://127.0.0.1:3000,https://pravilnyvector.netlify.app
# ВАЖНО: origin пишется БЕЗ завершающего "/" и БЕЗ пути.
_DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://pravilnyvector.netlify.app",
]

_raw_origins = os.getenv("SITE_ORIGIN", "")
_parsed_origins = [
    o.strip().rstrip("/")
    for o in _raw_origins.replace(";", ",").split(",")
    if o.strip()
]

ALLOWED_ORIGINS: list[str] = _parsed_origins or _DEFAULT_ORIGINS