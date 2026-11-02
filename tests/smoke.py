"""
Смоук-тест бота без Telegram: БД, списание занятий, поиск, конфликты, дедупликация,
резервные копии, клавиатуры и приём заявок с сайта.

Запуск (из папки проекта, база НЕ трогается — работаем на копии):
    DB_PATH=/tmp/test.db python tests/smoke.py --source school_new.db
"""
import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--source", default=os.getenv("SMOKE_SOURCE", "school_new.db"))
args, _ = parser.parse_known_args()

workdir = tempfile.mkdtemp(prefix="pv-smoke-")
db_path = os.path.join(workdir, "test.db")
if os.path.exists(args.source):
    shutil.copy2(args.source, db_path)
os.environ["DB_PATH"] = db_path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp import web
import aiohttp

from api import create_app
from backup import make_backup
from config import API_TOKEN
from database import db
from handlers.admin import student_stats_text, user_card_text
from keyboards import admin_menu as am
from keyboards.main_menu import report_kb
from schema_migration import migrate_bookings, migrate_lessons_charged

PASSED = 0


def check(cond, msg):
    global PASSED
    print(("  ✅ " if cond else "  ❌ ") + msg)
    assert cond, msg
    PASSED += 1


async def test_db():
    print("\n[1] миграции и данные")
    steps = migrate_bookings(db_path) + migrate_lessons_charged(db_path)
    print("   шаги:", steps)
    check(migrate_lessons_charged(db_path) == [], "повторная миграция идемпотентна")
    await db.connect()
    cols = [r["name"] for r in await db.fetchall("PRAGMA table_info(lessons)")]
    check("charged" in cols, "колонка lessons.charged есть")


async def test_charging():
    print("\n[2] списание занятий")
    uid = await db.execute(
        "INSERT INTO users (telegram_id, username, role, full_name, phone, balance, created_at) "
        "VALUES (990001, NULL, 'student', 'Тест Баланс', '+375290000001', 5, datetime('now'))")
    lid = await db.add_lesson(uid, "2026-12-01 10:00", None, "Тест")

    async def bal():
        return (await db.get_user_by_id(uid))["balance"]

    await db.set_lesson_status(lid, "done")
    check(await bal() == 4, "scheduled → done: -1")
    await db.set_lesson_status(lid, "done")
    check(await bal() == 4, "повторное «Проведено»: без списания")
    await db.set_lesson_status(lid, "missed")
    check(await bal() == 5, "done → missed: возврат")
    await db.set_lesson_status(lid, "cancelled")
    check(await bal() == 5, "missed → cancelled: без изменений")
    await db.execute("DELETE FROM lessons WHERE student_id = ?", (uid,))
    await db.execute("DELETE FROM users WHERE id = ?", (uid,))


async def test_search_and_stats():
    print("\n[3] поиск, фильтр долга, статистика")
    users, total = await db.search_users("Гримович", None, 0, 9)
    check(total >= 1 and users, "поиск по фамилии работает")
    users, total = await db.search_users("+375", None, 0, 9)
    check(total >= 1, "поиск по телефону работает")
    debt_users, debt_total = await db.search_users("", None, 0, 9, debt_only=True)
    check(isinstance(debt_total, int), "фильтр «с долгом» работает")
    student = await db.fetchone("SELECT * FROM users WHERE role='student' LIMIT 1")
    stats = await db.get_student_dashboard(student["id"])
    check("Статистика" in student_stats_text(student, stats), "экран статистики собирается")
    check("Баланс" in user_card_text(student, stats), "карточка ученика собирается")


async def test_conflict():
    print("\n[4] конфликт времени")
    student = await db.fetchone("SELECT * FROM users WHERE role='student' LIMIT 1")
    lid = await db.add_lesson(student["id"], "2027-01-15 18:00", None, "Слот")
    conflict = await db.has_lesson_conflict(student["id"], "2027-01-15 18:20")
    check(conflict is not None, "занятие в тот же слот находится")
    check(await db.has_lesson_conflict(student["id"], "2027-01-15 21:00") is None, "свободный слот не конфликтует")
    await db.execute("DELETE FROM lessons WHERE id = ?", (lid,))


