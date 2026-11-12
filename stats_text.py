"""Текст карточки успеваемости ученика (используется в панели преподавателя)."""
from database import db
from utils import DB_DT_FORMAT, esc, fmt_balance, fmt_date, fmt_dt, now_local


async def student_card_text(student_id: int, with_payments: bool = True) -> str:
    """Карточка ученика: занятия, посещаемость, домашние задания и (по желанию) оплаты.

    with_payments=False — для преподавателя: суммы оплат ему не показываются.
    """
    student = await db.get_user_by_id(student_id)
    if not student:
        return "Ученик не найден."
    stats = await db.get_student_stats(student_id)

    lessons = stats["lessons"]
    done = lessons.get("done", 0)
    planned = lessons.get("scheduled", 0)
    missed = lessons.get("missed", 0)
    cancelled = lessons.get("cancelled", 0)
    held = done + missed
    attendance = round(done / held * 100) if held else None

    meta = []
    if student["grade"]:
        meta.append(f"🏫 {esc(student['grade'])} класс")
    if student["subject"]:
        meta.append(esc(student["subject"]))
    lines = [f"📊 <b>{esc(student['full_name'])}</b>"]
    if meta:
        lines.append(" · ".join(meta))
    lines.append(f"📦 Осталось занятий: {fmt_balance(student['balance'])}")
    lines.append("")

    lines.append("📅 <b>Занятия</b>")
    lines.append(f"• проведено {done} · запланировано {planned}")
    if missed or cancelled:
        lines.append(f"• пропущено {missed} · отменено {cancelled}")
    if attendance is not None:
        lines.append(f"• посещаемость {attendance}%")
    upcoming = await db.get_upcoming_lessons(student_id, now_local().strftime(DB_DT_FORMAT), limit=1)
    if upcoming:
        lines.append(f"• ближайшее: {fmt_dt(upcoming[0]['lesson_dt'])}")
    lines.append("")

    lines.append("📚 <b>Домашние задания</b>")
    lines.append(f"• выдано {stats['hw_total']} · сдано {stats['hw_submitted']} · не сдано {stats['hw_unsubmitted']}")
    if stats["hw_pending"]:
        lines.append(f"• на проверке {stats['hw_pending']}")
    if stats["avg_score"] is not None:
        lines.append(f"• средний балл {stats['avg_score']:.1f} / 10")
    else:
        lines.append("• средний балл: оценок пока нет")

    if with_payments:
        lines.append("")
        lines.append("💳 <b>Оплаты</b>")
        if stats["payments_count"]:
            lines.append(f"• {stats['payments_count']} на {stats['payments_sum']:g} BYN")
            for payment in stats["last_payments"]:
                lines.append(f"  – {fmt_date(str(payment['paid_at'])[:10])}: {payment['amount']:g} BYN")
        else:
            lines.append("• оплат пока нет")
    return "\n".join(lines)
