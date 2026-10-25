"""
FAQ: список вопросов (инлайн-кнопки) и ответы из таблицы faq.
Администратор управляет вопросами в админ-панели.
"""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from database import db
from keyboards.main_menu import faq_back_kb, faq_kb
from utils import esc, safe_edit

router = Router(name="faq")


@router.callback_query(F.data == "menu:faq")
async def cb_faq_list(callback: CallbackQuery) -> None:
    await callback.answer()
    items = await db.list_faq()
    text = "❓ <b>Частые вопросы</b>\nВыберите вопрос:" if items else "Пока вопросов нет."
    await safe_edit(callback.message, text, faq_kb(items))


@router.callback_query(F.data.startswith("faq:"))
async def cb_faq_answer(callback: CallbackQuery) -> None:
    await callback.answer()
    item = await db.get_faq(int(callback.data.split(":")[1]))
    if not item:
        await callback.message.answer("Этот вопрос больше не доступен.")
        return
    await safe_edit(callback.message, f"❓ <b>{esc(item['question'])}</b>\n\n{esc(item['answer'])}", faq_back_kb())
