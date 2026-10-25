"""
Админ-панель преподавателя (команда /admin, только для Telegram ID из ADMIN_IDS):
ученики (просмотр, блокировка, редактирование), расписание, домашние задания и их проверка,
приём оплаты, заявки на пробный урок, рассылка, статистика, управление FAQ.
"""
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import (ADMIN_IDS, DEFAULT_PACKAGE_DAYS, HW_SCORES, HW_STATUS_LABELS, NOTIFY_PAYMENTS,
                    TIMEZONE)
from database import db
from handlers.homework import send_submission_to_admin
from keyboards.admin_menu import (admin_main_kb, back_admin_kb, cancel_admin_kb,pick_teacher_kb, teacher_card_kb, admin_main_kb, back_admin_kb, bookings_kb, broadcast_audience_kb,
    broadcast_confirm_kb, broadcast_select_kb, cancel_admin_kb, confirm_delete_kb, edit_fields_kb,
    faq_admin_kb, hw_menu_kb, lesson_status_kb, lessons_list_kb, pick_student_kb, review_comment_kb,
    material_card_kb, materials_admin_kb, schedule_menu_kb, students_list_kb, submissions_list_kb,
    user_card_kb, confirm_teacher_delete_kb, pick_teacher_kb, student_stats_back_kb, teacher_card_kb,
    teachers_admin_kb)
from keyboards.main_menu import homework_notify_kb
from notifications import notify_family, safe_send
from stats_text import student_card_text
from utils import (DB_DT_FORMAT, esc, fmt_date, fmt_dt, now_local, parse_date, parse_time, safe_edit,
                   validate_amount, validate_grade, validate_int, validate_name, validate_phone,
                   validate_url)

logger = logging.getLogger(__name__)

# Публичный роутер (команда /admin с проверкой) и закрытый для не-админов
router = Router(name="admin")
admin_router = Router(name="admin_only")
admin_router.message.filter(F.from_user.id.in_(ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))
router.include_router(admin_router)

PANEL_TEXT = "🛠 <b>Админ-панель</b>\nВыберите раздел:"
TEXT_ONLY = F.text, ~F.text.startswith("/")

FIELD_PROMPTS = {
    "full_name": "Введите новое имя и фамилию:",
    "phone": "Введите телефон в формате +375XXXXXXXXX:",
    "grade": "Введите класс (например 9 или 11А):",
    "subject": "Введите предмет:",
    "child_name": "Введите имя и фамилию ребёнка:",
}


class AdminStates(StatesGroup):
    edit_value = State()
    lesson_date = State()
    lesson_time = State()
    lesson_link = State()
    hw_content = State()
    pay_lessons = State()
    pay_amount = State()
    pay_days = State()
    report_comment = State()
    review_comment = State()
    bc_content = State()
    bc_confirm = State()
    faq_question = State()
    faq_answer = State()
    mat_title = State()
    mat_file = State()
    tch_tgid = State()
    tch_name = State()
    tch_subject = State()
    tch_exp = State()
    tch_bio = State()


# ======================================================================
# Вход в панель
# ======================================================================

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return
    await state.clear()
    await message.answer(PANEL_TEXT, reply_markup=admin_main_kb())


