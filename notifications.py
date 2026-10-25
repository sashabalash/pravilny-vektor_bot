"""
Отправка уведомлений: безопасная отправка сообщений, рассылка администраторам,
уведомление ученика и его родителей.
"""
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

from config import ADMIN_IDS
from database import db

logger = logging.getLogger(__name__)


async def safe_send(bot: Bot, chat_id: int, text: str,
                    reply_markup: InlineKeyboardMarkup | None = None) -> bool:
    """Отправляет сообщение и не падает, если пользователь заблокировал бота."""
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return True
    except TelegramForbiddenError:
        logger.warning("Пользователь %s заблокировал бота или недоступен", chat_id)
    except TelegramAPIError as exc:
        logger.error("Не удалось отправить сообщение %s: %s", chat_id, exc)
    return False


async def notify_admins(bot: Bot, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Отправляет сообщение всем администраторам."""
    for admin_id in ADMIN_IDS:
        await safe_send(bot, admin_id, text, reply_markup)


async def notify_family(bot: Bot, student: dict, text: str, parent_text: str | None = None,
                        reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Уведомляет ученика и всех привязанных к нему родителей."""
    await safe_send(bot, student["telegram_id"], text, reply_markup)
    for parent in await db.get_parents_of_student(student):
        await safe_send(bot, parent["telegram_id"], parent_text or text)
