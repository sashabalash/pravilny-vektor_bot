"""
Планировщик APScheduler:
  • каждую минуту — напоминания о занятиях (за 1 час и за 10 минут);
  • ежедневно в 09:00 — напоминания об оплате (за 3 дня до окончания пакета);
  • по понедельникам в 10:00 — отчёты родителям;
  • ежедневно в 03:10 — резервная копия базы (backups/, хранится 14 дней);
  • каждый час — напоминание админам о заявках с сайта, висящих больше 24 часов.
Флаги отправки хранятся в БД, поэтому напоминания не дублируются после перезапуска.
"""
import logging
from datetime import timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backup import daily_backup_job
from config import ADMIN_IDS, NOTIFY_PAYMENTS, PAYMENT_REMIND_DAYS, PAYMENT_URL, TIMEZONE
from database import db
from handlers.reports import send_weekly_reports
from keyboards.main_menu import pay_kb
from notifications import notify_family, safe_send
from utils import DB_DT_FORMAT, esc, fmt_balance, fmt_date, fmt_dt, now_local

logger = logging.getLogger(__name__)


def _lesson_text(prefix: str, lesson: dict) -> str:
    text = f"{prefix}\n🕒 {fmt_dt(lesson['lesson_dt'])}"
    if lesson["topic"]:
        text += f"\n📖 {esc(lesson['topic'])}"
    if lesson["link"]:
        text += f"\n🔗 <a href=\"{esc(lesson['link'])}\">Ссылка на занятие</a>"
    return text


async def _send_lesson_reminder(bot: Bot, lesson: dict, prefix: str) -> None:
    student = await db.get_user_by_id(lesson["student_id"])
    if not student:
        return
    await notify_family(
        bot, student,
        _lesson_text(prefix, lesson),
        parent_text=_lesson_text(f"{prefix}\n👤 {esc(student['full_name'])}", lesson),
    )


async def check_lesson_reminders(bot: Bot) -> None:
    """Напоминания за 10 минут и за 1 час до занятия."""
    try:
        now = now_local()
        now_str = now.strftime(DB_DT_FORMAT)

        # За 10 минут (отмечаем оба флага, чтобы не слать «за час» после)
        until_10 = (now + timedelta(minutes=10)).strftime(DB_DT_FORMAT)
        for lesson in await db.lessons_to_remind("reminded_10m", now_str, until_10):
            await _send_lesson_reminder(bot, lesson, "🔔 <b>Занятие начнётся через 10 минут!</b>")
            await db.mark_lesson_reminded(lesson["id"], one_hour=True, ten_min=True)

        # За 1 час
        until_60 = (now + timedelta(minutes=60)).strftime(DB_DT_FORMAT)
        for lesson in await db.lessons_to_remind("reminded_1h", now_str, until_60):
            await _send_lesson_reminder(bot, lesson, "⏰ <b>Занятие через час</b>")
            await db.mark_lesson_reminded(lesson["id"], one_hour=True)
    except Exception:
        logger.exception("Ошибка при отправке напоминаний о занятиях")


async def check_payment_reminders(bot: Bot) -> None:
    """Напоминание об оплате за 3 дня до окончания пакета."""
    try:
        today = now_local().date()
        until = today + timedelta(days=PAYMENT_REMIND_DAYS)
        for student in await db.users_for_payment_reminder(today.isoformat(), until.isoformat()):
            text = (
                "💳 <b>Напоминание об оплате</b>\n\n"
                f"Пакет занятий действует до <b>{fmt_date(student['package_end'])}</b>. "
                f"Осталось занятий: {fmt_balance(student['balance'])}.\n"
                "Чтобы не прерывать подготовку, продлите оплату заранее 🙌"
            )
            parent_text = f"👤 Ученик: {esc(student['full_name'])}\n\n{text}"
            await notify_family(bot, student, text, parent_text=parent_text, reply_markup=pay_kb(PAYMENT_URL))
            await db.mark_payment_reminded(student["id"])
            logger.info("Напоминание об оплате: %s", student["full_name"])
    except Exception:
        logger.exception("Ошибка при отправке напоминаний об оплате")


async def weekly_reports_job(bot: Bot) -> None:
    try:
        await send_weekly_reports(bot)
    except Exception:
        logger.exception("Ошибка при отправке еженедельных отчётов")


async def check_stale_bookings(bot: Bot) -> None:
    """Заявки с сайта, которые висят больше суток: одно сводное напоминание админам."""
    try:
        stale = await db.stale_site_bookings(24)
        if not stale:
            return
        lines = [f"⏳ <b>Заявок с сайта без ответа: {len(stale)}</b> (старше 24 часов)", ""]
        for booking in stale[:10]:
            lines.append(f"• №{booking['id']} · {esc(booking['name'])} · {esc(booking['phone'])}")
        if len(stale) > 10:
            lines.append(f"…и ещё {len(stale) - 10}")
        lines.append("")
        lines.append("Откройте «📝 Заявки» в админ-панели, чтобы обработать.")
        text = "\n".join(lines)
        for admin_id in ADMIN_IDS:
            await safe_send(bot, admin_id, text)
        for booking in stale:
            await db.mark_booking_reminded(booking["id"])
        logger.info("Сводное напоминание по %s заявкам отправлено", len(stale))
    except Exception:
        logger.exception("Не удалось отправить напоминания по заявкам")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Создаёт планировщик и регистрирует задачи (запуск — scheduler.start())."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        check_lesson_reminders, "interval", minutes=1, args=[bot],
        id="lesson_reminders", max_instances=1, coalesce=True)
    if NOTIFY_PAYMENTS:  # напоминания об оплате включаются в .env (NOTIFY_PAYMENTS=true)
        scheduler.add_job(
            check_payment_reminders, CronTrigger(hour=9, minute=0, timezone=TIMEZONE), args=[bot],
            id="payment_reminders", max_instances=1, coalesce=True)
    scheduler.add_job(
        weekly_reports_job, CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=TIMEZONE), args=[bot],
        id="weekly_reports", max_instances=1, coalesce=True)
    scheduler.add_job(
        daily_backup_job, CronTrigger(hour=3, minute=10, timezone=TIMEZONE),
        id="daily_backup", max_instances=1, coalesce=True)
    scheduler.add_job(
        check_stale_bookings, "interval", hours=1, args=[bot],
        id="stale_bookings", max_instances=1, coalesce=True)
    return scheduler
