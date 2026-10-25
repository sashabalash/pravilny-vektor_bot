"""
Вспомогательные функции: экранирование HTML, валидация ввода,
работа с датами и безопасное редактирование сообщений.
"""
import html
import re
from datetime import date, datetime, time as dtime

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from config import TIMEZONE

DB_DT_FORMAT = "%Y-%m-%d %H:%M"
DB_TS_FORMAT = "%Y-%m-%d %H:%M:%S"
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\s\-']{1,59}$")
_GRADE_RE = re.compile(r"^(?:[1-9]|10|11)\s?[А-Яа-яA-Za-z]?$")
_PHONE_CHARS_RE = re.compile(r"^[\d\s()+\-]+$")


def esc(value) -> str:
    """Экранирует текст для безопасной вставки в HTML-сообщение."""
    return html.escape("" if value is None else str(value))


def short(text, limit: int = 40) -> str:
    """Обрезает текст до limit символов (в одну строку)."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def now_local() -> datetime:
    """Текущее время в часовом поясе школы."""
    return datetime.now(TIMEZONE)


def now_ts() -> str:
    """Метка времени для записи в БД."""
    return now_local().strftime(DB_TS_FORMAT)


def normalize_name(name) -> str:
    """Приводит имя к виду для сравнения (регистр, ё/е, пробелы)."""
    return " ".join(str(name or "").casefold().replace("ё", "е").split())


# ---------- Валидация ----------

def validate_name(raw: str) -> str | None:
    """Имя не пустое, только буквы, пробелы, дефис и апостроф (2–60 символов)."""
    value = " ".join((raw or "").split())
    return value if _NAME_RE.match(value) else None


def validate_phone(raw: str) -> str | None:
    """Белорусский номер: +375XXXXXXXXX. Принимает также 80XXXXXXXXX и 375XXXXXXXXX."""
    raw = (raw or "").strip()
    if not _PHONE_CHARS_RE.match(raw):
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("375") and len(digits) == 12:
        return "+" + digits
    if digits.startswith("80") and len(digits) == 11:
        return "+375" + digits[2:]
    return None


def validate_grade(raw: str) -> str | None:
    """Класс: число 1–11 с необязательной буквой, например 9 или 11А."""
    value = (raw or "").strip()
    return value.replace(" ", "").upper() if _GRADE_RE.match(value) else None


def validate_int(raw: str, min_value: int, max_value: int) -> int | None:
    """Целое число в заданных пределах."""
    value = (raw or "").strip()
    if not value.isdigit():
        return None
    number = int(value)
    return number if min_value <= number <= max_value else None


def validate_amount(raw: str) -> float | None:
    """Сумма оплаты (допускается запятая как разделитель)."""
    try:
        value = float((raw or "").strip().replace(",", "."))
    except ValueError:
        return None
    return round(value, 2) if 0 <= value <= 100000 else None


def validate_url(raw: str) -> str | None:
    """Простая проверка ссылки (http/https)."""
    value = (raw or "").strip()
    if re.match(r"^https?://\S+\.\S+$", value) and len(value) <= 300:
        return value
    return None


# ---------- Даты ----------

def parse_date(raw: str) -> date | None:
    """Разбирает дату ДД.ММ.ГГГГ."""
    value = (raw or "").strip().replace("/", ".").replace("-", ".")
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_time(raw: str) -> dtime | None:
    """Разбирает время ЧЧ:ММ."""
    value = (raw or "").strip().replace(".", ":")
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def fmt_dt(db_value: str) -> str:
    """'2026-10-20 18:00' -> 'Вт, 20.10.2026 в 18:00'."""
    moment = datetime.strptime(db_value, DB_DT_FORMAT)
    return f"{WEEKDAYS[moment.weekday()]}, {moment:%d.%m.%Y} в {moment:%H:%M}"


def fmt_date(iso_value: str | None) -> str:
    """'2026-10-20' -> '20.10.2026'."""
    if not iso_value:
        return "—"
    return date.fromisoformat(iso_value).strftime("%d.%m.%Y")


# ---------- Telegram ----------

async def safe_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Редактирует сообщение, а если нельзя — отправляет новое."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        await message.answer(text, reply_markup=reply_markup)
