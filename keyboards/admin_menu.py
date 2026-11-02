"""
Клавиатуры админ-панели (только Inline).
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils import fmt_dt, short


def admin_main_kb(students: int | None = None, new_bookings: int | None = None) -> InlineKeyboardMarkup:
    """Меню админ-панели. Счётчики в подписях показываются, только если переданы."""
    students_label = "👥 Ученики" + (f" · {students}" if students is not None else "")
    bookings_label = "📝 Заявки" + (f" · {new_bookings}" if new_bookings else "")
    builder = InlineKeyboardBuilder()
    builder.button(text=students_label, callback_data="adm:students")
    builder.button(text="👨‍🏫 Преподаватели", callback_data="adm:teachers")
    builder.button(text="📅 Расписание", callback_data="adm:schedule")
    builder.button(text="📚 Домашние задания", callback_data="adm:hw")
    builder.button(text="📅 Сегодня", callback_data="adm:today")
    builder.button(text="📊 Статистика", callback_data="adm:stats")
    builder.button(text="💳 Оплата", callback_data="adm:pay")
    builder.button(text=bookings_label, callback_data="adm:bk")
    builder.button(text="📢 Рассылка", callback_data="adm:bc")
    builder.button(text="❓ FAQ", callback_data="adm:faq")
    builder.button(text="📎 Материалы", callback_data="adm:mat")
    builder.button(text="🏠 Главное меню", callback_data="menu:main")
    builder.adjust(2, 2, 2, 2, 2, 2)
    return builder.as_markup()

def back_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В админ-панель", callback_data="adm:main")
    return builder.as_markup()


def cancel_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✖️ Отмена", callback_data="adm:main")
    return builder.as_markup()


STUDENTS_PER_PAGE = 9  # 3 кнопки в ряд × 3 ряда на страницу


def _user_icon(user: dict) -> str:
    """Иконка роли; заблокированный пользователь помечается красным флажком."""
    if user.get("is_blocked"):
        return "🚫"
    return "🎓" if user["role"] == "student" else "👪"


def student_button_label(user: dict, limit: int = 12) -> str:
    """«Гримович Маргарита» → «Гримович М.» — короткая подпись под плитку 3 в ряд."""
    parts = str(user.get("full_name") or "").split()
    if len(parts) >= 2:
        label = f"{parts[0]} {parts[1][0]}."
    else:
        label = parts[0] if parts else "—"
    return short(label, limit)


def students_list_kb(users: list[dict], page: int = 0, pages: int = 1,
                     role_filter: str = "all", counts: dict | None = None) -> InlineKeyboardMarkup:
    """Список учеников: плитка по 3 в ряд, фильтры по роли и постраничная навигация."""
    counts = counts or {}
    kb = InlineKeyboardBuilder()

    def tab(key: str, label: str) -> InlineKeyboardButton:
        mark = "▸ " if key == role_filter else ""
        return InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"adm:students:{key}:0")

    kb.row(
        tab("all", f"Все · {counts.get('all', 0)}"),
        tab("student", f"🎓 {counts.get('student', 0)}"),
        tab("parent", f"👪 {counts.get('parent', 0)}"),
    )
    kb.row(
        InlineKeyboardButton(text="🔍 Поиск", callback_data="adm:find"),
        InlineKeyboardButton(text=f"⚠️ С долгом · {counts.get('debt', 0)}",
                             callback_data="adm:students:debt:0"),
    )
    for i in range(0, len(users), 3):
        row = [
            InlineKeyboardButton(
                text=f"{_user_icon(user)} {student_button_label(user)}",
                callback_data=f"adm:u:{user['id']}",
            )
            for user in users[i:i + 3]
        ]
        kb.row(*row)

    if pages > 1:
        prev_page = max(0, page - 1)
        next_page = min(pages - 1, page + 1)
        kb.row(
            InlineKeyboardButton(text="◀️", callback_data=f"adm:students:{role_filter}:{prev_page}"),
            InlineKeyboardButton(text=f"{page + 1} / {pages}",
                                 callback_data=f"adm:students:{role_filter}:{page}"),
            InlineKeyboardButton(text="▶️", callback_data=f"adm:students:{role_filter}:{next_page}"),
        )

    kb.row(InlineKeyboardButton(text="🔄 Обновить",
                                callback_data=f"adm:students:{role_filter}:{page}"))
    kb.row(InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm:main"))
    return kb.as_markup()


def user_card_kb(user: dict) -> InlineKeyboardMarkup:
    """Карточка пользователя: статистика сверху, действия по 2 в ряд."""
    uid = user["id"]
    kb = InlineKeyboardBuilder()
    if user["role"] == "student":
        kb.row(InlineKeyboardButton(text="📊 Статистика ученика", callback_data=f"adm:ustats:{uid}"))
        kb.row(
            InlineKeyboardButton(text="➕ Занятие", callback_data=f"adm:ulesson:{uid}"),
            InlineKeyboardButton(text="📚 Выдать ДЗ", callback_data=f"adm:uhw:{uid}"),
        )
        kb.row(
            InlineKeyboardButton(text="💳 Принять оплату", callback_data=f"adm:upay:{uid}"),
            InlineKeyboardButton(text="💬 Комментарий", callback_data=f"adm:ucomment:{uid}"),
        )
        kb.row(InlineKeyboardButton(text="👨‍🏫 Преподаватель", callback_data=f"adm:uteacher:{uid}"))
    block_text = "✅ Разблокировать" if user["is_blocked"] else "🚫 Заблокировать"
    kb.row(
        InlineKeyboardButton(text="✏️ Изменить данные", callback_data=f"adm:uedit:{uid}"),
        InlineKeyboardButton(text=block_text, callback_data=f"adm:ublock:{uid}"),
    )
    kb.row(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:udel:{uid}"))
    kb.row(InlineKeyboardButton(text="⬅️ К списку", callback_data="adm:students"))
    return kb.as_markup()


def student_stats_kb(user_id: int) -> InlineKeyboardMarkup:
    """Кнопки экрана статистики ученика."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔄 Обновить", callback_data=f"adm:ustats:{user_id}"))
    kb.row(
        InlineKeyboardButton(text="📅 Занятия", callback_data=f"adm:uless:{user_id}"),
        InlineKeyboardButton(text="💳 Оплаты", callback_data=f"adm:upays:{user_id}"),
    )
    kb.row(InlineKeyboardButton(text="💳 Принять оплату / продлить", callback_data=f"adm:upay:{user_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ К карточке", callback_data=f"adm:u:{user_id}"))
    return kb.as_markup()


