"""
Отчёты для родителей: посещаемость, средний балл, несданные ДЗ, комментарий преподавателя.
Автоматическая рассылка — каждый понедельник в 10:00 (см. scheduler/reminders.py),
по запросу — команда /report и кнопка «Отчёт по ребёнку».
"""
import logging
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from database import db
from keyboards.main_menu import back_to_menu_kb
from notifications import safe_send
from utils import esc, now_local

logger = logging.getLogger(__name__)
router = Router(name="reports")


async def build_report(student: dict, start: date, end: date) -> dict:
    """Собирает показатели ученика за период [start, end]."""
    start_s, end_s = start.isoformat(), end.isoformat()
    return {
        "start": start,
        "end": end,
        "attended": await db.count_lessons(student["id"], "done", start_s, end_s),
        "missed": await db.count_lessons(student["id"], "missed", start_s, end_s),
        "avg_score": await db.average_score(student["id"], start_s, end_s),
        "unsubmitted": await db.count_unsubmitted(student["id"]),
        "comment": student["report_comment"],
    }


def format_report(student: dict, report: dict) -> str:
    avg = report["avg_score"]
    avg_text = f"{avg:.1f} (из 10)" if avg is not None else "пока нет оценок"
    comment = esc(report["comment"]) if report["comment"] else "—"
    return (
        f"📊 <b>Отчёт по ученику: {esc(student['full_name'])}</b>\n"
        f"🗓 Период: {report['start']:%d.%m} – {report['end']:%d.%m.%Y}\n\n"
        f"✅ Посещено занятий: <b>{report['attended']}</b> (пропущено: {report['missed']})\n"
        f"⭐ Средний балл за ДЗ: <b>{avg_text}</b>\n"
        f"📚 Несданные ДЗ: <b>{report['unsubmitted']}</b>\n"
        f"💬 Комментарий преподавателя: {comment}"
    )


async def send_weekly_reports(bot: Bot) -> None:
    """Еженедельная рассылка: отчёт за прошедшую неделю (пн–вс) всем родителям."""
    today = now_local().date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=6)
    sent = 0
    for student in await db.list_active_students():
        parents = await db.get_parents_of_student(student)
        if not parents:
            continue
        report = await build_report(student, start, end)
        text = format_report(student, report)
        for parent in parents:
            if await safe_send(bot, parent["telegram_id"], text):
                sent += 1
        await db.save_report(student["id"], start.isoformat(), end.isoformat(), report["attended"],
                             report["avg_score"], report["unsubmitted"], report["comment"])
        if student["report_comment"]:
            await db.update_user(student["id"], report_comment=None)
    logger.info("Еженедельные отчёты отправлены: %s сообщений", sent)


async def show_report(target: Message, db_user: dict | None) -> None:
    """Отчёт за последние 7 дней по запросу."""
    if not db_user:
        await target.answer("Сначала зарегистрируйтесь: /start")
        return
    student = await db.resolve_student(db_user)
    if not student:
        await target.answer(
            f"ℹ️ Ученик «{esc(db_user['child_name'])}» пока не зарегистрирован в боте.",
            reply_markup=back_to_menu_kb())
        return
    today = now_local().date()
    report = await build_report(student, today - timedelta(days=6), today)
    await target.answer(format_report(student, report), reply_markup=back_to_menu_kb())


@router.message(Command("report"))
async def cmd_report(message: Message, db_user: dict | None) -> None:
    await show_report(message, db_user)


@router.callback_query(F.data == "menu:report")
async def cb_report(callback: CallbackQuery, db_user: dict | None) -> None:
    await callback.answer()
    await show_report(callback.message, db_user)
