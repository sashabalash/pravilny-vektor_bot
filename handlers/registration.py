"""
Регистрация новых пользователей: выбор роли, ввод ФИО, телефона,
для ученика — класса, для родителя — имени ребёнка.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import is_admin
from database import db
from handlers.start import show_main_menu
from keyboards.main_menu import back_to_menu_kb
from utils import esc

logger = logging.getLogger(__name__)

router = Router(name="registration")


class Reg(StatesGroup):
    role = State()
    full_name = State()
    phone = State()
    grade = State()       # только для student
    child_name = State()  # только для parent


ROLE_TITLES = {
    "student": "🎓 Ученик",
    "parent": "👨‍👩‍👧 Родитель",
    "admin": "🛠 Администратор",
}


@router.callback_query(F.data.startswith("role:"))
async def cb_role(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    role = callback.data.split(":", 1)[1]
    if role not in ROLE_TITLES:
        return
    await state.update_data(role=role)
    await state.set_state(Reg.full_name)
    await callback.message.edit_text(
        f"Вы выбрали роль: <b>{ROLE_TITLES[role]}</b>\n\n"
        "Как вас зовут? Напишите ФИО полностью (например: Иванов Иван Иванович).",
        reply_markup=back_to_menu_kb(),
    )


@router.message(Reg.full_name)
async def msg_full_name(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 120:
        await message.answer("Пожалуйста, напишите ФИО текстом (от 2 до 120 символов).")
        return
    await state.update_data(full_name=text)
    await state.set_state(Reg.phone)
    await message.answer(
        "📞 Укажите номер телефона для связи (например: +375291234567).",
        reply_markup=back_to_menu_kb(),
    )


@router.message(Reg.phone)
async def msg_phone(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    digits = sum(c.isdigit() for c in text)
    if digits < 7:
        await message.answer("Похоже, это не номер телефона. Введите номер (минимум 7 цифр).")
        return
    await state.update_data(phone=text)
    data = await state.get_data()
    role = data["role"]

    if role == "student":
        await state.set_state(Reg.grade)
        await message.answer(
            "🎓 В каком классе вы учитесь? (например: 11)",
            reply_markup=back_to_menu_kb(),
        )
    elif role == "parent":
        await state.set_state(Reg.child_name)
        await message.answer(
            "👨‍👩‍👧 Как зовут вашего ребёнка? (ФИО)",
            reply_markup=back_to_menu_kb(),
        )
    else:
        await _finish(message, state)


@router.message(Reg.grade)
async def msg_grade(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Напишите класс текстом (например: 11).")
        return
    await state.update_data(grade=text)
    await _finish(message, state)


@router.message(Reg.child_name)
async def msg_child_name(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 2:
        await message.answer("Напишите ФИО ребёнка.")
        return
    await state.update_data(child_name=text)
    await _finish(message, state)


async def _finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()

    role = data["role"]
    telegram_id = message.from_user.id
    username = message.from_user.username

    try:
        user_id = await db.add_user(
            telegram_id=telegram_id,
            username=username,
            role=role,
            full_name=data["full_name"],
            phone=data["phone"],
            grade=data.get("grade"),
            subject=data.get("subject"),
            child_name=data.get("child_name"),
        )
    except Exception as exc:  # IntegrityError на повторный telegram_id
        logger.exception("Не удалось создать пользователя: %s", exc)
        db_user = await db.get_user(telegram_id)
        if db_user:
            await show_main_menu(message, db_user, is_admin(telegram_id),
                                 "Похоже, вы уже зарегистрированы.")
        else:
            await message.answer("Не удалось завершить регистрацию. Попробуйте /start.")
        return

    db_user = await db.get_user_by_id(user_id)
    logger.info("Зарегистрирован пользователь id=%s role=%s tg=%s", user_id, role, telegram_id)

    await show_main_menu(
        message,
        db_user,
        is_admin(telegram_id),
        f"✅ <b>Готово!</b> Спасибо, {esc(db_user['full_name'])}!\n\n"
        "Ваш аккаунт создан. Теперь вам доступно главное меню.",
    )