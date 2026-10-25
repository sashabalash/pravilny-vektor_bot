"""
Домашние задания (сторона ученика): список заданий, просмотр, сдача решения
(фото, текст, файлы), уведомление администраторов о сдаче.
Выдача ДЗ и проверка выполняются в админ-панели (handlers/admin.py).
"""
import logging

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS, HW_STATUS_LABELS
from database import db
from keyboards.admin_menu import review_kb
from keyboards.main_menu import (back_to_menu_kb, homework_collect_kb, homework_list_kb,
                                 homework_open_kb)
from notifications import safe_send
from utils import esc, safe_edit, short

logger = logging.getLogger(__name__)
router = Router(name="homework")

MAX_ITEMS = 10


class HomeworkStates(StatesGroup):
    collecting = State()


# ---------- Отправка работы администратору (используется и в админ-панели) ----------

async def send_submission_to_admin(bot: Bot, admin_id: int, submission_id: int) -> None:
    """Присылает администратору содержимое сдачи и кнопки оценки."""
    sub = await db.get_submission(submission_id)
    if not sub:
        return
    items = await db.get_submission_items(submission_id)
    await safe_send(
        bot, admin_id,
        f"📥 <b>Сдача ДЗ №{sub['homework_id']}</b> (работа №{submission_id})\n"
        f"👤 {esc(sub['student_name'])}\n📚 {esc(short(sub['hw_text'] or 'Файл', 80))}",
    )
    for item in items:
        try:
            if item["item_type"] == "text":
                await bot.send_message(admin_id, f"💬 {esc(item['text'])}")
            elif item["item_type"] == "photo":
                await bot.send_photo(admin_id, item["file_id"], caption=item["text"])
            elif item["item_type"] == "document":
                await bot.send_document(admin_id, item["file_id"], caption=item["text"])
        except TelegramAPIError as exc:
            logger.error("Не удалось отправить часть работы админу %s: %s", admin_id, exc)
    await safe_send(bot, admin_id, "Оцените работу:", review_kb(submission_id))


# ---------- Список и просмотр заданий ----------

async def show_homework_list(target: Message, db_user: dict | None) -> None:
    if not db_user or db_user["role"] != "student":
        await target.answer("📚 Этот раздел доступен ученикам.", reply_markup=back_to_menu_kb())
        return
    items = await db.list_homework(db_user["id"])
    if not items:
        await target.answer("📚 Заданий пока нет. Когда преподаватель выдаст ДЗ — я сразу сообщу! 🎉",
                            reply_markup=back_to_menu_kb())
        return
    await target.answer("📚 <b>Ваши домашние задания</b>\nВыберите задание:", reply_markup=homework_list_kb(items))


@router.callback_query(F.data == "menu:homework")
async def cb_homework_list(callback: CallbackQuery, db_user: dict | None) -> None:
    await callback.answer()
    await show_homework_list(callback.message, db_user)


@router.callback_query(F.data.startswith("hw:open:"))
async def cb_homework_open(callback: CallbackQuery, db_user: dict | None) -> None:
    await callback.answer()
    homework = await db.get_homework(int(callback.data.split(":")[2]))
    if not db_user or not homework or homework["student_id"] != db_user["id"]:
        await callback.message.answer("Задание не найдено.", reply_markup=back_to_menu_kb())
        return

    last = await db.get_last_submission(homework["id"])
    status = last["status"] if last else None
    lines = [
        f"📘 <b>Домашнее задание №{homework['id']}</b>\n",
        esc(homework["text"]) if homework["text"] else "<i>Задание во вложении ниже</i>",
        f"\nСтатус: {HW_STATUS_LABELS.get(status, HW_STATUS_LABELS[None])}",
    ]
    if last and last["teacher_comment"]:
        lines.append(f"💬 Комментарий преподавателя: {esc(last['teacher_comment'])}")

    can_submit = status in (None, "rework")
    await callback.message.answer("\n".join(lines), reply_markup=homework_open_kb(homework["id"], can_submit))
    if homework["file_id"]:
        if homework["file_type"] == "photo":
            await callback.message.answer_photo(homework["file_id"])
        else:
            await callback.message.answer_document(homework["file_id"])


