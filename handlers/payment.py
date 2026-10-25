"""
Оплата: команда /balance и кнопка «Баланс занятий» — остаток занятий,
срок действия пакета, последние оплаты и ссылка на оплату (заглушка).
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import PAYMENT_REMIND_DAYS, PAYMENT_URL
from database import db
from keyboards.main_menu import pay_kb
from utils import esc, fmt_date, now_local

router = Router(name="payment")


async def show_balance(target: Message, db_user: dict | None) -> None:
    if not db_user:
        await target.answer("Сначала зарегистрируйтесь: /start")
        return
    student = await db.resolve_student(db_user)
    if not student:
        await target.answer(
            f"ℹ️ Ученик «{esc(db_user['child_name'])}» пока не зарегистрирован в боте.",
            reply_markup=pay_kb(PAYMENT_URL))
        return

    lines = [
        f"💳 <b>Баланс занятий: {esc(student['full_name'])}</b>\n",
        f"📚 Осталось занятий: <b>{student['balance']}</b>",
        f"📆 Пакет действует до: <b>{fmt_date(student['package_end'])}</b>",
    ]
    if student["package_end"]:
        days_left = (now_local().date().fromisoformat(student["package_end"]) - now_local().date()).days
        if days_left < 0:
            lines.append("\n⚠️ Срок действия пакета истёк. Пожалуйста, продлите оплату.")
        elif days_left <= PAYMENT_REMIND_DAYS:
            lines.append(f"\n⏰ До окончания пакета осталось дней: {days_left}. Самое время продлить!")
    elif student["balance"] == 0:
        lines.append("\nℹ️ Оплаченных занятий пока нет.")

    payments = await db.list_payments(student["id"], limit=3)
    if payments:
        lines.append("\n🧾 <b>Последние оплаты:</b>")
        for payment in payments:
            lines.append(f"• {payment['paid_at'][:10]} — {payment['lessons_count']} зан., {payment['amount']:g} BYN")

    await target.answer("\n".join(lines), reply_markup=pay_kb(PAYMENT_URL))


@router.message(Command("balance"))
async def cmd_balance(message: Message, db_user: dict | None) -> None:
    await show_balance(message, db_user)


@router.callback_query(F.data == "menu:balance")
async def cb_balance(callback: CallbackQuery, db_user: dict | None) -> None:
    await callback.answer()
    await show_balance(callback.message, db_user)
