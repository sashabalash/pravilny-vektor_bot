"""Общие тексты и функции для handlers (чтобы не было циклических импортов)."""
from aiogram.types import Message

from keyboards.main_menu import main_menu_kb
from utils import esc, safe_edit

WELCOME_NEW = (
    "👋 <b>Добро пожаловать в онлайн-школу «Правильный Вектор»!</b>\n\n"
    "Мы готовим к ЦТ и ЦЭ по математике. Ответьте на несколько вопросов, "
    "чтобы записаться на пробный урок 👇"
)


async def show_main_menu(target: Message, db_user: dict, is_admin: bool, text: str | None = None,
                         edit: bool = False) -> None:
    """Показывает главное меню пользователя (отправляет или редактирует сообщение)."""
    if text is None:
        text = f"🏠 <b>Главное меню</b>\nЗдравствуйте, {esc(db_user['full_name'])}! Что хотите сделать?"
    markup = main_menu_kb(db_user["role"], is_admin)
    if edit:
        await safe_edit(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)

