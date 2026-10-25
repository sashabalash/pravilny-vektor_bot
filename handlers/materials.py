"""
Материалы: чек-листы и другие файлы (PDF, картинки) для учеников, родителей и гостей.
Файлы добавляет администратор в админ-панели; здесь — просмотр списка и отправка файла.
Глубокая ссылка t.me/<бот>?start=mat_<id> (см. handlers/start.py) отправляет материал сразу.
"""
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from database import db
from keyboards.main_menu import material_cta_kb, materials_list_kb
from utils import esc, safe_edit

router = Router(name="materials")


async def send_material(target: Message, material: dict) -> None:
    """Отправляет файл материала с названием, описанием и кнопкой записи на пробный урок."""
    caption = f"📎 <b>{esc(material['title'])}</b>"
    if material["description"]:
        caption += f"\n\n{esc(material['description'])}"
    markup = material_cta_kb()
    if material["file_type"] == "photo":
        await target.answer_photo(material["file_id"], caption=caption, reply_markup=markup)
    else:
        await target.answer_document(material["file_id"], caption=caption, reply_markup=markup)


@router.callback_query(F.data == "menu:materials")
async def cb_materials(callback: CallbackQuery) -> None:
    await callback.answer()
    items = await db.list_materials()
    text = ("📎 <b>Материалы</b>\nВыберите, что хотите получить:" if items
            else "📎 Материалы скоро появятся. Загляните позже!")
    await safe_edit(callback.message, text, materials_list_kb(items))


@router.callback_query(F.data.startswith("mat:"))
async def cb_material(callback: CallbackQuery) -> None:
    material = await db.get_material(int(callback.data.split(":")[1]))
    if not material:
        await callback.answer("Этот материал больше не доступен", show_alert=True)
        return
    await callback.answer()
    await send_material(callback.message, material)