def student_lessons_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ К статистике", callback_data=f"adm:ustats:{user_id}"))
    return kb.as_markup()


def student_payments_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ К статистике", callback_data=f"adm:ustats:{user_id}"))
    return kb.as_markup()


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
    """Выбор ученика плиткой по 3 в ряд; callback_data = '<prefix>:<id>'."""
    kb = InlineKeyboardBuilder()
    for i in range(0, len(students), 3):
        kb.row(*[
            InlineKeyboardButton(text=f"🎓 {student_button_label(student)}",
                                 callback_data=f"{prefix}:{student['id']}")
            for student in students[i:i + 3]
        ])
    kb.row(InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm:main"))
    return kb.as_markup()


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
    """Список заявок: открываем карточку, а не закрываем вслепую."""
    kb = InlineKeyboardBuilder()
    for item in bookings:
        kb.row(InlineKeyboardButton(text=f"📄 №{item['id']} · {short(item['name'], 25)}",
                                    callback_data=f"adm:bkc:{item['id']}"))
    kb.row(InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm:main"))
    return kb.as_markup()


def booking_card_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="👤 Создать ученика", callback_data=f"adm:bknew:{booking_id}"))
    kb.row(InlineKeyboardButton(text="✅ Обработана", callback_data=f"adm:bkdone:{booking_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ К заявкам", callback_data="adm:bk"))
    return kb.as_markup()


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
