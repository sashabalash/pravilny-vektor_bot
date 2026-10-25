"""
Клавиатуры админ-панели (только Inline).
"""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils import fmt_dt, short


def admin_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Ученики", callback_data="adm:students")
    builder.button(text="👨‍🏫 Преподаватели", callback_data="adm:teachers")
    builder.button(text="📅 Расписание", callback_data="adm:schedule")
    builder.button(text="📚 Домашние задания", callback_data="adm:hw")
    builder.button(text="📊 Статистика", callback_data="adm:stats")
    builder.button(text="💳 Оплата", callback_data="adm:pay")
    builder.button(text="📝 Заявки", callback_data="adm:bk")
    builder.button(text="📢 Рассылка", callback_data="adm:bc")
    builder.button(text="❓ FAQ", callback_data="adm:faq")
    builder.button(text="📎 Материалы", callback_data="adm:mat")
    builder.button(text="🏠 Главное меню", callback_data="menu:main")
    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup()

def back_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    return builder.as_markup()


def cancel_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✖️ Отмена", callback_data="adm:main")
    return builder.as_markup()


def students_list_kb(users: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in users:
        icon = "🎓" if user["role"] == "student" else "👪"
        blocked = " 🚫" if user["is_blocked"] else ""
        builder.button(text=f"{icon} {short(user['full_name'], 35)}{blocked}", callback_data=f"adm:u:{user['id']}")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def user_card_kb(user: dict) -> InlineKeyboardMarkup:
    uid = user["id"]
    builder = InlineKeyboardBuilder()
    if user["role"] == "student":
        builder.button(text="➕ Занятие", callback_data=f"adm:ulesson:{uid}")
        builder.button(text="📚 Выдать ДЗ", callback_data=f"adm:uhw:{uid}")
        builder.button(text="💳 Принять оплату", callback_data=f"adm:upay:{uid}")
        builder.button(text="💬 Комментарий к отчёту", callback_data=f"adm:ucomment:{uid}")
        builder.button(text="👨‍🏫 Преподаватель", callback_data=f"adm:uteacher:{uid}")
    builder.button(text="✏️ Изменить данные", callback_data=f"adm:uedit:{uid}")
    block_text = "✅ Разблокировать" if user["is_blocked"] else "🚫 Заблокировать"
    builder.button(text=block_text, callback_data=f"adm:ublock:{uid}")
    builder.button(text="🗑 Удалить", callback_data=f"adm:udel:{uid}")
    builder.button(text="⬅️ К списку", callback_data="adm:students")
    builder.adjust(2, 2, 2, 1, 1, 1)
    return builder.as_markup()


def edit_fields_kb(user: dict) -> InlineKeyboardMarkup:
    uid = user["id"]
    builder = InlineKeyboardBuilder()
    builder.button(text="Имя", callback_data=f"adm:ef:{uid}:full_name")
    builder.button(text="Телефон", callback_data=f"adm:ef:{uid}:phone")
    if user["role"] == "student":
        builder.button(text="Класс", callback_data=f"adm:ef:{uid}:grade")
        builder.button(text="Предмет", callback_data=f"adm:ef:{uid}:subject")
    else:
        builder.button(text="Имя ребёнка", callback_data=f"adm:ef:{uid}:child_name")
    builder.button(text="⬅️ Назад", callback_data=f"adm:u:{uid}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def confirm_delete_kb(uid: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Да, удалить", callback_data=f"adm:udelok:{uid}")
    builder.button(text="⬅️ Отмена", callback_data=f"adm:u:{uid}")
    builder.adjust(1)
    return builder.as_markup()


def pick_student_kb(students: list[dict], prefix: str) -> InlineKeyboardMarkup:
    """Выбор ученика; callback_data = '<prefix>:<id>'."""
    builder = InlineKeyboardBuilder()
    for student in students:
        builder.button(text=f"🎓 {short(student['full_name'], 35)}", callback_data=f"{prefix}:{student['id']}")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def schedule_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить занятие", callback_data="adm:pick:lesson")
    builder.button(text="📋 Ближайшие занятия", callback_data="adm:lessons")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def lessons_list_kb(lessons: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for lesson in lessons:
        builder.button(
            text=f"{fmt_dt(lesson['lesson_dt'])} · {short(lesson['student_name'], 20)}",
            callback_data=f"adm:les:{lesson['id']}",
        )
    builder.button(text="⬅️ Назад", callback_data="adm:schedule")
    builder.adjust(1)
    return builder.as_markup()


def lesson_status_kb(lesson_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Проведено", callback_data=f"adm:lstat:{lesson_id}:done")
    builder.button(text="❌ Пропущено", callback_data=f"adm:lstat:{lesson_id}:missed")
    builder.button(text="🚫 Отменено", callback_data=f"adm:lstat:{lesson_id}:cancelled")
    builder.button(text="⬅️ Назад", callback_data="adm:lessons")
    builder.adjust(3, 1)
    return builder.as_markup()


def hw_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Выдать ДЗ", callback_data="adm:pick:hw")
    builder.button(text="📥 Работы на проверке", callback_data="adm:subs")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def submissions_list_kb(subs: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sub in subs:
        builder.button(
            text=f"📥 №{sub['id']} · {short(sub['student_name'], 25)} · ДЗ №{sub['homework_id']}",
            callback_data=f"adm:sub:{sub['id']}",
        )
    builder.button(text="⬅️ Назад", callback_data="adm:hw")
    builder.adjust(1)
    return builder.as_markup()


def review_kb(submission_id: int) -> InlineKeyboardMarkup:
    """Кнопки оценки работы (используются и в уведомлении о сдаче)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🌟 Отлично", callback_data=f"adm:rev:{submission_id}:excellent")
    builder.button(text="✅ Принято", callback_data=f"adm:rev:{submission_id}:accepted")
    builder.button(text="🔁 На доработку", callback_data=f"adm:rev:{submission_id}:rework")
    builder.adjust(1)
    return builder.as_markup()


def review_comment_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Без комментария", callback_data="adm:revskip")
    return builder.as_markup()


def booking_done_kb(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Заявка обработана", callback_data=f"adm:bkdone:{booking_id}")
    return builder.as_markup()


def bookings_kb(bookings: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in bookings:
        builder.button(text=f"✅ №{item['id']} · {short(item['name'], 25)}", callback_data=f"adm:bkdone:{item['id']}")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def broadcast_audience_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Всем", callback_data="adm:bca:all")
    builder.button(text="🎓 Только ученикам", callback_data="adm:bca:students")
    builder.button(text="👪 Только родителям", callback_data="adm:bca:parents")
    builder.button(text="☑️ Выбрать вручную", callback_data="adm:bca:select")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def broadcast_select_kb(users: list[dict], selected: set[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in users:
        mark = "☑️" if user["id"] in selected else "⬜"
        icon = "🎓" if user["role"] == "student" else "👪"
        builder.button(text=f"{mark} {icon} {short(user['full_name'], 30)}", callback_data=f"adm:bct:{user['id']}")
    builder.button(text=f"Далее ➡️ (выбрано: {len(selected)})", callback_data="adm:bcnext")
    builder.button(text="✖️ Отмена", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📨 Отправить", callback_data="adm:bcok")
    builder.button(text="✖️ Отмена", callback_data="adm:bcno")
    builder.adjust(2)
    return builder.as_markup()


def faq_admin_kb(items: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=f"🗑 {short(item['question'], 45)}", callback_data=f"adm:faqdel:{item['id']}")
    builder.button(text="➕ Добавить вопрос", callback_data="adm:faqadd")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def materials_admin_kb(items: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=f"📄 {short(item['title'], 50)}", callback_data=f"adm:mat:{item['id']}")
    builder.button(text="➕ Добавить материал", callback_data="adm:matadd")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def material_card_kb(material_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Удалить", callback_data=f"adm:matdel:{material_id}")
    builder.button(text="⬅️ К списку", callback_data="adm:mat")
    builder.adjust(1)
    return builder.as_markup()

def teachers_list_kb(teachers: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in teachers:
        builder.button(
            text=f"👨‍🏫 {short(t['name'], 30)} · {t['students_count']} уч.",
            callback_data=f"adm:t:{t['id']}",
        )
    builder.button(text="➕ Добавить преподавателя", callback_data="adm:tadd")
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def teacher_card_kb(teacher_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data=f"adm:tstats:{teacher_id}")
    builder.button(text="👥 Ученики", callback_data=f"adm:tstudents:{teacher_id}")
    builder.button(text="🗑 Удалить", callback_data=f"adm:tdel:{teacher_id}")
    builder.button(text="⬅️ К списку", callback_data="adm:teachers")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def pick_teacher_kb(teachers: list[dict], user_id: int) -> InlineKeyboardMarkup:
    """Выбор преподавателя для привязки ученика (callback: adm:setteacher:<uid>:<tid>)."""
    builder = InlineKeyboardBuilder()
    for t in teachers:
        builder.button(
            text=f"👨‍🏫 {short(t['name'], 35)}",
            callback_data=f"adm:setteacher:{user_id}:{t['id']}",
        )
    builder.button(text="❌ Снять привязку", callback_data=f"adm:setteacher:{user_id}:0")
    builder.button(text="⬅️ Назад", callback_data=f"adm:u:{user_id}")
    builder.adjust(1)
    return builder.as_markup()
