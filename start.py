"""
Старт бота: /start (в том числе ссылки с сайта и ссылки на материалы), /menu, /cancel,
возврат в главное меню, вход в панели администратора и преподавателя, запасной обработчик.
"""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.booking import begin_deeplink_booking, parse_deeplink
from handlers.common import WELCOME_NEW, show_main_menu
from handlers.materials import send_material
from keyboards.admin_menu import admin_main_kb
from keyboards.main_menu import role_kb
from keyboards.teacher_menu import teacher_main_kb
from utils import esc, safe_edit

router = Router(name="start")
fallback_router = Router(name="fallback")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext,
                    db_user: dict | None, is_admin: bool, teacher: dict | None) -> None:
    await state.clear()
    args = (command.args or "").strip()

    # 1) Ссылка с сайта: t.me/<бот>?start=ind_mat_ct — формат, предмет и цель уже известны
    booking_params = parse_deeplink(args)
    if booking_params:
        await begin_deeplink_booking(message, state, booking_params, db_user)
        return

    # 2) Ссылка на материал из канала: t.me/<бот>?start=mat_<id>
    if args.startswith("mat_") and args[4:].isdigit():
        material = await db.get_material(int(args[4:]))
        if material:
            await send_material(message, material)

    # 3) Обычный старт
    if db_user:
        await show_main_menu(message, db_user, is_admin, f"👋 С возвращением, {esc(db_user['full_name'])}!")
    else:
        await message.answer(WELCOME_NEW, reply_markup=role_kb(is_admin, teacher is not None))


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, db_user: dict | None, is_admin: bool,
                   teacher: dict | None) -> None:
    await state.clear()
    if db_user:
        await show_main_menu(message, db_user, is_admin)
    else:
        await message.answer(WELCOME_NEW, reply_markup=role_kb(is_admin, teacher is not None))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db_user: dict | None, is_admin: bool,
                     teacher: dict | None) -> None:
    await state.clear()
    if db_user:
        await show_main_menu(message, db_user, is_admin, "↩️ Действие отменено.")
    else:
        await message.answer("↩️ Действие отменено.", reply_markup=role_kb(is_admin, teacher is not None))


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, db_user: dict | None, is_admin: bool,
                       teacher: dict | None) -> None:
    await callback.answer()
    await state.clear()
    if db_user:
        await show_main_menu(callback.message, db_user, is_admin, edit=True)
    else:
        await safe_edit(callback.message, WELCOME_NEW, role_kb(is_admin, teacher is not None))


@router.callback_query(F.data == "role:admin")
async def cb_role_admin(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    await callback.answer()
    if is_admin:
        await state.clear()
        await callback.message.answer("🛠 <b>Админ-панель</b>\nВыберите раздел:", reply_markup=admin_main_kb())
    else:
        await callback.message.answer(
            f"⛔ Ваш Telegram ID <code>{callback.from_user.id}</code> не найден в списке администраторов.\n"
            "Если вы владелец школы — добавьте этот ID в файл .env (ADMIN_IDS) и перезапустите бота.")


@router.callback_query(F.data == "role:teacher")
async def cb_role_teacher(callback: CallbackQuery, state: FSMContext, teacher: dict | None) -> None:
    await callback.answer()
    if teacher:
        await state.clear()
        await callback.message.answer(
            f"👨‍🏫 <b>Панель преподавателя</b>\n{esc(teacher['name'])}", reply_markup=teacher_main_kb())
    else:
        await callback.message.answer(
            f"⛔ Вас нет в списке преподавателей. Ваш Telegram ID: <code>{callback.from_user.id}</code> — "
            "сообщите его администратору школы.")


@fallback_router.message()
async def unknown_message(message: Message, db_user: dict | None) -> None:
    """Последний обработчик: сообщение не подошло ни под один сценарий."""
    if db_user:
        await message.answer("🤔 Не совсем понял. Откройте меню: /menu\nОтменить текущее действие: /cancel")
    else:
        await message.answer("🤔 Не совсем понял. Нажмите /start, чтобы начать.")
