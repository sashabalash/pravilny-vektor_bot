"""
Панель преподавателя (/teacher или кнопка «Панель преподавателя»).
Преподаватель видит только учеников, которые привязаны к нему в базе (users.teacher_id):
  • «Мои ученики» — список;
  • «Моя статистика» — ученики, проведённые занятия, деньги, которые принесли его ученики;
  • «Статистика по ученику» — карточка успеваемости выбранного ученика;
  • «Мои занятия» — ближайшие занятия с отметкой результата.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from database import db
from keyboards.teacher_menu import (teacher_back_kb, teacher_lesson_status_kb, teacher_lessons_kb,
                                    teacher_main_kb, teacher_pick_kb, teacher_student_back_kb)
from notifications import safe_send
from stats_text import student_card_text
from utils import DB_DT_FORMAT, esc, fmt_dt, now_local, safe_edit

logger = logging.getLogger(__name__)

NO_STUDENTS_TEXT = "У вас пока нет учеников."


class IsTeacher(BaseFilter):
    """Пропускает только пользователей из таблицы teachers (данные кладёт AuthMiddleware)."""

    async def __call__(self, event: TelegramObject, teacher: dict | None = None) -> bool:
        return teacher is not None


# Публичный роутер: команда /teacher с понятным отказом; закрытый — все остальные действия
router = Router(name="teacher")
teacher_router = Router(name="teacher_only")
teacher_router.message.filter(IsTeacher())
teacher_router.callback_query.filter(IsTeacher())
router.include_router(teacher_router)


def _panel_text(teacher: dict) -> str:
    subject = f" · {esc(teacher['subject'])}" if teacher["subject"] else ""
    return f"👨‍🏫 <b>Панель преподавателя</b>\n{esc(teacher['name'])}{subject}"


@router.message(Command("teacher"))
async def cmd_teacher(message: Message, state: FSMContext, teacher: dict | None) -> None:
    if not teacher:
        await message.answer("⛔ Эта команда доступна только преподавателям школы.")
        return
    await state.clear()
    await message.answer(_panel_text(teacher), reply_markup=teacher_main_kb())


@teacher_router.callback_query(F.data == "tch:main")
async def cb_main(callback: CallbackQuery, state: FSMContext, teacher: dict) -> None:
    await callback.answer()
    await state.clear()
    await safe_edit(callback.message, _panel_text(teacher), teacher_main_kb())


# ---------- Мои ученики ----------

@teacher_router.callback_query(F.data == "tch:students")
async def cb_students(callback: CallbackQuery, teacher: dict) -> None:
    await callback.answer()
    students = await db.list_students_of_teacher(teacher["id"])
    if not students:
        await safe_edit(callback.message, f"📊 <b>Мои ученики</b>\n\n{NO_STUDENTS_TEXT}", teacher_back_kb())
        return
    lines = [f"📊 <b>Мои ученики</b> ({len(students)})\n"]
    for number, student in enumerate(students[:60], start=1):
        blocked = " 🚫" if student["is_blocked"] else ""
        lines.append(
            f"{number}. <b>{esc(student['full_name'])}</b>{blocked} · {esc(student['grade'])} кл. · "
            f"{esc(student['subject'])} · осталось: {student['balance']} зан.")
    await safe_edit(callback.message, "\n".join(lines), teacher_back_kb())


# ---------- Моя статистика ----------

@teacher_router.callback_query(F.data == "tch:stats")
async def cb_stats(callback: CallbackQuery, teacher: dict) -> None:
    await callback.answer()
    stats = await db.get_teacher_stats(teacher["id"])
    if stats["students"] == 0:
        text = f"📈 <b>Моя статистика</b>\n\n{NO_STUDENTS_TEXT}"
    else:
        text = (
            "📈 <b>Моя статистика</b> (только мои ученики)\n\n"
            f"🎓 Учеников: <b>{stats['students']}</b>\n"
            f"✅ Проведено занятий: <b>{stats['lessons_done']}</b>\n"
            f"🗓 Запланировано: {stats['lessons_planned']}\n\n"
            f"💰 Оплаты моих учеников: <b>{stats['money_total']:g} BYN</b>\n"
            f"📆 За текущий месяц: <b>{stats['money_month']:g} BYN</b>")
    await safe_edit(callback.message, text, teacher_back_kb())


# ---------- Статистика по ученику ----------

@teacher_router.callback_query(F.data == "tch:pick")
async def cb_pick(callback: CallbackQuery, teacher: dict) -> None:
    await callback.answer()
    students = await db.list_students_of_teacher(teacher["id"])
    if not students:
        await safe_edit(callback.message, f"👤 <b>Статистика по ученику</b>\n\n{NO_STUDENTS_TEXT}",
                        teacher_back_kb())
        return
    await safe_edit(callback.message, "👤 <b>Статистика по ученику</b>\nВыберите ученика:",
                    teacher_pick_kb(students))


@teacher_router.callback_query(F.data.startswith("tch:ss:"))
async def cb_student_card(callback: CallbackQuery, teacher: dict) -> None:
    student = await db.get_user_by_id(int(callback.data.split(":")[2]))
    # Преподаватель видит только своих учеников
    if not student or student["role"] != "student" or student["teacher_id"] != teacher["id"]:
        await callback.answer("Этот ученик не закреплён за вами", show_alert=True)
        return
    await callback.answer()
    text = await student_card_text(student["id"], with_payments=False)
    await safe_edit(callback.message, text, teacher_student_back_kb())


# ---------- Мои занятия ----------

@teacher_router.callback_query(F.data == "tch:lessons")
async def cb_lessons(callback: CallbackQuery, teacher: dict) -> None:
    await callback.answer()
    since = now_local().replace(hour=0, minute=0).strftime(DB_DT_FORMAT)
    lessons = await db.list_scheduled_lessons_of_teacher(teacher["id"], since)
    if not lessons:
        await safe_edit(callback.message, "📅 <b>Мои занятия</b>\n\nЗапланированных занятий нет.", teacher_back_kb())
        return
    await safe_edit(callback.message, "📅 <b>Мои занятия</b>\nНажмите на занятие, чтобы отметить результат:",
                    teacher_lessons_kb(lessons))


@teacher_router.callback_query(F.data.startswith("tch:les:"))
async def cb_lesson_card(callback: CallbackQuery, teacher: dict) -> None:
    lesson = await db.get_lesson(int(callback.data.split(":")[2]))
    if not lesson or lesson["teacher_id"] != teacher["id"]:
        await callback.answer("Занятие не найдено", show_alert=True)
        return
    await callback.answer()
    text = (f"📅 <b>Занятие №{lesson['id']}</b>\n👤 {esc(lesson['student_name'])}\n"
            f"🕒 {fmt_dt(lesson['lesson_dt'])}\n\n"
            "Отметьте результат («Проведено» спишет одно занятие с баланса ученика):")
    await safe_edit(callback.message, text, teacher_lesson_status_kb(lesson["id"]))


@teacher_router.callback_query(F.data.startswith("tch:lstat:"))
async def cb_lesson_status(callback: CallbackQuery, bot: Bot, teacher: dict) -> None:
    _, _, lesson_id, status = callback.data.split(":")
    lesson = await db.get_lesson(int(lesson_id))
    if not lesson or lesson["teacher_id"] != teacher["id"] or status not in ("done", "missed", "cancelled"):
        await callback.answer("Занятие не найдено", show_alert=True)
        return
    if lesson["status"] != "scheduled":
        await callback.answer("Занятие уже отмечено", show_alert=True)
        return
    await db.set_lesson_status(lesson["id"], status)
    await callback.answer("Сохранено")
    await safe_edit(callback.message, "✅ Статус занятия обновлён.", teacher_back_kb())
    if status == "done":
        student = await db.get_user_by_id(lesson["student_id"])
        if student:
            await safe_send(bot, student["telegram_id"],
                            f"✅ Занятие {fmt_dt(lesson['lesson_dt'])} проведено. Осталось занятий: {student['balance']}")
