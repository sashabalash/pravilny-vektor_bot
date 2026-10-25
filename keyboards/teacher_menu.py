"""Клавиатуры панели преподавателя."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def teacher_main_kb() -> InlineKeyboardMarkup:
    """Главное меню преподавателя."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Мои ученики", callback_data="tch:students")],
            [InlineKeyboardButton(text="📅 Расписание", callback_data="tch:schedule")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )
