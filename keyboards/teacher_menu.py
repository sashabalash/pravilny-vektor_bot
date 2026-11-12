"""Клавиатуры панели преподавателя (callback_data с префиксом «tch:» обрабатывает handlers/teacher.py)."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.admin_menu import student_button_label
from utils import fmt_dt


def _short(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def teacher_main_kb() -> InlineKeyboardMarkup:
    """Главное меню преподавателя."""
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Мои ученики", callback_data="tch:students")
    builder.button(text="📈 Моя статистика", callback_data="tch:stats")
    builder.button(text="👤 Статистика по ученику", callback_data="tch:pick")
    builder.button(text="📅 Мои занятия", callback_data="tch:lessons")
    builder.button(text="🏠 Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def teacher_back_kb() -> InlineKeyboardMarkup:
    """Возврат в панель преподавателя."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В панель преподавателя", callback_data="tch:main")
    return builder.as_markup()


def teacher_student_back_kb() -> InlineKeyboardMarkup:
    """Под карточкой ученика: к списку учеников или в панель."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К списку учеников", callback_data="tch:pick")
    builder.button(text="🏠 В панель преподавателя", callback_data="tch:main")
    builder.adjust(1)
    return builder.as_markup()


def teacher_pick_kb(students: list[dict]) -> InlineKeyboardMarkup:
    """Выбор ученика плиткой по 3 в ряд; callback_data = 'tch:ss:<id ученика>'."""
    builder = InlineKeyboardBuilder()
    for student in students[:60]:
        builder.button(text=f"🎓 {student_button_label(student)}", callback_data=f"tch:ss:{student['id']}")
    builder.adjust(3)
    builder.row(*teacher_back_kb().inline_keyboard[0])
    return builder.as_markup()


def teacher_lessons_kb(lessons: list[dict]) -> InlineKeyboardMarkup:
    """Ближайшие занятия преподавателя; callback_data = 'tch:les:<id занятия>'."""
    builder = InlineKeyboardBuilder()
    for lesson in lessons:
        builder.button(text=f"{fmt_dt(lesson['lesson_dt'])} · {_short(lesson['student_name'], 20)}",
                       callback_data=f"tch:les:{lesson['id']}")
    builder.adjust(1)
    builder.row(*teacher_back_kb().inline_keyboard[0])
    return builder.as_markup()


def teacher_lesson_status_kb(lesson_id: int) -> InlineKeyboardMarkup:
    """Отметка результата занятия."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Проведено", callback_data=f"tch:lstat:{lesson_id}:done")
    builder.button(text="❌ Пропущено", callback_data=f"tch:lstat:{lesson_id}:missed")
    builder.button(text="🚫 Отменено", callback_data=f"tch:lstat:{lesson_id}:cancelled")
    builder.button(text="⬅️ К занятиям", callback_data="tch:lessons")
    builder.adjust(3, 1)
    return builder.as_markup()
