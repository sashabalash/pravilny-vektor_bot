"""Общие тексты и функции для handlers (чтобы не было циклических импортов)."""
import logging

from aiogram.types import Message

from database import db
from keyboards.main_menu import main_menu_kb
from utils import esc, fmt_balance, fmt_date, fmt_dt, now_local, safe_edit

logger = logging.getLogger(__name__)

WELCOME_NEW = (
    "👋 <b>Добро пожаловать в онлайн-школу «Правильный Вектор»!</b>\n\n"
    "Мы готовим к ЦТ и ЦЭ по математике. Ответьте на несколько вопросов, "
    "чтобы записаться на пробный урок 👇"
)


async def main_menu_text(db_user: dict) -> str:
    """Главное меню со сводкой: баланс занятий и ближайший урок (если он есть)."""
    lines = ["🏠 <b>Главное меню</b>", f"Здравствуйте, {esc(db_user['full_name'])}!"]
    try:
        student = await db.resolve_student(db_user)
        if student:
            lines.append("")
            whose = " ребёнка" if db_user["role"] == "parent" else ""
            balance = f"📦 Баланс{whose}: <b>{fmt_balance(student['balance'])}</b>"
            if student["package_end"]:
                balance += f" · пакет до {fmt_date(student['package_end'])}"
            lines.append(balance)
            moment = now_local().strftime("%Y-%m-%d %H:%M")
            lesson = await db.fetchone(
                "SELECT lesson_dt FROM lessons WHERE student_id = ? AND status = 'scheduled' "
                "AND lesson_dt >= ? ORDER BY lesson_dt LIMIT 1", (student["id"], moment))
            if lesson:
                lines.append(f"🕒 Ближайшее занятие: {fmt_dt(lesson['lesson_dt'])}")
    except Exception:  # сводка не должна ломать меню
        logger.exception("Не удалось собрать сводку для главного меню")
    lines.append("")
    lines.append("Что хотите сделать?")
    return "\n".join(lines)


async def show_main_menu(target: Message, db_user: dict, is_admin: bool, text: str | None = None,
                         edit: bool = False) -> None:
    """Показывает главное меню пользователя (отправляет или редактирует сообщение)."""
    if text is None:
        text = await main_menu_text(db_user)
    markup = main_menu_kb(db_user["role"], is_admin)
    if edit:
        await safe_edit(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)