@admin_router.callback_query(F.data == "adm:main")
async def cb_admin_main(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await safe_edit(callback.message, PANEL_TEXT, admin_main_kb())


# ======================================================================
# Ученики и родители
# ======================================================================

def user_card_text(user: dict, teacher_name: str | None = None) -> str:
    role = "🎓 Ученик" if user["role"] == "student" else "👪 Родитель"
    lines = [f"<b>{esc(user['full_name'])}</b> — {role}", f"📱 {esc(user['phone'])}"]
    if user["username"]:
        lines.append(f"✈️ @{esc(user['username'])}")
    lines.append(f"🔗 <a href=\"tg://user?id={user['telegram_id']}\">Открыть чат</a>")
    if user["role"] == "student":
        lines.append(f"🏫 Класс: {esc(user['grade'])} · 📖 {esc(user['subject'])}")
        lines.append(f"👨‍🏫 Преподаватель: {esc(teacher_name) if teacher_name else 'не назначен'}")
        lines.append(f"💳 Баланс: {user['balance']} зан. · пакет до {fmt_date(user['package_end'])}")
        if user["report_comment"]:
            lines.append(f"💬 Комментарий к отчёту: {esc(user['report_comment'])}")
    else:
        lines.append(f"👶 Ребёнок: {esc(user['child_name'])}")
    lines.append(f"📅 Регистрация: {user['created_at'][:10]}")
    lines.append("🚫 <b>Заблокирован</b>" if user["is_blocked"] else "🟢 Активен")
    return "\n".join(lines)


async def show_user_card(target: Message, user_id: int, edit: bool = False) -> None:
    user = await db.get_user_by_id(user_id)
    if not user:
        await target.answer("Пользователь не найден.", reply_markup=back_admin_kb())
        return
    teacher = await db.get_teacher(user["teacher_id"]) if user["teacher_id"] else None
    text = user_card_text(user, teacher["name"] if teacher else None)
    if edit:
        await safe_edit(target, text, user_card_kb(user))
    else:
        await target.answer(text, reply_markup=user_card_kb(user))


@admin_router.callback_query(F.data == "adm:students")
async def cb_students(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    users = await db.list_users(limit=50)
    text = (f"👥 <b>Пользователи</b> (показано: {len(users)})\nВыберите, чтобы открыть карточку:"
            if users else "Пока никто не зарегистрирован.")
    await safe_edit(callback.message, text, students_list_kb(users))


@admin_router.callback_query(F.data.startswith("adm:u:"))
async def cb_user_card(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await show_user_card(callback.message, int(callback.data.split(":")[2]), edit=True)


@admin_router.callback_query(F.data.startswith("adm:ublock:"))
async def cb_user_block(callback: CallbackQuery) -> None:
    user = await db.get_user_by_id(int(callback.data.split(":")[2]))
    if not user:
        await callback.answer("Не найден", show_alert=True)
        return
    new_state = not user["is_blocked"]
    await db.set_blocked(user["id"], new_state)
    await callback.answer("🚫 Заблокирован" if new_state else "✅ Разблокирован")
    await show_user_card(callback.message, user["id"], edit=True)


@admin_router.callback_query(F.data.startswith("adm:uedit:"))
async def cb_user_edit(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await db.get_user_by_id(int(callback.data.split(":")[2]))
    if not user:
        return
    await safe_edit(callback.message, f"✏️ Что изменить у <b>{esc(user['full_name'])}</b>?", edit_fields_kb(user))


@admin_router.callback_query(F.data.startswith("adm:ef:"))
async def cb_edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    _, _, user_id, field = callback.data.split(":")
    if field not in FIELD_PROMPTS:
        return
    await state.set_state(AdminStates.edit_value)
    await state.update_data(user_id=int(user_id), field=field)
    await callback.message.answer(FIELD_PROMPTS[field] + "\nОтмена: /cancel")


def _validate_field(field: str, raw: str) -> str | None:
    if field in ("full_name", "child_name"):
        return validate_name(raw)
    if field == "phone":
        return validate_phone(raw)
    if field == "grade":
        return validate_grade(raw)
    value = " ".join(raw.split())
    return value if 2 <= len(value) <= 40 else None


@admin_router.message(AdminStates.edit_value, *TEXT_ONLY)
async def msg_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    value = _validate_field(data["field"], message.text)
    if not value:
        await message.answer("⚠️ Некорректное значение, попробуйте ещё раз:")
        return
    await db.update_user(data["user_id"], **{data["field"]: value})
    await state.clear()
    await message.answer("✅ Данные обновлены.")
    await show_user_card(message, data["user_id"])


@admin_router.callback_query(F.data.startswith("adm:udel:"))
async def cb_user_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await db.get_user_by_id(int(callback.data.split(":")[2]))
    if not user:
        return
    await safe_edit(
        callback.message,
        f"🗑 Удалить <b>{esc(user['full_name'])}</b>? Будут удалены занятия, ДЗ и оплаты этого пользователя. "
        "Действие необратимо.",
        confirm_delete_kb(user["id"]))


@admin_router.callback_query(F.data.startswith("adm:udelok:"))
async def cb_user_delete_ok(callback: CallbackQuery) -> None:
    await callback.answer("Удалено")
    await db.delete_user(int(callback.data.split(":")[2]))
    await safe_edit(callback.message, "🗑 Пользователь удалён.", back_admin_kb())


@admin_router.callback_query(F.data.startswith("adm:ucomment:"))
async def cb_report_comment(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminStates.report_comment)
    await state.update_data(user_id=int(callback.data.split(":")[2]))
    await callback.message.answer(
        "💬 Напишите комментарий для ближайшего отчёта родителям.\nЧтобы очистить — отправьте «-». Отмена: /cancel")


@admin_router.message(AdminStates.report_comment, *TEXT_ONLY)
async def msg_report_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = message.text.strip()
    await db.update_user(data["user_id"], report_comment=None if text == "-" else text[:500])
    await state.clear()
    await message.answer("✅ Комментарий сохранён.")
    await show_user_card(message, data["user_id"])


# ======================================================================
# Выбор ученика для действий (занятие / ДЗ / оплата)
# ======================================================================

PICK_CONFIG = {
    "lesson": ("adm:ulesson", "➕ <b>Новое занятие</b>\nВыберите ученика:"),
    "hw": ("adm:uhw", "📚 <b>Выдать ДЗ</b>\nВыберите ученика:"),
    "pay": ("adm:upay", "💳 <b>Приём оплаты</b>\nВыберите ученика:"),
    "stats": ("adm:ss", "👤 <b>Статистика по ученику</b>\nВыберите ученика:"),
}


@admin_router.callback_query(F.data.startswith("adm:pick:"))
async def cb_pick_student(callback: CallbackQuery) -> None:
    await callback.answer()
    prefix, text = PICK_CONFIG[callback.data.split(":")[2]]
    students = await db.list_users(role="student", limit=50)
    if not students:
        await safe_edit(callback.message, "Пока нет ни одного ученика.", back_admin_kb())
        return
    await safe_edit(callback.message, text, pick_student_kb(students, prefix))


# ======================================================================
# Расписание
# ======================================================================

@admin_router.callback_query(F.data == "adm:schedule")
async def cb_schedule_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await safe_edit(callback.message, "📅 <b>Расписание</b>", schedule_menu_kb())


@admin_router.callback_query(F.data.startswith("adm:ulesson:"))
async def cb_lesson_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminStates.lesson_date)
    await state.update_data(student_id=int(callback.data.split(":")[2]))
    await callback.message.answer("📆 Введите дату занятия в формате <b>ДД.ММ.ГГГГ</b>\nОтмена: /cancel")


@admin_router.message(AdminStates.lesson_date, *TEXT_ONLY)
async def msg_lesson_date(message: Message, state: FSMContext) -> None:
    lesson_date = parse_date(message.text)
    if not lesson_date:
        await message.answer("⚠️ Неверная дата. Пример: <i>25.10.2026</i>")
        return
    if lesson_date < now_local().date():
        await message.answer("⚠️ Эта дата уже прошла. Введите будущую дату:")
        return
    await state.update_data(lesson_date=lesson_date.isoformat())
    await state.set_state(AdminStates.lesson_time)
    await message.answer("🕒 Введите время в формате <b>ЧЧ:ММ</b> (например 18:30):")


@admin_router.message(AdminStates.lesson_time, *TEXT_ONLY)
async def msg_lesson_time(message: Message, state: FSMContext) -> None:
    lesson_time = parse_time(message.text)
    if not lesson_time:
        await message.answer("⚠️ Неверное время. Пример: <i>18:30</i>")
        return
    data = await state.get_data()
    moment = TIMEZONE.localize(datetime.combine(datetime.fromisoformat(data["lesson_date"]).date(), lesson_time))
    if moment <= now_local():
        await message.answer("⚠️ Это время уже прошло. Введите время ещё раз:")
        return
    await state.update_data(lesson_dt=moment.strftime(DB_DT_FORMAT))
    await state.set_state(AdminStates.lesson_link)
    await message.answer("🔗 Отправьте ссылку на занятие (https://...) или «-», если ссылки пока нет:")


@admin_router.message(AdminStates.lesson_link, *TEXT_ONLY)
async def msg_lesson_link(message: Message, state: FSMContext, bot: Bot) -> None:
    raw = message.text.strip()
    link = None
    if raw != "-":
        link = validate_url(raw)
        if not link:
            await message.answer("⚠️ Нужна ссылка вида https://... или «-»")
            return
    data = await state.get_data()
    await state.clear()
    student = await db.get_user_by_id(data["student_id"])
    if not student:
        await message.answer("Ученик не найден.", reply_markup=back_admin_kb())
        return
    await db.add_lesson(student["id"], data["lesson_dt"], link, None, student["teacher_id"])
    await message.answer(
        f"✅ Занятие добавлено: <b>{esc(student['full_name'])}</b>, {fmt_dt(data['lesson_dt'])}",
        reply_markup=schedule_menu_kb())

    text = f"📅 <b>Новое занятие в расписании</b>\n🕒 {fmt_dt(data['lesson_dt'])}"
    if link:
        text += f"\n🔗 <a href=\"{esc(link)}\">Ссылка на занятие</a>"
    await notify_family(bot, student, text, parent_text=f"👤 {esc(student['full_name'])}\n{text}")


@admin_router.callback_query(F.data == "adm:lessons")
async def cb_lessons(callback: CallbackQuery) -> None:
    await callback.answer()
    since = (now_local().replace(hour=0, minute=0)).strftime(DB_DT_FORMAT)
    lessons = await db.list_scheduled_lessons(since, limit=15)
    text = ("📋 <b>Ближайшие занятия</b>\nНажмите на занятие, чтобы отметить результат:"
            if lessons else "Запланированных занятий нет.")
    await safe_edit(callback.message, text, lessons_list_kb(lessons))


@admin_router.callback_query(F.data.startswith("adm:les:"))
async def cb_lesson_card(callback: CallbackQuery) -> None:
    await callback.answer()
    lesson = await db.get_lesson(int(callback.data.split(":")[2]))
    if not lesson:
        return
    text = (f"📅 <b>Занятие №{lesson['id']}</b>\n👤 {esc(lesson['student_name'])}\n"
            f"🕒 {fmt_dt(lesson['lesson_dt'])}\n🔗 {esc(lesson['link']) if lesson['link'] else 'ссылки нет'}\n\n"
            "Отметьте результат («Проведено» спишет одно занятие с баланса):")
    await safe_edit(callback.message, text, lesson_status_kb(lesson["id"]))


@admin_router.callback_query(F.data.startswith("adm:lstat:"))
async def cb_lesson_status(callback: CallbackQuery, bot: Bot) -> None:
    _, _, lesson_id, status = callback.data.split(":")
    lesson = await db.get_lesson(int(lesson_id))
    if not lesson or lesson["status"] != "scheduled" or status not in ("done", "missed", "cancelled"):
        await callback.answer("Занятие уже отмечено", show_alert=True)
        return
    await db.set_lesson_status(lesson["id"], status)
    await callback.answer("Сохранено")
    await safe_edit(callback.message, "✅ Статус занятия обновлён.", schedule_menu_kb())
    if status == "done":
        student = await db.get_user_by_id(lesson["student_id"])
        if student:
            await safe_send(bot, student["telegram_id"],
                            f"✅ Занятие {fmt_dt(lesson['lesson_dt'])} проведено. Осталось занятий: {student['balance']}")


# ======================================================================
# Домашние задания
# ======================================================================

@admin_router.callback_query(F.data == "adm:hw")
async def cb_hw_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await safe_edit(callback.message, "📚 <b>Домашние задания</b>", hw_menu_kb())


@admin_router.callback_query(F.data.startswith("adm:uhw:"))
async def cb_hw_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminStates.hw_content)
    await state.update_data(student_id=int(callback.data.split(":")[2]))
    await callback.message.answer(
        "📚 Отправьте задание одним сообщением: текст, фото или файл (подпись станет текстом задания).\n"
        "Отмена: /cancel")


@admin_router.message(AdminStates.hw_content, F.text | F.photo | F.document)
async def msg_hw_content(message: Message, state: FSMContext, bot: Bot) -> None:
    if message.text and message.text.startswith("/"):
        await message.answer("⚠️ Неизвестная команда. Отправьте задание или нажмите /cancel")
        return
    text, file_id, file_type = message.text or message.caption, None, None
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    elif message.document:
        file_id, file_type = message.document.file_id, "document"

    data = await state.get_data()
    student = await db.get_user_by_id(data["student_id"])
    await state.clear()
    if not student:
        await message.answer("Ученик не найден.", reply_markup=back_admin_kb())
        return
    hw_id = await db.add_homework(student["id"], text, file_id, file_type)
    await message.answer(f"✅ ДЗ №{hw_id} выдано ученику <b>{esc(student['full_name'])}</b>.",
                         reply_markup=hw_menu_kb())
    await safe_send(bot, student["telegram_id"],
                    f"📚 <b>Новое домашнее задание №{hw_id}!</b>\nОткройте его и сдайте решение в боте.",
                    homework_notify_kb(hw_id))
    for parent in await db.get_parents_of_student(student):
        await safe_send(bot, parent["telegram_id"],
                        f"📚 {esc(student['full_name'])} получил(а) новое домашнее задание №{hw_id}.")


@admin_router.message(AdminStates.hw_content)
async def msg_hw_unsupported(message: Message) -> None:
    await message.answer("⚠️ Отправьте текст, фото или файл.")


@admin_router.callback_query(F.data == "adm:subs")
async def cb_submissions(callback: CallbackQuery) -> None:
    await callback.answer()
    subs = await db.list_pending_submissions()
    text = "📥 <b>Работы на проверке</b>" if subs else "✅ Непроверенных работ нет."
    await safe_edit(callback.message, text, submissions_list_kb(subs))


@admin_router.callback_query(F.data.startswith("adm:sub:"))
async def cb_submission_open(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    await send_submission_to_admin(bot, callback.from_user.id, int(callback.data.split(":")[2]))


@admin_router.callback_query(F.data.startswith("adm:rev:"))
async def cb_review_choose(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, sub_id, status = callback.data.split(":")
    sub = await db.get_submission(int(sub_id))
    if not sub or status not in HW_SCORES:
        await callback.answer("Работа не найдена", show_alert=True)
        return
    if sub["status"] != "pending":
        await callback.answer("Эта работа уже проверена", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.review_comment)
    await state.update_data(submission_id=int(sub_id), status=status)
    await callback.message.answer(
        f"Оценка: {HW_STATUS_LABELS[status]}\n💬 Напишите комментарий для ученика или нажмите кнопку:",
        reply_markup=review_comment_kb())


async def _finish_review(bot: Bot, state: FSMContext, reply_to: Message, comment: str | None) -> None:
    data = await state.get_data()
    await state.clear()
    sub = await db.get_submission(data["submission_id"])
    if not sub or sub["status"] != "pending":
        await reply_to.answer("Работа уже проверена.", reply_markup=back_admin_kb())
        return
    status = data["status"]
    await db.review_submission(sub["id"], status, HW_SCORES[status], comment)
    await reply_to.answer(f"✅ Оценка сохранена: {HW_STATUS_LABELS[status]}", reply_markup=hw_menu_kb())

    text = f"📬 <b>Результат по ДЗ №{sub['homework_id']}</b>\n{HW_STATUS_LABELS[status]}"
    if comment:
        text += f"\n💬 {esc(comment)}"
    if status == "rework":
        text += "\n\nИсправьте работу и сдайте её снова в разделе «Домашние задания»."
    await safe_send(bot, sub["student_tg"], text, homework_notify_kb(sub["homework_id"]))


@admin_router.message(AdminStates.review_comment, *TEXT_ONLY)
async def msg_review_comment(message: Message, state: FSMContext, bot: Bot) -> None:
    await _finish_review(bot, state, message, message.text.strip()[:500])


@admin_router.callback_query(AdminStates.review_comment, F.data == "adm:revskip")
async def cb_review_skip(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback.answer()
    await _finish_review(bot, state, callback.message, None)


# ======================================================================
# Оплата
# ======================================================================

@admin_router.callback_query(F.data == "adm:pay")
async def cb_pay_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    students = await db.list_users(role="student", limit=50)
    if not students:
        await safe_edit(callback.message, "Пока нет ни одного ученика.", back_admin_kb())
        return
    await safe_edit(callback.message, PICK_CONFIG["pay"][1], pick_student_kb(students, PICK_CONFIG["pay"][0]))


@admin_router.callback_query(F.data.startswith("adm:upay:"))
async def cb_pay_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminStates.pay_lessons)
    await state.update_data(student_id=int(callback.data.split(":")[2]))
    await callback.message.answer("💳 Сколько занятий в пакете? (число от 1 до 100)\nОтмена: /cancel")


@admin_router.message(AdminStates.pay_lessons, *TEXT_ONLY)
async def msg_pay_lessons(message: Message, state: FSMContext) -> None:
    lessons = validate_int(message.text, 1, 100)
    if not lessons:
        await message.answer("⚠️ Введите целое число от 1 до 100:")
        return
    await state.update_data(lessons=lessons)
    await state.set_state(AdminStates.pay_amount)
    await message.answer("💰 Сумма оплаты в BYN (например 120 или 99.50):")


@admin_router.message(AdminStates.pay_amount, *TEXT_ONLY)
async def msg_pay_amount(message: Message, state: FSMContext) -> None:
    amount = validate_amount(message.text)
    if amount is None:
        await message.answer("⚠️ Введите сумму числом, например 120 или 99.50:")
        return
    await state.update_data(amount=amount)
    await state.set_state(AdminStates.pay_days)
    await message.answer(f"📆 На сколько дней действует пакет? (1–365, обычно {DEFAULT_PACKAGE_DAYS})")


@admin_router.message(AdminStates.pay_days, *TEXT_ONLY)
async def msg_pay_days(message: Message, state: FSMContext, bot: Bot) -> None:
    days = validate_int(message.text, 1, 365)
    if not days:
        await message.answer("⚠️ Введите число дней от 1 до 365:")
        return
    data = await state.get_data()
    await state.clear()
    student = await db.get_user_by_id(data["student_id"])
    if not student:
        await message.answer("Ученик не найден.", reply_markup=back_admin_kb())
        return
    valid_until = await db.add_payment(student["id"], data["amount"], data["lessons"], days)
    await message.answer(
        f"✅ Оплата принята: <b>{esc(student['full_name'])}</b>\n"
        f"📚 +{data['lessons']} зан. · 💰 {data['amount']:g} BYN · 📆 до {fmt_date(valid_until)}",
        reply_markup=back_admin_kb())
    # Оплата записана в БД и попадёт в статистику; ученику и родителям пишем только если включено в .env
    if NOTIFY_PAYMENTS:
        text = (f"✅ <b>Оплата получена, спасибо!</b>\n📚 Добавлено занятий: {data['lessons']}\n"
                f"📆 Пакет действует до {fmt_date(valid_until)}")
        await notify_family(bot, student, text, parent_text=f"👤 {esc(student['full_name'])}\n{text}")


# ======================================================================
# Заявки на пробный урок
# ======================================================================

@admin_router.callback_query(F.data == "adm:bk")
async def cb_bookings(callback: CallbackQuery) -> None:
    await callback.answer()
    bookings = await db.list_bookings("new")
    if not bookings:
        await safe_edit(callback.message, "✅ Новых заявок нет.", back_admin_kb())
        return
    lines = ["📝 <b>Новые заявки</b> (нажмите кнопку, чтобы отметить обработанной):\n"]
    for item in bookings:
        lines.append(
            f"<b>№{item['id']}</b> · {esc(item['name'])} · {esc(item['phone'])}\n"
            f"   {esc(item['lesson_format'])} · {esc(item['goal'])} · {item['created_at'][:16]}")
    await safe_edit(callback.message, "\n".join(lines), bookings_kb(bookings))


@admin_router.callback_query(F.data.startswith("adm:bkdone:"))
async def cb_booking_done(callback: CallbackQuery) -> None:
    await db.set_booking_status(int(callback.data.split(":")[2]), "done")
    await callback.answer("✅ Отмечено обработанной")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass


# ======================================================================
# Рассылка
# ======================================================================

@admin_router.callback_query(F.data == "adm:bc")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await safe_edit(callback.message, "📢 <b>Рассылка</b>\nКому отправить?", broadcast_audience_kb())


@admin_router.callback_query(F.data.startswith("adm:bca:"))
async def cb_broadcast_audience(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    audience = callback.data.split(":")[2]
    await state.update_data(audience=audience, selected=[])
    if audience == "select":
        users = await db.list_users(limit=50)
        await safe_edit(callback.message, "☑️ Отметьте получателей:", broadcast_select_kb(users, set()))
        return
    await state.set_state(AdminStates.bc_content)
    await safe_edit(callback.message,
                    "✍️ Отправьте сообщение для рассылки (текст, фото или файл — перешлю как есть).\n"
                    "Отмена: /cancel", cancel_admin_kb())


@admin_router.callback_query(F.data.startswith("adm:bct:"))
async def cb_broadcast_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected ^= {user_id}
    await state.update_data(selected=list(selected))
    users = await db.list_users(limit=50)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=broadcast_select_kb(users, selected))


@admin_router.callback_query(F.data == "adm:bcnext")
async def cb_broadcast_next(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("selected"):
        await callback.answer("Выберите хотя бы одного получателя", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.bc_content)
    await safe_edit(callback.message,
                    "✍️ Отправьте сообщение для рассылки (текст, фото или файл).\nОтмена: /cancel",
                    cancel_admin_kb())


@admin_router.message(AdminStates.bc_content)
async def msg_broadcast_content(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/"):
        await message.answer("⚠️ Неизвестная команда. Отправьте текст рассылки или нажмите /cancel")
        return
    data = await state.get_data()
    recipients = await db.get_recipients(data["audience"], data.get("selected"))
    if not recipients:
        await state.clear()
        await message.answer("⚠️ Нет получателей для рассылки.", reply_markup=back_admin_kb())
        return
    await state.update_data(src_chat=message.chat.id, src_message=message.message_id)
    await state.set_state(AdminStates.bc_confirm)
    await message.answer(f"📨 Получателей: <b>{len(recipients)}</b>. Отправить это сообщение?",
                         reply_markup=broadcast_confirm_kb())


@admin_router.callback_query(AdminStates.bc_confirm, F.data == "adm:bcok")
async def cb_broadcast_send(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback.answer()
    data = await state.get_data()
    await state.clear()
    recipients = await db.get_recipients(data["audience"], data.get("selected"))
    await safe_edit(callback.message, f"⏳ Отправляю… (получателей: {len(recipients)})")
    sent = failed = 0
    for telegram_id in recipients:
        try:
            await bot.copy_message(telegram_id, data["src_chat"], data["src_message"])
            sent += 1
        except TelegramAPIError as exc:
            failed += 1
            logger.warning("Рассылка: не доставлено %s (%s)", telegram_id, exc)
        await asyncio.sleep(0.05)  # ограничение Telegram по частоте
    logger.info("Рассылка завершена: доставлено %s, ошибок %s", sent, failed)
    await callback.message.answer(f"✅ Рассылка завершена.\nДоставлено: {sent}\nНе доставлено: {failed}",
                                  reply_markup=back_admin_kb())


@admin_router.callback_query(F.data == "adm:bcno")
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Отменено")
    await state.clear()
    await safe_edit(callback.message, "↩️ Рассылка отменена.", back_admin_kb())


# ======================================================================
# Статистика
# ======================================================================

MONTHS_RU = ("январь", "февраль", "март", "апрель", "май", "июнь",
             "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


def _month_label(year_month: str) -> str:
    """'2026-10' -> 'октябрь 2026'."""
    year, month = year_month.split("-")
    return f"{MONTHS_RU[int(month) - 1]} {year}"


@admin_router.callback_query(F.data == "adm:stats")
async def cb_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    s = await db.get_stats()
    months = await db.payments_by_month(12)
    if months:
        month_lines = "\n".join(
            f"• {_month_label(m['month'])}: {m['cnt']} оплат · {m['total']:g} BYN · {m['lessons']} зан."
            for m in months)
    else:
        month_lines = "пока нет оплат"
    text = (
        "📊 <b>Общая статистика школы</b>\n\n"
        f"🎓 Учеников: <b>{s['students']}</b>\n"
        f"👨‍🏫 Преподавателей: <b>{s['teachers']}</b>\n"
        f"👪 Родителей: <b>{s['parents']}</b>\n"
        f"🚫 Заблокировано: {s['blocked']}\n\n"
        f"💳 Оплат всего: <b>{s['payments_count']}</b> на сумму <b>{s['payments_sum']:g} BYN</b>\n"
        f"\n📆 <b>Оплаты по месяцам</b>\n{month_lines}\n\n"
        f"✅ Проведено занятий: {s['lessons_done']}\n\n"
        f"📚 Сдач ДЗ всего: <b>{s['submissions_total']}</b> (на проверке: {s['submissions_pending']})\n"
        f"📝 Новых заявок на пробный урок: {s['bookings_new']}"
    )
    await safe_edit(callback.message, text, back_admin_kb())


# ======================================================================
# FAQ
# ======================================================================

@admin_router.callback_query(F.data == "adm:faq")
async def cb_faq_admin(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    items = await db.list_faq()
    await safe_edit(callback.message,
                    "❓ <b>Управление FAQ</b>\nНажмите на вопрос, чтобы удалить его, или добавьте новый:",
                    faq_admin_kb(items))


@admin_router.callback_query(F.data.startswith("adm:faqdel:"))
async def cb_faq_delete(callback: CallbackQuery) -> None:
    await db.delete_faq(int(callback.data.split(":")[2]))
    await callback.answer("🗑 Удалено")
    items = await db.list_faq()
    await safe_edit(callback.message, "❓ <b>Управление FAQ</b>", faq_admin_kb(items))


@admin_router.callback_query(F.data == "adm:faqadd")
async def cb_faq_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminStates.faq_question)
    await callback.message.answer("❓ Введите текст вопроса (до 100 символов):\nОтмена: /cancel")


@admin_router.message(AdminStates.faq_question, *TEXT_ONLY)
async def msg_faq_question(message: Message, state: FSMContext) -> None:
    question = " ".join(message.text.split())
    if not 3 <= len(question) <= 100:
        await message.answer("⚠️ Вопрос должен быть от 3 до 100 символов:")
        return
    await state.update_data(question=question)
    await state.set_state(AdminStates.faq_answer)
    await message.answer("💬 Теперь введите ответ на этот вопрос:")


@admin_router.message(AdminStates.faq_answer, *TEXT_ONLY)
async def msg_faq_answer(message: Message, state: FSMContext) -> None:
    answer = message.text.strip()
    if not 3 <= len(answer) <= 3000:
        await message.answer("⚠️ Ответ должен быть от 3 до 3000 символов:")
        return
    data = await state.get_data()
    await state.clear()
    await db.add_faq(data["question"], answer)
    items = await db.list_faq()
    await message.answer("✅ Вопрос добавлен.", reply_markup=faq_admin_kb(items))


# ======================================================================
# Материалы (чек-листы, PDF)
# ======================================================================

def _material_link(bot_username: str, material_id: int) -> str:
    return f"https://t.me/{bot_username}?start=mat_{material_id}"


@admin_router.callback_query(F.data == "adm:mat")
async def cb_materials_admin(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    items = await db.list_materials()
    text = ("📎 <b>Материалы</b>\nНажмите на материал, чтобы получить ссылку для канала или удалить его:"
            if items else "📎 <b>Материалы</b>\nПока ничего нет. Добавьте первый чек-лист:")
    await safe_edit(callback.message, text, materials_admin_kb(items))


@admin_router.callback_query(F.data.startswith("adm:mat:"))
async def cb_material_card(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    material = await db.get_material(int(callback.data.split(":")[2]))
    if not material:
        return
    me = await bot.me()
    description = esc(material["description"]) if material["description"] else "<i>без описания</i>"
    text = (f"📎 <b>{esc(material['title'])}</b>\n\n{description}\n\n"
            f"🔗 Ссылка для поста в канале:\n<code>{_material_link(me.username, material['id'])}</code>")
    await safe_edit(callback.message, text, material_card_kb(material["id"]))


@admin_router.callback_query(F.data.startswith("adm:matdel:"))
async def cb_material_delete(callback: CallbackQuery) -> None:
    await db.delete_material(int(callback.data.split(":")[2]))
    await callback.answer("🗑 Удалено")
    items = await db.list_materials()
    await safe_edit(callback.message, "📎 <b>Материалы</b>", materials_admin_kb(items))


@admin_router.callback_query(F.data == "adm:matadd")
async def cb_material_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminStates.mat_title)
    await callback.message.answer(
        "📎 Введите название материала (до 80 символов), например: "
        "<i>Чек-лист: 10 ошибок в вычислениях</i>\nОтмена: /cancel")


@admin_router.message(AdminStates.mat_title, *TEXT_ONLY)
async def msg_material_title(message: Message, state: FSMContext) -> None:
    title = " ".join(message.text.split())
    if not 3 <= len(title) <= 80:
        await message.answer("⚠️ Название должно быть от 3 до 80 символов:")
        return
    await state.update_data(title=title)
    await state.set_state(AdminStates.mat_file)
    await message.answer(
        "📄 Теперь отправьте файл (PDF) или картинку.\n"
        "Подпись к файлу станет описанием материала (до 700 символов, можно без подписи).")


@admin_router.message(AdminStates.mat_file, F.document | F.photo)
async def msg_material_file(message: Message, state: FSMContext, bot: Bot) -> None:
    description = (message.caption or "").strip()
    if len(description) > 700:
        await message.answer("⚠️ Описание длиннее 700 символов. Сократите подпись и отправьте файл снова:")
        return
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    else:
        file_id, file_type = message.document.file_id, "document"
    data = await state.get_data()
    await state.clear()
    material_id = await db.add_material(data["title"], description or None, file_id, file_type)
    me = await bot.me()
    items = await db.list_materials()
    await message.answer(
        "✅ Материал добавлен.\n\n🔗 Ссылка для поста в канале (по ней человек сразу получит файл):\n"
        f"<code>{_material_link(me.username, material_id)}</code>",
        reply_markup=materials_admin_kb(items))


@admin_router.message(AdminStates.mat_file)
async def msg_material_file_unsupported(message: Message) -> None:
    await message.answer("⚠️ Отправьте PDF-файл или картинку. Отмена: /cancel")


# ======================================================================
# Статистика по ученику (любой ученик школы)
# ======================================================================

@admin_router.callback_query(F.data.startswith("adm:ss:"))
async def cb_student_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    student_id = int(callback.data.split(":")[2])
    text = await student_card_text(student_id, with_payments=True)
    if text is None:
        await callback.message.answer("Ученик не найден.", reply_markup=back_admin_kb())
        return
    await safe_edit(callback.message, text, student_stats_back_kb(student_id))


# ======================================================================
# Преподаватели: список, добавление по Telegram ID, удаление, назначение ученикам
# ======================================================================

@admin_router.callback_query(F.data == "adm:tch")
async def cb_teachers(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    items = await db.list_teachers()
    text = ("👨‍🏫 <b>Преподаватели</b>\nНажмите на преподавателя, чтобы открыть карточку:" if items
            else "👨‍🏫 <b>Преподаватели</b>\nПока никого нет. Добавьте первого:")
    await safe_edit(callback.message, text, teachers_admin_kb(items))


@admin_router.callback_query(F.data.startswith("adm:tch:"))
async def cb_teacher_card(callback: CallbackQuery) -> None:
    await callback.answer()
    teacher = await db.get_teacher(int(callback.data.split(":")[2]))
    if not teacher:
        return
    students = await db.list_students_of_teacher(teacher["id"])
    text = (
        f"👨‍🏫 <b>{esc(teacher['name'])}</b>\n"
        f"📖 Предмет: {esc(teacher['subject']) if teacher['subject'] else '—'}\n"
        f"🎓 Стаж: {teacher['experience_years']} лет\n"
        f"🆔 Telegram ID: <code>{teacher['telegram_id']}</code>\n"
        f"👥 Учеников: {len(students)}\n"
        f"📝 О себе: {esc(teacher['bio']) if teacher['bio'] else '—'}")
    await safe_edit(callback.message, text, teacher_card_kb(teacher["id"]))


@admin_router.callback_query(F.data == "adm:tchadd")
async def cb_teacher_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminStates.tch_tgid)
    await callback.message.answer(
        "👨‍🏫 Введите <b>Telegram ID</b> преподавателя (число). Узнать его можно у @userinfobot.\n"
        "По этому ID преподаватель войдёт в свою панель.\nОтмена: /cancel")


@admin_router.message(AdminStates.tch_tgid, *TEXT_ONLY)
async def msg_teacher_tgid(message: Message, state: FSMContext) -> None:
    telegram_id = validate_int(message.text, 1, 10 ** 13)
    if not telegram_id:
        await message.answer("⚠️ Telegram ID — это число. Попробуйте ещё раз:")
        return
    if await db.get_teacher_by_telegram(telegram_id):
        await message.answer("⚠️ Преподаватель с таким ID уже добавлен. Введите другой ID или /cancel:")
        return
    await state.update_data(telegram_id=telegram_id)
    await state.set_state(AdminStates.tch_name)
    await message.answer("✍️ Введите имя и фамилию преподавателя:")


@admin_router.message(AdminStates.tch_name, *TEXT_ONLY)
async def msg_teacher_name(message: Message, state: FSMContext) -> None:
    name = validate_name(message.text)
    if not name:
        await message.answer("⚠️ Введите имя и фамилию буквами, например: <i>Александр Балаш</i>")
        return
    await state.update_data(name=name)
    await state.set_state(AdminStates.tch_subject)
    await message.answer("📖 Какой предмет ведёт преподаватель? (например: Математика)")


@admin_router.message(AdminStates.tch_subject, *TEXT_ONLY)
async def msg_teacher_subject(message: Message, state: FSMContext) -> None:
    subject = " ".join(message.text.split())
    if not 2 <= len(subject) <= 40:
        await message.answer("⚠️ Название предмета — от 2 до 40 символов:")
        return
    await state.update_data(subject=subject)
    await state.set_state(AdminStates.tch_exp)
    await message.answer("🎓 Стаж преподавания в годах (число от 0 до 60):")


@admin_router.message(AdminStates.tch_exp, *TEXT_ONLY)
async def msg_teacher_exp(message: Message, state: FSMContext) -> None:
    years = validate_int(message.text, 0, 60)
    if years is None:
        await message.answer("⚠️ Введите целое число от 0 до 60:")
        return
    await state.update_data(experience_years=years)
    await state.set_state(AdminStates.tch_bio)
    await message.answer("📝 Коротко о преподавателе (до 500 символов) или «-», чтобы пропустить:")


@admin_router.message(AdminStates.tch_bio, *TEXT_ONLY)
async def msg_teacher_bio(message: Message, state: FSMContext, bot: Bot) -> None:
    bio = message.text.strip()
    if len(bio) > 500:
        await message.answer("⚠️ Слишком длинно (максимум 500 символов). Сократите текст:")
        return
    data = await state.get_data()
    await state.clear()
    teacher_id = await db.add_teacher(
        data["telegram_id"], data["name"], data["subject"], data["experience_years"],
        None if bio == "-" else bio)
    items = await db.list_teachers()
    await message.answer(f"✅ Преподаватель <b>{esc(data['name'])}</b> добавлен.", reply_markup=teachers_admin_kb(items))
    delivered = await safe_send(
        bot, data["telegram_id"],
        "👨‍🏫 <b>Вас добавили преподавателем школы «Правильный Вектор».</b>\n"
        "Откройте панель командой /teacher.")
    if not delivered:
        await message.answer("ℹ️ Преподаватель ещё не запускал бота, поэтому уведомление не доставлено. "
                             "Попросите его открыть бота и отправить /start, затем /teacher.")


@admin_router.callback_query(F.data.startswith("adm:tchdel:"))
async def cb_teacher_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    teacher = await db.get_teacher(int(callback.data.split(":")[2]))
    if not teacher:
        return
    await safe_edit(
        callback.message,
        f"🗑 Удалить преподавателя <b>{esc(teacher['name'])}</b>? Его ученики останутся в базе, "
        "но привязка к преподавателю снимется.", confirm_teacher_delete_kb(teacher["id"]))


@admin_router.callback_query(F.data.startswith("adm:tchdelok:"))
async def cb_teacher_delete_ok(callback: CallbackQuery) -> None:
    await db.delete_teacher(int(callback.data.split(":")[2]))
    await callback.answer("Удалено")
    items = await db.list_teachers()
    await safe_edit(callback.message, "👨‍🏫 <b>Преподаватели</b>", teachers_admin_kb(items))


@admin_router.callback_query(F.data.startswith("adm:uteach:"))
async def cb_student_teacher_pick(callback: CallbackQuery) -> None:
    student_id = int(callback.data.split(":")[2])
    teachers = await db.list_teachers()
    if not teachers:
        await callback.answer("Сначала добавьте преподавателей (раздел «Преподаватели»)", show_alert=True)
        return
    await callback.answer()
    await safe_edit(callback.message, "👨‍🏫 Выберите преподавателя для ученика:", pick_teacher_kb(teachers, student_id))


@admin_router.callback_query(F.data.startswith("adm:setteach:"))
async def cb_student_teacher_set(callback: CallbackQuery, bot: Bot) -> None:
    _, _, student_id, teacher_id = callback.data.split(":")
    student = await db.get_user_by_id(int(student_id))
    if not student or student["role"] != "student":
        await callback.answer("Ученик не найден", show_alert=True)
        return
    teacher = await db.get_teacher(int(teacher_id)) if int(teacher_id) else None
    await db.set_student_teacher(student["id"], teacher["id"] if teacher else None)
    await callback.answer("Сохранено")
    await show_user_card(callback.message, student["id"], edit=True)
    if teacher:
        await safe_send(bot, teacher["telegram_id"],
                        f"🎓 Вам назначен ученик: <b>{esc(student['full_name'])}</b> "
                        f"({esc(student['grade'])} кл., {esc(student['subject'])}).")
