"""
Клавиатуры для учеников, родителей и гостей (только Inline).
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CHANNEL_URL, FORMATS, GOALS, HW_STATUS_LABELS, SUBJECTS, TEACHER_URL
from utils import short


def role_kb(is_admin: bool = False, is_teacher: bool = False) -> InlineKeyboardMarkup:
    """Выбор роли при первом запуске (больше не используется в воронке — вместо неё lead_kb)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎓 Я ученик", callback_data="role:student")
    builder.button(text="👨‍👩‍👧 Я родитель", callback_data="role:parent")
    builder.button(text="🛠 Я администратор", callback_data="role:admin")
    if is_teacher:
        builder.button(text="👨‍🏫 Я преподаватель", callback_data="role:teacher")
    builder.button(text="📝 Записаться на пробный урок", callback_data="menu:booking")
    builder.button(text="📎 Материалы", callback_data="menu:materials")
    builder.button(text="❓ Частые вопросы", callback_data="menu:faq")
    builder.adjust(1)
    return builder.as_markup()


def main_menu_kb(role: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню зарегистрированного пользователя."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Расписание", callback_data="menu:schedule")
    if role == "student":
        builder.button(text="📚 Домашние задания", callback_data="menu:homework")
    else:
        builder.button(text="📊 Отчёт по ребёнку", callback_data="menu:report")
    builder.button(text="💳 Баланс занятий", callback_data="menu:balance")
    builder.button(text="📝 Пробный урок", callback_data="menu:booking")
    builder.button(text="📎 Материалы", callback_data="menu:materials")
    builder.button(text="❓ Частые вопросы", callback_data="menu:faq")
    builder.button(text="👨‍🏫 Преподаватель", url=TEACHER_URL)
    builder.button(text="📢 Канал школы", url=CHANNEL_URL)
    if is_admin:
        builder.button(text="🛠 Админ-панель", callback_data="adm:main")
    builder.adjust(2)
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="menu:main")
    return builder.as_markup()


def subject_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, title in SUBJECTS.items():
        builder.button(text=title, callback_data=f"book:subj:{code}")
    builder.adjust(1)
    return builder.as_markup()


def booking_format_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, title in FORMATS.items():
        builder.button(text=title, callback_data=f"book:fmt:{code}")
    builder.adjust(1)
    return builder.as_markup()


def booking_goal_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, title in GOALS.items():
        builder.button(text=title, callback_data=f"book:goal:{code}")
    builder.adjust(1)
    return builder.as_markup()


def faq_kb(items: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=f"❓ {short(item['question'], 55)}", callback_data=f"faq:{item['id']}")
    builder.button(text="⬅️ В меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def faq_back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К вопросам", callback_data="menu:faq")
    builder.button(text="🏠 В меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def pay_kb(url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить", url=url)
    builder.button(text="⬅️ В меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def homework_list_kb(items: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for hw in items:
        label = HW_STATUS_LABELS.get(hw["last_status"], HW_STATUS_LABELS[None])
        icon = label.split()[0]
        title = short(hw["text"] or "Файл", 28)
        builder.button(text=f"{icon} №{hw['id']} · {title}", callback_data=f"hw:open:{hw['id']}")
    builder.button(text="⬅️ В меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def homework_open_kb(hw_id: int, can_submit: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_submit:
        builder.button(text="📤 Сдать решение", callback_data=f"hw:submit:{hw_id}")
    builder.button(text="📚 Все задания", callback_data="menu:homework")
    builder.adjust(1)
    return builder.as_markup()


def homework_notify_kb(hw_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📘 Открыть задание", callback_data=f"hw:open:{hw_id}")
    return builder.as_markup()


def homework_collect_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить решение", callback_data="hw:send")
    builder.button(text="✖️ Отмена", callback_data="hw:cancel")
    builder.adjust(1)
    return builder.as_markup()


def materials_list_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """Список материалов (чек-листов) для учеников, родителей и гостей."""
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=f"📄 {short(item['title'], 50)}", callback_data=f"mat:{item['id']}")
    builder.button(text="⬅️ В меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def material_cta_kb() -> InlineKeyboardMarkup:
    """Кнопки под отправленным материалом: запись на пробный урок и навигация."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Записаться на пробный урок", callback_data="menu:booking")
    builder.button(text="📎 Другие материалы", callback_data="menu:materials")
    builder.button(text="🏠 В меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def lead_kb(is_admin: bool = False, is_teacher: bool = False) -> InlineKeyboardMarkup:
    """Для незарегистрированных вместо role_kb(): сразу запись на пробный урок.

    Кнопки входа в админ-панель / панель преподавателя сохранены: администратор или преподаватель,
    которого нет в таблице users, иначе потерял бы к ним доступ (раньше они были в role_kb).
    """
    rows = [
        [InlineKeyboardButton(text="📝 Записаться на пробный урок", callback_data="lead:student")],
        [InlineKeyboardButton(text="👨‍👩‍👧 Я родитель — записать ребёнка", callback_data="lead:parent")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="role:admin")])
    if is_teacher:
        rows.append([InlineKeyboardButton(text="👨‍🏫 Панель преподавателя", callback_data="role:teacher")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def site_confirm_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Подтверждение заявки, пришедшей с сайта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Всё верно, записать", callback_data=f"site:ok:{booking_id}")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"site:edit:{booking_id}")],
        ]
    )


def role_pick_kb() -> InlineKeyboardMarkup:
    """Выбор роли при первом входе (ученик / родитель)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Я ученик", callback_data="role:student")],
            [InlineKeyboardButton(text="👨‍👩‍👧 Я родитель", callback_data="role:parent")],
        ]
    )


def confirm_booking_kb() -> InlineKeyboardMarkup:
    """Подтверждение заявки (для сценария с предзаполненными данными)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Всё верно", callback_data="book:confirm")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="book:edit")],
        ]
    )