# ---------- Сдача решения ----------

@router.callback_query(F.data.startswith("hw:submit:"))
async def cb_homework_submit(callback: CallbackQuery, state: FSMContext, db_user: dict | None) -> None:
    homework = await db.get_homework(int(callback.data.split(":")[2]))
    if not db_user or not homework or homework["student_id"] != db_user["id"]:
        await callback.answer("Задание не найдено", show_alert=True)
        return
    last = await db.get_last_submission(homework["id"])
    if last and last["status"] not in ("rework",):
        await callback.answer("Это задание уже сдано или принято", show_alert=True)
        return
    await callback.answer()
    await state.set_state(HomeworkStates.collecting)
    await state.update_data(homework_id=homework["id"], items=[])
    await callback.message.answer(
        f"📤 <b>Сдача ДЗ №{homework['id']}</b>\n\n"
        f"Отправьте решение: фото, текст или файлы (до {MAX_ITEMS} сообщений). "
        "Когда всё отправите — нажмите «Отправить решение».\nОтмена: /cancel",
        reply_markup=homework_collect_kb(),
    )


async def _add_item(message: Message, state: FSMContext, item: dict) -> None:
    data = await state.get_data()
    items = data.get("items", [])
    if len(items) >= MAX_ITEMS:
        await message.answer(f"⚠️ Достигнут лимит ({MAX_ITEMS}). Нажмите «Отправить решение».",
                             reply_markup=homework_collect_kb())
        return
    items.append(item)
    await state.update_data(items=items)
    await message.answer(f"📎 Добавлено: {len(items)}. Можно отправить ещё или нажать «Отправить решение».",
                         reply_markup=homework_collect_kb())


@router.message(HomeworkStates.collecting, F.photo)
async def hw_photo(message: Message, state: FSMContext) -> None:
    await _add_item(message, state, {"type": "photo", "file_id": message.photo[-1].file_id,
                                     "text": message.caption})


@router.message(HomeworkStates.collecting, F.document)
async def hw_document(message: Message, state: FSMContext) -> None:
    await _add_item(message, state, {"type": "document", "file_id": message.document.file_id,
                                     "text": message.caption})


@router.message(HomeworkStates.collecting, F.text, ~F.text.startswith("/"))
async def hw_text(message: Message, state: FSMContext) -> None:
    await _add_item(message, state, {"type": "text", "text": message.text})


@router.message(HomeworkStates.collecting)
async def hw_unsupported(message: Message) -> None:
    if message.text and message.text.startswith("/"):
        raise SkipHandler
    await message.answer("⚠️ Поддерживаются фото, текст и файлы (документы).")


@router.callback_query(HomeworkStates.collecting, F.data == "hw:send")
async def cb_homework_send(callback: CallbackQuery, state: FSMContext, bot: Bot, db_user: dict | None) -> None:
    data = await state.get_data()
    items = data.get("items", [])
    if not items:
        await callback.answer("Сначала отправьте решение (фото, текст или файл)", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    if not db_user:
        return

    submission_id = await db.create_submission(data["homework_id"], db_user["id"], items)
    logger.info("Сдача ДЗ №%s: работа №%s от %s", data["homework_id"], submission_id, db_user["full_name"])
    await callback.message.answer(
        "✅ <b>Решение отправлено!</b> Преподаватель проверит работу, и я пришлю результат.",
        reply_markup=back_to_menu_kb())
    for admin_id in ADMIN_IDS:
        await send_submission_to_admin(bot, admin_id, submission_id)


@router.callback_query(F.data == "hw:cancel")
async def cb_homework_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Отменено")
    await state.clear()
    await safe_edit(callback.message, "↩️ Сдача отменена.", back_to_menu_kb())