async def test_backup():
    print("\n[5] резервная копия")
    path = make_backup(db_path, os.path.join(workdir, "backups"), keep=3)
    con = sqlite3.connect(path)
    count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    check(count >= 1, "бэкап создаётся и читается")


async def test_api():
    print("\n[6] заявка с сайта (дедупликация)")
    runner = web.AppRunner(create_app())
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 8097).start()
    payload = {"name": "Смоук Сайт", "phone": "+375297770011", "format": "group",
               "goal": "ct", "role": "parent", "subject": "math"}
    async with aiohttp.ClientSession() as session:
        async with session.post("http://127.0.0.1:8097/lead", json=payload,
                                headers={"Origin": "https://vectorp.by", "X-Api-Token": API_TOKEN}) as r:
            first = await r.json()
            check(r.status == 201, "первая заявка создаётся (201)")
        async with session.post("http://127.0.0.1:8097/lead", json=payload,
                                headers={"Origin": "https://vectorp.by", "X-Api-Token": API_TOKEN}) as r:
            second = await r.json()
            check(r.status == 200 and second.get("reused"), "повторная заявка переиспользует первую")
            check(second["booking_id"] == first["booking_id"], "id заявки тот же")
        async with session.post("http://127.0.0.1:8097/lead", json=payload,
                                headers={"Origin": "https://evil.example"}) as r:
            check(r.status == 401, "чужой Origin отклоняется")
    await runner.cleanup()


async def test_bookings():
    print("\n[8] заявка → ученик")
    booking_id = await db.add_site_booking("smoke-token-1", "Смоук Заявка", "+375295550022",
                                           "Мини-группа", "Подготовка к ЦТ", "parent",
                                           subject="Математика")
    user = await db.create_user_from_booking(booking_id)
    check(user is not None and user["telegram_id"] < 0, "ученик создан из заявки")
    check((await db.get_booking(booking_id))["status"] == "done", "заявка отмечена обработанной")
    again = await db.create_user_from_booking(booking_id)
    check(again["id"] == user["id"], "повторное создание не дублирует ученика")
    attached = await db.attach_telegram_by_phone("+375295550022", 777001, "smoke_user")
    check(attached is not None and attached["telegram_id"] == 777001, "Telegram привязан по телефону")
    await db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    await db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))


async def test_stale_bookings():
    print("\n[9] зависшие заявки")
    booking_id = await db.add_site_booking("smoke-token-2", "Старая Заявка", "+375295550033",
                                           "Индивидуально", "ЦТ", "student")
    await db.execute("UPDATE bookings SET created_at = datetime('now','-48 hours') WHERE id = ?",
                     (booking_id,))
    stale = await db.stale_site_bookings(24)
    check(any(item["id"] == booking_id for item in stale), "заявка старше 24 ч попадает в выборку")
    await db.mark_booking_reminded(booking_id)
    stale = await db.stale_site_bookings(24)
    check(all(item["id"] != booking_id for item in stale), "после напоминания не повторяется")
    await db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))


async def test_keyboards():
    print("\n[7] клавиатуры")
    users = await db.list_users_page(None, 0, 9)
    student = await db.fetchone("SELECT * FROM users WHERE role='student' LIMIT 1")
    kb = am.students_list_kb(users, 0, 1, "all", {"all": 9, "student": 7, "parent": 2, "debt": 0})
    rows = [[b.text for b in row] for row in kb.inline_keyboard]
    check(all(len(r) <= 3 for r in rows[2:]), "плитка не больше 3 в ряд")
    check(any("Поиск" in b for r in rows for b in r), "есть кнопка поиска")
    longest = max(len(b.callback_data) for row in kb.inline_keyboard for b in row if b.callback_data)
    check(longest <= 64, "callback_data ≤ 64")
    am.user_card_kb(student)
    am.student_stats_kb(student["id"])
    am.admin_main_kb(7, 6)
    report_kb()
    check(True, "карточка, статистика, меню и отчёт собираются")


async def main():
    await test_db()
    await test_charging()
    await test_search_and_stats()
    await test_conflict()
    await test_backup()
    await test_api()
    await test_bookings()
    await test_stale_bookings()
    await test_keyboards()
    await db.close()
    print(f"\nSMOKE OK · проверок пройдено: {PASSED}")


asyncio.run(main())
