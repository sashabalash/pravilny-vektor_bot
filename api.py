"""HTTP-API для «быстрой записи» с сайта.

POST /lead   — принимает заявку из модалки сайта, создаёт её в bookings со статусом 'pending'
               и возвращает deep link https://t.me/<бот>?start=b_<token>.
GET  /health — проверка живости (для мониторинга / reverse-proxy).

Запускается из bot.py параллельно с polling (start_api).
"""
from __future__ import annotations

import hmac
import logging
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque

import aiohttp_cors
from aiohttp import web

from config import (ALLOWED_ORIGINS, API_HOST, API_PORT, API_TOKEN, BOT_USERNAME, FORMATS, GOALS,
                    SUBJECTS)
from database import db
from handlers.booking import LINK_FORMATS, LINK_GOALS, LINK_SUBJECTS
from utils import validate_name, validate_phone

log = logging.getLogger(__name__)

# --- настройки -------------------------------------------------------------
RATE_LIMIT = 10          # запросов
RATE_WINDOW = 60.0       # за столько секунд (с одного IP)
MAX_BODY = 16 * 1024     # максимальный размер тела запроса, байт
ALLOWED_ROLES = {"student", "parent"}

# --- rate limit (in-memory, один процесс) ----------------------------------
_hits: dict[str, deque] = defaultdict(deque)
_last_purge = 0.0


def _rate_limited(ip: str) -> bool:
    """True, если с этого IP превышен лимит. Считается каждый запрос."""
    global _last_purge
    now = time.monotonic()

    if now - _last_purge > 300:
        _last_purge = now
        for key in [k for k, q in _hits.items() if not q or now - q[-1] > RATE_WINDOW]:
            _hits.pop(key, None)

    q = _hits[ip]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


def _client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.remote or "unknown"


# --- валидация -------------------------------------------------------------
_CTRL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value, max_len: int) -> str:
    if not isinstance(value, str):
        return ""
    value = _CTRL_CHARS.sub(" ", value)
    return " ".join(value.split())[:max_len]


def _resolve(value, link_map: dict, labels: dict) -> str | None:
    """Код с сайта ('grp') или ключ бота ('group') → ключ справочника config.py; иначе None."""
    code = _clean(value, 30).lower()
    key = link_map.get(code, code)
    return key if key in labels else None


def _error(status: int, code: str, headers: dict | None = None) -> web.Response:
    return web.json_response({"error": code}, status=status, headers=headers)


# --- извлечение токена из запроса ------------------------------------------
def _extract_token(request: web.Request) -> str:
    """Токен может прийти в X-Api-Token или в Authorization: Bearer <token>."""
    supplied = request.headers.get("X-Api-Token", "").strip()
    if supplied:
        return supplied
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


# --- обработчики -----------------------------------------------------------
async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def lead(request: web.Request) -> web.Response:
    if _rate_limited(_client_ip(request)):
        return _error(429, "too_many_requests", headers={"Retry-After": "60"})

    supplied = _extract_token(request)
    origin = (request.headers.get("Origin", "") or "").rstrip("/")

    # Вариант B: если токен передан — проверяем его.
    # Если токена нет, но Origin в списке разрешённых (CORS уже пропустил) — пускаем.
    if supplied:
        if not hmac.compare_digest(supplied.encode("utf-8"), API_TOKEN.encode("utf-8")):
            return _error(401, "unauthorized")
    else:
        if origin not in ALLOWED_ORIGINS:
            return _error(401, "unauthorized")

    try:
        payload = await request.json()
    except Exception:
        return _error(422, "invalid_json")
    if not isinstance(payload, dict):
        return _error(422, "invalid_json")

    fields: dict[str, str] = {}

    name = validate_name(_clean(payload.get("name"), 100))
    if not name:
        fields["name"] = "invalid"

    phone = validate_phone(_clean(payload.get("phone"), 30))
    if not phone:
        fields["phone"] = "invalid"

    format_key = _resolve(payload.get("format"), LINK_FORMATS, FORMATS)
    if format_key is None:
        fields["format"] = "invalid"

    goal_key = _resolve(payload.get("goal"), LINK_GOALS, GOALS)
    if goal_key is None:
        fields["goal"] = "invalid"

    subject_key = None
    if payload.get("subject") not in (None, ""):
        subject_key = _resolve(payload.get("subject"), LINK_SUBJECTS, SUBJECTS)
        if subject_key is None:
            fields["subject"] = "invalid"

    role = _clean(payload.get("role"), 20).lower() or "student"
    if role not in ALLOWED_ROLES:
        fields["role"] = "invalid"

    if fields:
        return web.json_response({"error": "validation", "fields": fields}, status=422)

    booking_id = None
    token = ""
    try:
        for _ in range(3):
            token = secrets.token_urlsafe(9)
            try:
                booking_id = await db.add_site_booking(
                    token, name, phone, FORMATS[format_key], GOALS[goal_key], role,
                    subject=SUBJECTS[subject_key] if subject_key else None)
                break
            except sqlite3.IntegrityError:
                continue
    except Exception:
        log.exception("POST /lead: ошибка записи в БД")
        return _error(500, "server_error")

    if booking_id is None:
        log.error("POST /lead: не удалось сгенерировать уникальный токен")
        return _error(500, "server_error")

    url = f"https://t.me/{BOT_USERNAME}?start=b_{token}"
    return web.json_response({"booking_id": booking_id, "url": url}, status=201)


# --- приложение ------------------------------------------------------------
def create_app() -> web.Application:
    app = web.Application(client_max_size=MAX_BODY)
    app.router.add_get("/health", health)

    if ALLOWED_ORIGINS:
        cors = aiohttp_cors.setup(
            app,
            defaults={
                origin: aiohttp_cors.ResourceOptions(
                    allow_credentials=False,
                    expose_headers=(),
                    allow_headers=("Content-Type", "X-Api-Token", "Authorization"),
                    allow_methods=("POST", "OPTIONS"),
                    max_age=3600,
                )
                for origin in ALLOWED_ORIGINS
            },
        )
        resource = cors.add(app.router.add_resource("/lead"))
        cors.add(resource.add_route("POST", lead))
    else:
        log.warning("ALLOWED_ORIGINS пуст: CORS выключен")
        app.router.add_post("/lead", lead)

    return app


async def start_api() -> web.AppRunner | None:
    if len(API_TOKEN) < 32:
        log.error("API_TOKEN пуст или короче 32 символов — HTTP-API не запущен")
        return None
    if not BOT_USERNAME:
        log.error("BOT_USERNAME не задан — HTTP-API не запущен")
        return None

    runner = web.AppRunner(create_app(), access_log=None)
    try:
        await runner.setup()
        await web.TCPSite(runner, API_HOST, API_PORT).start()
    except OSError:
        log.exception("Не удалось занять %s:%s — HTTP-API не запущен", API_HOST, API_PORT)
        await runner.cleanup()
        return None
    log.info("HTTP API слушает %s:%s", API_HOST, API_PORT)
    return runner