"""
Запись на пробный урок и регистрация новых пользователей — единая воронка.

Сценарии:
  1) /start без параметров (новый пользователь): роль → предмет → цель → формат → контакты → заявка;
  2) кнопка «Пробный урок» (уже зарегистрирован): предмет → цель → формат → заявка;
  3) ссылка с сайта t.me/<бот>?start=ind_mat_ct: формат, предмет и цель известны, поэтому бот сразу
     просит подтвердить запись (новому пользователю дополнительно нужны роль и контакты);
  4) «быстрая запись»: клиент заполнил модалку на сайте, API создал заявку (status='pending') и выдал ссылку
     t.me/<бот>?start=b_<token>; в боте остаётся нажать «Всё верно» — данные вводить не нужно.
Заявка сохраняется в таблицу bookings и отправляется администраторам.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, User

from config import FORMATS, GOALS, SUBJECTS
from database import db
from handlers.common import WELCOME_NEW, show_main_menu
from keyboards.admin_menu import booking_done_kb
from keyboards.main_menu import (booking_format_kb, booking_goal_kb, confirm_booking_kb, lead_kb,
                                 role_pick_kb, subject_kb)
from notifications import notify_admins
from utils import esc, validate_grade, validate_name, validate_phone

logger = logging.getLogger(__name__)
router = Router(name="booking")

# Коды из ссылок на сайте → ключи справочников бота (config.py)
LINK_FORMATS = {"ind": "ind", "grp": "group"}
LINK_SUBJECTS = {"mat": "math", "eng": "english", "other": "other"}
LINK_GOALS = {"base": "base", "ct": "ct", "hard": "hard"}


class Funnel(StatesGroup):
    role = State()
    subject = State()
    goal = State()
    lesson_format = State()
    name = State()
    phone = State()
    grade = State()
    child_name = State()
    confirm = State()


def parse_deeplink(args: str) -> dict | None:
    """'ind_mat_ct' → {'lesson_format': 'ind', 'subject': 'math', 'goal': 'ct'}; иначе None."""
    parts = (args or "").lower().split("_")
    if len(parts) != 3:
        return None
    format_code, subject_code, goal_code = parts
    if format_code in LINK_FORMATS and subject_code in LINK_SUBJECTS and goal_code in LINK_GOALS:
        return {
            "lesson_format": LINK_FORMATS[format_code],
            "subject": LINK_SUBJECTS[subject_code],
            "goal": LINK_GOALS[goal_code],
        }
    return None


def _summary(data: dict) -> str:
    return (f"👥 Формат: <b>{FORMATS[data['lesson_format']]}</b>\n"
            f"📖 Предмет: <b>{SUBJECTS[data['subject']]}</b>\n"
            f"🎯 Цель: <b>{GOALS[data['goal']]}</b>")


# ---------- Точки входа ----------

async def begin_deeplink_booking(message: Message, state: FSMContext, params: dict, db_user: dict | None) -> None:
    """Ссылка с сайта: показываем расшифрованную заявку и просим подтвердить."""
    await state.clear()
    await state.update_data(**params)
    await state.set_state(Funnel.confirm)
    greeting = "" if db_user else "👋 <b>Добро пожаловать в «Правильный Вектор»!</b>\n\n"
    await message.answer(
        f"{greeting}📝 <b>Заявка на пробный урок</b>\n\n{_summary(params)}\n\n"
        "🎁 Первый урок — бесплатно. Всё верно? Подтвердите запись 👇",
        reply_markup=confirm_booking_kb())


async def start_funnel(target: Message, state: FSMContext, db_user: dict | None, is_admin: bool = False,
                       is_teacher: bool = False) -> None:
    """Запись из меню: зарегистрированному достаточно выбрать предмет, цель и формат."""
    await state.clear()
    if not db_user:
        await target.answer(WELCOME_NEW, reply_markup=lead_kb(is_admin, is_teacher))
        return
    await state.update_data(role=db_user["role"])
    await state.set_state(Funnel.subject)
    await target.answer(
        "📝 <b>Запись на пробный урок</b>\n\n📖 Какой предмет вас интересует?", reply_markup=subject_kb())


@router.callback_query(F.data == "menu:booking")
async def cb_booking(callback: CallbackQuery, state: FSMContext, db_user: dict | None, is_admin: bool,
                     teacher: dict | None) -> None:
    await callback.answer()
    await start_funnel(callback.message, state, db_user, is_admin, teacher is not None)


@router.message(Command("book"))
async def cmd_booking(message: Message, state: FSMContext, db_user: dict | None, is_admin: bool,
                      teacher: dict | None) -> None:
    await start_funnel(message, state, db_user, is_admin, teacher is not None)


# ---------- Подтверждение заявки с сайта ----------

@router.callback_query(Funnel.confirm, F.data == "book:confirm")
async def cb_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot, db_user: dict | None,
                     is_admin: bool) -> None:
    await callback.answer()
    if db_user:
        await finalize(callback.message, callback.from_user, state, bot, db_user, is_admin)
        return
    await state.set_state(Funnel.role)
    await callback.message.answer("Отлично! Осталось познакомиться. <b>Кто вы?</b>", reply_markup=role_pick_kb())


@router.callback_query(Funnel.confirm, F.data == "book:edit")
async def cb_edit(callback: CallbackQuery, state: FSMContext, db_user: dict | None, is_admin: bool,
                  teacher: dict | None) -> None:
    await callback.answer()
    await start_funnel(callback.message, state, db_user, is_admin, teacher is not None)


# ---------- Роль (новый пользователь) ----------

@router.callback_query(F.data.in_({"role:student", "role:parent"}))
async def cb_role(callback: CallbackQuery, state: FSMContext, db_user: dict | None, is_admin: bool) -> None:
    await callback.answer()
    if db_user:
        await show_main_menu(callback.message, db_user, is_admin, "Вы уже зарегистрированы 👌")
        return
    role = callback.data.split(":")[1]
    data = await state.get_data()
    await state.update_data(role=role)
    if all(key in data for key in ("subject", "goal", "lesson_format")):
        await ask_name(callback.message, state, role)  # заявка пришла с сайта — выбор уже сделан
    else:
        await state.set_state(Funnel.subject)
        await callback.message.answer("📖 Какой предмет вас интересует?", reply_markup=subject_kb())


# ---------- Предмет → цель → формат ----------

@router.callback_query(Funnel.subject, F.data.startswith("book:subj:"))
async def cb_subject(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    code = callback.data.split(":")[2]
    if code not in SUBJECTS:
        # раньше здесь был молчаливый return — воронка «зависала» без единого сообщения
        logger.warning("Неизвестный предмет в callback_data %r; ключи config.SUBJECTS: %s", callback.data, list(SUBJECTS))
        await callback.message.answer("⚠️ Не удалось определить предмет. Выберите, пожалуйста, ещё раз 👇",
                                      reply_markup=subject_kb())
        return
    await state.update_data(subject=code)
    await state.set_state(Funnel.goal)
    await callback.message.answer("🎯 Какая у вас цель?", reply_markup=booking_goal_kb())


@router.callback_query(Funnel.goal, F.data.startswith("book:goal:"))
async def cb_goal(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    code = callback.data.split(":")[2]
    if code not in GOALS:
        return
    await state.update_data(goal=code)
    await state.set_state(Funnel.lesson_format)
    await callback.message.answer("👥 Выберите удобный формат:", reply_markup=booking_format_kb())


@router.callback_query(Funnel.lesson_format, F.data.startswith("book:fmt:"))
async def cb_format(callback: CallbackQuery, state: FSMContext, bot: Bot, db_user: dict | None,
                    is_admin: bool, teacher: dict | None) -> None:
    await callback.answer()
    code = callback.data.split(":")[2]
    if code not in FORMATS:
        return
    await state.update_data(lesson_format=code)
    data = await state.get_data()
    if data.get("site_booking_id"):  # правка заявки с сайта («✏️ Изменить»): обновляем её, а не создаём новую
        await confirm_site_booking(
            callback, state, bot, db_user, is_admin, data["site_booking_id"], teacher,
            changes={"goal": GOALS[data["goal"]], "lesson_format": FORMATS[code]})
        return
    if db_user:
        await finalize(callback.message, callback.from_user, state, bot, db_user, is_admin)
    else:
        data = await state.get_data()
        await ask_name(callback.message, state, data["role"])


# ---------- Контакты нового пользователя ----------

async def ask_name(message: Message, state: FSMContext, role: str) -> None:
    await state.set_state(Funnel.name)
    who = "Как вас зовут?" if role == "student" else "Как вас зовут (имя и фамилия родителя)?"
    await message.answer(f"✍️ {who} Напишите имя и фамилию:")


@router.message(Funnel.name, F.text, ~F.text.startswith("/"))
async def msg_name(message: Message, state: FSMContext) -> None:
    name = validate_name(message.text)
    if not name:
        await message.answer("⚠️ Введите имя и фамилию буквами, например: <i>Иван Петров</i>")
        return
    await state.update_data(name=name)
    await state.set_state(Funnel.phone)
    await message.answer("📱 Введите номер телефона в формате <b>+375XXXXXXXXX</b>:")


@router.message(Funnel.phone, F.text, ~F.text.startswith("/"))
async def msg_phone(message: Message, state: FSMContext) -> None:
    phone = validate_phone(message.text)
    if not phone:
        await message.answer("⚠️ Не похоже на белорусский номер. Формат: <b>+375291234567</b>")
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    if data["role"] == "student":
        await state.set_state(Funnel.grade)
        await message.answer("🏫 В каком вы классе? Например: <i>9</i> или <i>11А</i>")
    else:
        await state.set_state(Funnel.child_name)
        await message.answer("👶 Как зовут вашего ребёнка? Напишите имя и фамилию (так же, как будет у ученика):")


@router.message(Funnel.grade, F.text, ~F.text.startswith("/"))
async def msg_grade(message: Message, state: FSMContext, bot: Bot, is_admin: bool) -> None:
    grade = validate_grade(message.text)
    if not grade:
        await message.answer("⚠️ Укажите класс числом от 1 до 11, например: <i>9</i> или <i>11А</i>")
        return
    await state.update_data(grade=grade)
    await finalize(message, message.from_user, state, bot, None, is_admin)


@router.message(Funnel.child_name, F.text, ~F.text.startswith("/"))
async def msg_child(message: Message, state: FSMContext, bot: Bot, is_admin: bool) -> None:
    child_name = validate_name(message.text)
    if not child_name:
        await message.answer("⚠️ Введите имя и фамилию ребёнка буквами, например: <i>Иван Петров</i>")
        return
    await state.update_data(child_name=child_name)
    await finalize(message, message.from_user, state, bot, None, is_admin)


# ---------- Завершение: регистрация (если нужно) + заявка ----------

async def finalize(message: Message, tg_user: User, state: FSMContext, bot: Bot, db_user: dict | None,
                   is_admin: bool) -> None:
    data = await state.get_data()
    await state.clear()

    if db_user is None:
        db_user = await db.get_user(tg_user.id)  # защита от повторного нажатия
    if db_user is None:
        await db.add_user(
            telegram_id=tg_user.id, username=tg_user.username, role=data["role"],
            full_name=data["name"], phone=data["phone"], grade=data.get("grade"),
            subject=SUBJECTS[data["subject"]], child_name=data.get("child_name"))
        db_user = await db.get_user(tg_user.id)
        logger.info("Новая регистрация: %s (%s, %s)", data["name"], data["role"], tg_user.id)

    subject, goal, lesson_format = SUBJECTS[data["subject"]], GOALS[data["goal"]], FORMATS[data["lesson_format"]]
    phone = db_user["phone"] or "—"
    booking_id = await db.add_booking(
        telegram_id=tg_user.id, username=tg_user.username, name=db_user["full_name"], phone=phone,
        lesson_format=lesson_format, goal=goal, user_role=db_user["role"], subject=subject)
    logger.info("Заявка на пробный урок №%s от %s", booking_id, tg_user.id)

    await show_main_menu(
        message, db_user, is_admin,
        "✅ <b>Заявка принята!</b>\n\n"
        f"👤 {esc(db_user['full_name'])}\n📱 {esc(phone)}\n"
        f"📖 Предмет: {esc(subject)}\n🎯 Цель: {esc(goal)}\n👥 Формат: {esc(lesson_format)}\n\n"
        "Преподаватель свяжется с вами в ближайшее время. 🙌")

    role_text = {"student": "ученик", "parent": "родитель"}.get(db_user["role"], "пользователь")
    child = f"\n👶 Ребёнок: {esc(db_user['child_name'])}" if db_user["child_name"] else ""
    grade = f"\n🏫 Класс: {esc(db_user['grade'])}" if db_user["grade"] else ""
    username = f"@{esc(tg_user.username)}" if tg_user.username else "нет username"
    await notify_admins(
        bot,
        f"📝 <b>Новая заявка на пробный урок №{booking_id}</b>\n\n"
        f"👤 {esc(db_user['full_name'])} ({role_text}){child}{grade}\n📱 {esc(phone)}\n"
        f"✈️ {username} · <a href=\"tg://user?id={tg_user.id}\">открыть чат</a>\n"
        f"📖 Предмет: {esc(subject)}\n🎯 Цель: {esc(goal)}\n👥 Формат: {esc(lesson_format)}",
        booking_done_kb(booking_id),
    )


# ---------- Быстрая запись с сайта: заявка уже лежит в bookings со статусом pending ----------

def site_booking_text(booking: dict, is_new_user: bool) -> str:
    """Экран подтверждения заявки, пришедшей из модалки на сайте (/start b_<token>)."""
    greeting = "👋 <b>Добро пожаловать в «Правильный Вектор»!</b>\n\n" if is_new_user else ""
    subject = f"\n📖 Предмет: <b>{esc(booking['subject'])}</b>" if booking.get("subject") else ""
    return (f"{greeting}📝 <b>Ваша заявка на пробный урок</b>\n\n"
            f"👤 Имя: <b>{esc(booking['name'])}</b>\n"
            f"📱 Телефон: <b>{esc(booking['phone'])}</b>\n"
            f"👥 Формат: <b>{esc(booking['lesson_format'])}</b>\n"
            f"🎯 Цель: <b>{esc(booking['goal'])}</b>{subject}\n\n"
            "Всё верно? Подтвердите запись 👇")


def _site_booking_id(callback_data: str) -> int | None:
    try:
        return int(callback_data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


async def _drop_keyboard(message: Message) -> None:
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass  # сообщение уже без кнопок или слишком старое


async def site_booking_gone(callback: CallbackQuery, state: FSMContext, db_user: dict | None, is_admin: bool,
                            teacher: dict | None) -> None:
    """Заявка уже подтверждена (повторное нажатие / старая ссылка) или её нет в базе."""
    await state.clear()
    await _drop_keyboard(callback.message)
    text = "⚠️ Заявка не найдена или уже обработана."
    if db_user:
        await show_main_menu(callback.message, db_user, is_admin, text)
    else:
        await callback.message.answer(text, reply_markup=lead_kb(is_admin, teacher is not None))


async def confirm_site_booking(callback: CallbackQuery, state: FSMContext, bot: Bot, db_user: dict | None,
                               is_admin: bool, booking_id: int, teacher: dict | None = None,
                               changes: dict | None = None) -> None:
    """pending → new: привязываем заявку к Telegram-аккаунту, при необходимости регистрируем пользователя.

    changes — правки из ветки «✏️ Изменить» ({'goal': ..., 'lesson_format': ...}), применяются до подтверждения.
    """
    tg_user = callback.from_user
    booking = await db.get_pending_site_booking(booking_id)
    if booking is None:
        await site_booking_gone(callback, state, db_user, is_admin, teacher)
        return
    if changes:
        await db.update_site_booking(booking_id, **changes)
        booking.update(changes)
    # UPDATE ... WHERE status='pending': при двойном нажатии второй вызов вернёт False
    if not await db.confirm_booking(booking_id, tg_user.id, tg_user.username):
        await site_booking_gone(callback, state, db_user, is_admin, teacher)
        return
    await state.clear()
    await _drop_keyboard(callback.message)

    if db_user is None:
        db_user = await db.get_user(tg_user.id)  # как и в finalize: защита от повторной регистрации
    if db_user is None:
        role = booking["user_role"] if booking["user_role"] in ("student", "parent") else "student"
        await db.add_user(
            telegram_id=tg_user.id, username=tg_user.username, role=role,
            full_name=booking["name"], phone=booking["phone"], subject=booking["subject"])
        db_user = await db.get_user(tg_user.id)
        logger.info("Новая регистрация по заявке с сайта: %s (%s, %s)", booking["name"], role, tg_user.id)

    phone, goal, lesson_format = booking["phone"], booking["goal"], booking["lesson_format"]
    subject = booking["subject"]
    logger.info("Заявка с сайта №%s подтверждена пользователем %s", booking_id, tg_user.id)

    subject_line = f"\n📖 Предмет: {esc(subject)}" if subject else ""
    await show_main_menu(
        callback.message, db_user, is_admin,
        "✅ <b>Готово! Заявка принята.</b>\n\n"
        f"👤 {esc(booking['name'])}\n📱 {esc(phone)}{subject_line}\n"
        f"🎯 Цель: {esc(goal)}\n👥 Формат: {esc(lesson_format)}\n\n"
        "Преподаватель свяжется с вами в ближайшее время. 🙌")

    role_text = {"student": "ученик", "parent": "родитель"}.get(db_user["role"], "пользователь")
    child = f"\n👶 Ребёнок: {esc(db_user['child_name'])}" if db_user["child_name"] else ""
    grade = f"\n🏫 Класс: {esc(db_user['grade'])}" if db_user["grade"] else ""
    username = f"@{esc(tg_user.username)}" if tg_user.username else "нет username"
    subject_admin = f"\n📖 Предмет: {esc(subject)}" if subject else ""
    await notify_admins(
        bot,
        f"📝 <b>Новая заявка на пробный урок №{booking_id}</b> · 🌐 с сайта\n\n"
        f"👤 {esc(booking['name'])} ({role_text}){child}{grade}\n📱 {esc(phone)}\n"
        f"✈️ {username} · <a href=\"tg://user?id={tg_user.id}\">открыть чат</a>"
        f"{subject_admin}\n🎯 Цель: {esc(goal)}\n👥 Формат: {esc(lesson_format)}",
        booking_done_kb(booking_id),
    )


@router.callback_query(F.data.startswith("site:ok:"))
async def cb_site_ok(callback: CallbackQuery, state: FSMContext, bot: Bot, db_user: dict | None,
                     is_admin: bool, teacher: dict | None) -> None:
    await callback.answer()
    booking_id = _site_booking_id(callback.data)
    if booking_id is None:
        await site_booking_gone(callback, state, db_user, is_admin, teacher)
        return
    await confirm_site_booking(callback, state, bot, db_user, is_admin, booking_id, teacher)


@router.callback_query(F.data.startswith("site:edit:"))
async def cb_site_edit(callback: CallbackQuery, state: FSMContext, db_user: dict | None, is_admin: bool,
                       teacher: dict | None) -> None:
    """«✏️ Изменить»: имя и телефон берём из заявки, клиент заново выбирает цель и формат."""
    await callback.answer()
    booking_id = _site_booking_id(callback.data)
    booking = await db.get_pending_site_booking(booking_id) if booking_id is not None else None
    if booking is None:
        await site_booking_gone(callback, state, db_user, is_admin, teacher)
        return
    await state.clear()
    await state.update_data(site_booking_id=booking_id)
    await state.set_state(Funnel.goal)
    await callback.message.answer("✏️ Давайте поправим.\n\n🎯 Какая у вас цель?", reply_markup=booking_goal_kb())


# ---------- Кнопки лид-клавиатуры (новый пользователь) ----------

@router.callback_query(F.data.in_({"lead:student", "lead:parent"}))
async def cb_lead(callback: CallbackQuery, state: FSMContext, db_user: dict | None, is_admin: bool,
                  teacher: dict | None) -> None:
    """Запись из бота без предварительного выбора роли: роль уже известна по нажатой кнопке."""
    await callback.answer()
    if db_user:  # уже зарегистрирован: имя и телефон есть, сразу к предмету → цели → формату
        await start_funnel(callback.message, state, db_user, is_admin, teacher is not None)
        return
    await state.clear()
    await state.update_data(role=callback.data.split(":")[1])
    await state.set_state(Funnel.subject)
    await callback.message.answer(
        "📝 <b>Запись на пробный урок</b>\n\n📖 Какой предмет вас интересует?", reply_markup=subject_kb())


@router.message(StateFilter(Funnel))
async def funnel_fallback(message: Message) -> None:
    if message.text and message.text.startswith("/"):
        raise SkipHandler
    await message.answer("✍️ Пожалуйста, ответьте текстом или выберите кнопку выше. Отмена: /cancel")
