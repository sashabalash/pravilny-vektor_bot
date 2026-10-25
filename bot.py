"""
Точка входа Telegram-бота школы «Правильный Вектор».
Подключает БД, регистрирует роутеры и middleware, запускает планировщик и polling.
"""
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from api import start_api
from config import ADMIN_IDS, BOT_TOKEN, DB_PATH, LOG_FILE
from database import db
from handlers import (admin, booking, faq, homework, materials, payment, registration, reports,
                      schedule, start)
from middlewares.auth import AuthMiddleware
from scheduler.reminders import setup_scheduler
from schema_migration import migrate_bookings

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Логирование в файл bot.log (с ротацией) и в консоль."""
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def on_error(event: ErrorEvent) -> bool:
    """Глобальный обработчик ошибок: пишет трассировку в лог и сообщает пользователю."""
    logger.error("Необработанная ошибка: %s", event.exception, exc_info=event.exception)
    update = event.update
    try:
        if update.message:
            await update.message.answer("⚠️ Что-то пошло не так. Попробуйте ещё раз или откройте /menu")
        elif update.callback_query:
            await update.callback_query.answer("⚠️ Произошла ошибка. Попробуйте ещё раз.", show_alert=True)
    except Exception:
        logger.exception("Не удалось сообщить пользователю об ошибке")
    return True


async def main() -> None:
    setup_logging()

    if not BOT_TOKEN:
        logger.critical("Не задан BOT_TOKEN. Скопируйте .env.example в .env и заполните токен.")
        raise SystemExit(1)
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS пуст: админ-панель будет недоступна. Укажите ID в файле .env")

    # Быстрая запись: добавляет bookings.source / bookings.token, если их ещё нет (идемпотентно, до db.connect())
    for step in migrate_bookings(DB_PATH):
        logger.info("Миграция bookings: %s", step)

    await db.connect()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher(storage=MemoryStorage())

    auth = AuthMiddleware()
    dp.message.outer_middleware(auth)
    dp.callback_query.outer_middleware(auth)
    dp.errors.register(on_error)

    # Порядок важен: сначала команды и сценарии с состояниями, в конце — запасной обработчик
    dp.include_routers(
        start.router,
        registration.router,
        booking.router,
        schedule.router,
        payment.router,
        reports.router,
        faq.router,
        materials.router,
        homework.router,
        admin.router,
        start.fallback_router,
    )

    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="schedule", description="Расписание занятий"),
        BotCommand(command="balance", description="Баланс занятий и оплата"),
        BotCommand(command="report", description="Отчёт по ученику"),
        BotCommand(command="book", description="Записаться на пробный урок"),
        BotCommand(command="cancel", description="Отменить действие"),
    ])

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Бот запущен")

    api_runner = None
    try:
        api_runner = await start_api()  # HTTP-эндпоинт POST /lead для сайта, в том же event loop
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if api_runner is not None:
            await api_runner.cleanup()
        scheduler.shutdown(wait=False)
        await db.close()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
