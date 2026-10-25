"""
Работа с базой данных SQLite через aiosqlite.
Содержит схему таблиц и все запросы. Для перехода на PostgreSQL достаточно
заменить реализацию методов этого класса (интерфейс для хендлеров останется прежним).
"""
import logging
from datetime import date, datetime, timedelta

import aiosqlite

from config import DB_PATH, TIMEZONE
from schema import DEFAULT_FAQ, SCHEMA, SCHEMA_VERSION
from utils import normalize_name, now_local, now_ts

logger = logging.getLogger(__name__)


class SchemaVersionError(RuntimeError):
    """База данных старой версии: нужно выполнить migration.py."""

_USER_EDITABLE = {"full_name", "phone", "grade", "subject", "child_name", "report_comment"}


class Database:
    """Тонкая асинхронная обёртка над SQLite."""

    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    # ---------- Подключение ----------

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON")

        # Защита от запуска на базе старой структуры: сначала нужна миграция
        version = await self._scalar("PRAGMA user_version") or 0
        has_users = await self._scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'users'")
        if has_users and version < SCHEMA_VERSION:
            await self.conn.close()
            self.conn = None
            raise SchemaVersionError(
                f"База {self.path} создана старой версией бота. Выполните миграцию: "
                "python migration.py --old <старая_база> --new school_new.db, "
                "затем укажите DB_PATH=school_new.db в .env")

        await self.conn.executescript(SCHEMA)
        await self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        row = await self.fetchone("SELECT COUNT(*) AS c FROM faq")
        if row and row["c"] == 0:
            await self.conn.executemany("INSERT INTO faq (question, answer) VALUES (?, ?)", DEFAULT_FAQ)
        await self.conn.commit()
        logger.info("База данных подключена: %s", self.path)

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    # ---------- Базовые операции ----------

    async def execute(self, sql: str, params: tuple = ()) -> int:
        """Выполняет запрос с коммитом, возвращает lastrowid."""
        cursor = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cursor.lastrowid

    async def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        cursor = await self.conn.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def _scalar(self, sql: str, params: tuple = ()):
        row = await self.fetchone(sql, params)
        return next(iter(row.values())) if row else None

    # ---------- Пользователи ----------

    async def add_user(self, telegram_id: int, username: str | None, role: str, full_name: str,
                       phone: str, grade: str | None = None, subject: str | None = None,
                       child_name: str | None = None) -> int:
        return await self.execute(
            "INSERT INTO users (telegram_id, username, role, full_name, phone, grade, subject, "
            "child_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (telegram_id, username, role, full_name, phone, grade, subject, child_name, now_ts()),
        )

    async def get_user(self, telegram_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))

    async def get_user_by_id(self, user_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

    async def update_user(self, user_id: int, **fields) -> None:
        fields = {k: v for k, v in fields.items() if k in _USER_EDITABLE}
        if not fields:
            return
        assignments = ", ".join(f"{name} = ?" for name in fields)
        await self.execute(f"UPDATE users SET {assignments} WHERE id = ?", (*fields.values(), user_id))

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        await self.execute("UPDATE users SET is_blocked = ? WHERE id = ?", (int(blocked), user_id))

    async def delete_user(self, user_id: int) -> None:
        await self.execute("DELETE FROM users WHERE id = ?", (user_id,))

    async def list_users(self, role: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM users"
        params: list = []
        if role:
            sql += " WHERE role = ?"
            params.append(role)
        else:
            sql += " WHERE role != 'admin'"
        sql += " ORDER BY CASE role WHEN 'student' THEN 0 ELSE 1 END, full_name COLLATE NOCASE LIMIT ?"
        params.append(limit)
        return await self.fetchall(sql, tuple(params))

    async def list_active_students(self) -> list[dict]:
        return await self.fetchall("SELECT * FROM users WHERE role = 'student' AND is_blocked = 0")

    async def find_student_by_child_name(self, child_name: str) -> dict | None:
        """Ищет ученика по имени ребёнка (сравнение в Python: SQLite не умеет регистр кириллицы)."""
        target = normalize_name(child_name)
        for student in await self.fetchall("SELECT * FROM users WHERE role = 'student'"):
            if normalize_name(student["full_name"]) == target:
                return student
        return None

    async def get_parents_of_student(self, student: dict) -> list[dict]:
        target = normalize_name(student["full_name"])
        parents = await self.fetchall("SELECT * FROM users WHERE role = 'parent' AND is_blocked = 0")
        return [p for p in parents if normalize_name(p["child_name"]) == target]

    async def resolve_student(self, user: dict | None) -> dict | None:
        """Для ученика — он сам, для родителя — привязанный ребёнок."""
        if not user:
            return None
        if user["role"] == "student":
            return user
        if user["role"] == "parent":
            return await self.find_student_by_child_name(user["child_name"] or "")
        return None

    async def get_recipients(self, audience: str, ids: list[int] | None = None) -> list[int]:
        """Telegram ID получателей рассылки: all / students / parents / select."""
        if audience == "select":
            if not ids:
                return []
            marks = ",".join("?" for _ in ids)
            rows = await self.fetchall(
                f"SELECT telegram_id FROM users WHERE is_blocked = 0 AND id IN ({marks})", tuple(ids))
        elif audience in ("students", "parents"):
            role = "student" if audience == "students" else "parent"
            rows = await self.fetchall(
                "SELECT telegram_id FROM users WHERE is_blocked = 0 AND role = ?", (role,))
        else:
            rows = await self.fetchall(
                "SELECT telegram_id FROM users WHERE is_blocked = 0 AND role != 'admin'")
        return [row["telegram_id"] for row in rows]

    # ---------- Заявки на пробный урок ----------

    async def add_booking(self, telegram_id: int, username: str | None, name: str, phone: str,
                          lesson_format: str, goal: str, user_role: str | None,
                          subject: str | None = None) -> int:
        return await self.execute(
            "INSERT INTO bookings (telegram_id, username, name, phone, lesson_format, goal, user_role, "
            "subject, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (telegram_id, username, name, phone, lesson_format, goal, user_role, subject, now_ts()),
        )

    async def get_booking(self, booking_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM bookings WHERE id = ?", (booking_id,))

    async def list_bookings(self, status: str = "new", limit: int = 20) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM bookings WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit))
    
    async def add_site_booking(
        self,
        token: str,
        name: str,
        phone: str,
        lesson_format: str,
        goal: str,
        user_role: str,
        subject: str | None = None,
    ) -> int:
        """Заявка с сайта: status='pending', source='site', telegram_id=0, username=NULL.

        lesson_format / goal / subject — русские подписи из config (как в заявках из бота).
        Бросает sqlite3.IntegrityError, если токен уже занят (уникальный индекс idx_bookings_token).
        """
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            cur = await conn.execute(
                """
                INSERT INTO bookings
                    (telegram_id, username, name, phone, lesson_format, goal,
                     subject, user_role, status, source, token, created_at)
                VALUES (0, NULL, ?, ?, ?, ?, ?, ?, 'pending', 'site', ?, datetime('now'))
                """,
                (name, phone, lesson_format, goal, subject, user_role, token),
            )
            await conn.commit()
            return cur.lastrowid

    async def get_booking_by_token(self, token: str) -> dict | None:
        """Только необработанная (pending) заявка — повторный переход по ссылке вернёт None."""
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM bookings WHERE token = ? AND status = 'pending'", (token,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def get_pending_site_booking(self, booking_id: int) -> dict | None:
        """Заявка с сайта, ожидающая подтверждения, по id (для кнопок site:ok / site:edit)."""
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM bookings WHERE id = ? AND source = 'site' AND status = 'pending'",
                (booking_id,),
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def confirm_booking(
        self, booking_id: int, telegram_id: int, username: str | None = None
    ) -> bool:
        """pending → new и привязка к Telegram-аккаунту.

        WHERE status='pending' делает подтверждение одноразовым: повторное нажатие вернёт False.
        """
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            cur = await conn.execute(
                """
                UPDATE bookings
                   SET status = 'new',
                       telegram_id = ?,
                       username = COALESCE(?, username)
                 WHERE id = ? AND status = 'pending'
                """,
                (telegram_id, username, booking_id),
            )
            await conn.commit()
            return cur.rowcount > 0

    async def update_site_booking(self, booking_id: int, goal: str, lesson_format: str) -> bool:
        """Ветка «✏️ Изменить»: правим цель и формат в ещё не подтверждённой заявке."""
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            cur = await conn.execute(
                "UPDATE bookings SET goal = ?, lesson_format = ? WHERE id = ? AND status = 'pending'",
                (goal, lesson_format, booking_id),
            )
            await conn.commit()
            return cur.rowcount > 0


    async def set_booking_status(self, booking_id: int, status: str) -> None:
        await self.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))

    # ---------- Занятия ----------

    async def add_lesson(self, student_id: int, lesson_dt: str, link: str | None, topic: str | None = None,
                         teacher_id: int | None = None) -> int:
        return await self.execute(
            "INSERT INTO lessons (student_id, lesson_dt, link, topic, teacher_id) VALUES (?, ?, ?, ?, ?)",
            (student_id, lesson_dt, link, topic, teacher_id),
        )

    async def get_lesson(self, lesson_id: int) -> dict | None:
        return await self.fetchone(
            "SELECT l.*, u.full_name AS student_name, u.telegram_id AS student_tg "
            "FROM lessons l JOIN users u ON u.id = l.student_id WHERE l.id = ?", (lesson_id,))

    async def get_upcoming_lessons(self, student_id: int, now_str: str, limit: int = 10) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM lessons WHERE student_id = ? AND status = 'scheduled' AND lesson_dt >= ? "
            "ORDER BY lesson_dt LIMIT ?", (student_id, now_str, limit))

    async def list_scheduled_lessons(self, since_str: str, limit: int = 15) -> list[dict]:
        return await self.fetchall(
            "SELECT l.*, u.full_name AS student_name FROM lessons l JOIN users u ON u.id = l.student_id "
            "WHERE l.status = 'scheduled' AND l.lesson_dt >= ? ORDER BY l.lesson_dt LIMIT ?",
            (since_str, limit))

    async def set_lesson_status(self, lesson_id: int, status: str) -> None:
        """Меняет статус занятия; при «проведено» списывает одно занятие с баланса."""
        lesson = await self.fetchone("SELECT student_id FROM lessons WHERE id = ?", (lesson_id,))
        await self.execute("UPDATE lessons SET status = ? WHERE id = ?", (status, lesson_id))
        if status == "done" and lesson:
            await self.execute(
                "UPDATE users SET balance = MAX(balance - 1, 0) WHERE id = ?", (lesson["student_id"],))

    async def lessons_to_remind(self, column: str, now_str: str, until_str: str) -> list[dict]:
        if column not in ("reminded_1h", "reminded_10m"):
            raise ValueError("Недопустимое поле напоминания")
        return await self.fetchall(
            f"SELECT l.*, u.full_name AS student_name FROM lessons l JOIN users u ON u.id = l.student_id "
            f"WHERE l.status = 'scheduled' AND u.is_blocked = 0 AND l.{column} = 0 "
            f"AND l.lesson_dt >= ? AND l.lesson_dt <= ?", (now_str, until_str))

    async def mark_lesson_reminded(self, lesson_id: int, one_hour: bool = False, ten_min: bool = False) -> None:
        if one_hour:
            await self.execute("UPDATE lessons SET reminded_1h = 1 WHERE id = ?", (lesson_id,))
        if ten_min:
            await self.execute("UPDATE lessons SET reminded_10m = 1 WHERE id = ?", (lesson_id,))

    async def count_lessons(self, student_id: int, status: str, start: str, end: str) -> int:
        return await self._scalar(
            "SELECT COUNT(*) FROM lessons WHERE student_id = ? AND status = ? "
            "AND substr(lesson_dt, 1, 10) BETWEEN ? AND ?", (student_id, status, start, end)) or 0

    # ---------- Домашние задания ----------

    async def add_homework(self, student_id: int, text: str | None, file_id: str | None,
                           file_type: str | None) -> int:
        return await self.execute(
            "INSERT INTO homework (student_id, text, file_id, file_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (student_id, text, file_id, file_type, now_ts()),
        )

    async def get_homework(self, homework_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM homework WHERE id = ?", (homework_id,))

    async def list_homework(self, student_id: int, limit: int = 15) -> list[dict]:
        return await self.fetchall(
            "SELECT h.*, (SELECT s.status FROM submissions s WHERE s.homework_id = h.id "
            "ORDER BY s.id DESC LIMIT 1) AS last_status "
            "FROM homework h WHERE h.student_id = ? ORDER BY h.id DESC LIMIT ?", (student_id, limit))

    async def get_last_submission(self, homework_id: int) -> dict | None:
        return await self.fetchone(
            "SELECT * FROM submissions WHERE homework_id = ? ORDER BY id DESC LIMIT 1", (homework_id,))

    async def create_submission(self, homework_id: int, student_id: int, items: list[dict]) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO submissions (homework_id, student_id, status, submitted_at) VALUES (?, ?, 'pending', ?)",
            (homework_id, student_id, now_ts()),
        )
        submission_id = cursor.lastrowid
        await self.conn.executemany(
            "INSERT INTO submission_items (submission_id, item_type, text, file_id) VALUES (?, ?, ?, ?)",
            [(submission_id, it["type"], it.get("text"), it.get("file_id")) for it in items],
        )
        await self.conn.commit()
        return submission_id

    async def get_submission(self, submission_id: int) -> dict | None:
        return await self.fetchone(
            "SELECT s.*, h.text AS hw_text, u.full_name AS student_name, u.telegram_id AS student_tg "
            "FROM submissions s JOIN homework h ON h.id = s.homework_id "
            "JOIN users u ON u.id = s.student_id WHERE s.id = ?", (submission_id,))

    async def get_submission_items(self, submission_id: int) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM submission_items WHERE submission_id = ? ORDER BY id", (submission_id,))

    async def review_submission(self, submission_id: int, status: str, score: int | None,
                                comment: str | None) -> None:
        await self.execute(
            "UPDATE submissions SET status = ?, score = ?, teacher_comment = ?, reviewed_at = ? WHERE id = ?",
            (status, score, comment, now_ts(), submission_id),
        )

    async def list_pending_submissions(self, limit: int = 20) -> list[dict]:
        return await self.fetchall(
            "SELECT s.id, s.homework_id, s.submitted_at, u.full_name AS student_name "
            "FROM submissions s JOIN users u ON u.id = s.student_id "
            "WHERE s.status = 'pending' ORDER BY s.id LIMIT ?", (limit,))

    async def average_score(self, student_id: int, start: str, end: str) -> float | None:
        return await self._scalar(
            "SELECT AVG(score) FROM submissions WHERE student_id = ? AND score IS NOT NULL "
            "AND substr(reviewed_at, 1, 10) BETWEEN ? AND ?", (student_id, start, end))

    async def count_unsubmitted(self, student_id: int) -> int:
        """ДЗ без сдачи или с последним статусом «На доработку»."""
        return await self._scalar(
            "SELECT COUNT(*) FROM homework h WHERE h.student_id = ? AND ("
            "NOT EXISTS (SELECT 1 FROM submissions s WHERE s.homework_id = h.id) "
            "OR (SELECT s.status FROM submissions s WHERE s.homework_id = h.id ORDER BY s.id DESC LIMIT 1) = 'rework')",
            (student_id,)) or 0

    # ---------- Оплата ----------

    async def add_payment(self, user_id: int, amount: float, lessons_count: int, days: int) -> str:
        """Записывает оплату, пополняет баланс и продлевает пакет. Возвращает дату окончания."""
        user = await self.get_user_by_id(user_id)
        base = datetime.now(TIMEZONE).date()
        if user and user["package_end"]:
            current_end = date.fromisoformat(user["package_end"])
            if current_end > base:
                base = current_end
        valid_until = (base + timedelta(days=days)).isoformat()
        await self.execute(
            "INSERT INTO payments (user_id, amount, lessons_count, valid_until, paid_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, lessons_count, valid_until, now_ts()),
        )
        await self.execute(
            "UPDATE users SET balance = balance + ?, package_end = ?, payment_reminded = 0 WHERE id = ?",
            (lessons_count, valid_until, user_id),
        )
        return valid_until

    async def list_payments(self, user_id: int, limit: int = 3) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM payments WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))

    async def users_for_payment_reminder(self, today_str: str, until_str: str) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM users WHERE role = 'student' AND is_blocked = 0 AND payment_reminded = 0 "
            "AND package_end IS NOT NULL AND package_end >= ? AND package_end <= ?", (today_str, until_str))

    async def mark_payment_reminded(self, user_id: int) -> None:
        await self.execute("UPDATE users SET payment_reminded = 1 WHERE id = ?", (user_id,))

    # ---------- Отчёты ----------

    async def save_report(self, student_id: int, week_start: str, week_end: str, attended: int,
                          avg_score: float | None, unsubmitted: int, comment: str | None) -> int:
        return await self.execute(
            "INSERT INTO reports (student_id, week_start, week_end, attended, avg_score, unsubmitted, "
            "comment, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (student_id, week_start, week_end, attended, avg_score, unsubmitted, comment, now_ts()),
        )

    # ---------- FAQ ----------

    async def list_faq(self) -> list[dict]:
        return await self.fetchall("SELECT * FROM faq ORDER BY id")

    async def get_faq(self, faq_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM faq WHERE id = ?", (faq_id,))

    async def add_faq(self, question: str, answer: str) -> int:
        return await self.execute("INSERT INTO faq (question, answer) VALUES (?, ?)", (question, answer))

    async def delete_faq(self, faq_id: int) -> None:
        await self.execute("DELETE FROM faq WHERE id = ?", (faq_id,))

    # ---------- Материалы (чек-листы, PDF, картинки) ----------

    async def add_material(self, title: str, description: str | None, file_id: str, file_type: str) -> int:
        return await self.execute(
            "INSERT INTO materials (title, description, file_id, file_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (title, description, file_id, file_type, now_ts()),
        )

    async def list_materials(self) -> list[dict]:
        return await self.fetchall("SELECT * FROM materials ORDER BY id DESC")

    async def get_material(self, material_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM materials WHERE id = ?", (material_id,))

    async def delete_material(self, material_id: int) -> None:
        await self.execute("DELETE FROM materials WHERE id = ?", (material_id,))

    # ---------- Преподаватели ----------

    async def add_teacher(self, telegram_id: int, name: str, subject: str | None,
                          experience_years: int, bio: str | None) -> int:
        return await self.execute(
            "INSERT INTO teachers (telegram_id, name, subject, experience_years, bio, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (telegram_id, name, subject, experience_years, bio, now_ts()),
        )

    async def get_teacher(self, teacher_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM teachers WHERE id = ?", (teacher_id,))

    async def get_teacher_by_telegram(self, telegram_id: int) -> dict | None:
        return await self.fetchone("SELECT * FROM teachers WHERE telegram_id = ?", (telegram_id,))

    async def list_teachers(self) -> list[dict]:
        return await self.fetchall(
            "SELECT t.*, (SELECT COUNT(*) FROM users u WHERE u.teacher_id = t.id AND u.role = 'student') "
            "AS students_count FROM teachers t ORDER BY t.name COLLATE NOCASE")

    async def delete_teacher(self, teacher_id: int) -> None:
        """Удаляет преподавателя; у его учеников и занятий teacher_id становится пустым (ON DELETE SET NULL)."""
        await self.execute("DELETE FROM teachers WHERE id = ?", (teacher_id,))

    async def set_student_teacher(self, user_id: int, teacher_id: int | None) -> None:
        """Привязывает ученика к преподавателю (None — снять привязку), обновляет его будущие занятия."""
        await self.execute("UPDATE users SET teacher_id = ? WHERE id = ?", (teacher_id, user_id))
        if teacher_id is None:
            # Снятие привязки: будущие занятия остаются без преподавателя, история не меняется
            await self.execute(
                "UPDATE lessons SET teacher_id = NULL WHERE student_id = ? AND status = 'scheduled'", (user_id,))
        else:
            # Будущие занятия переходят к новому преподавателю; прошлые занятия без преподавателя
            # (например, перенесённые из старой базы) записываются на него. Чужая история не меняется.
            await self.execute(
                "UPDATE lessons SET teacher_id = ? WHERE student_id = ? AND (status = 'scheduled' OR teacher_id IS NULL)",
                (teacher_id, user_id))

    async def list_students_of_teacher(self, teacher_id: int) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM users WHERE role = 'student' AND teacher_id = ? ORDER BY full_name COLLATE NOCASE",
            (teacher_id,))

    async def list_scheduled_lessons_of_teacher(self, teacher_id: int, since_str: str, limit: int = 15) -> list[dict]:
        return await self.fetchall(
            "SELECT l.*, u.full_name AS student_name FROM lessons l JOIN users u ON u.id = l.student_id "
            "WHERE l.teacher_id = ? AND l.status = 'scheduled' AND l.lesson_dt >= ? "
            "ORDER BY l.lesson_dt LIMIT ?", (teacher_id, since_str, limit))

    async def ensure_admin_users(self, admin_ids) -> list[str]:
        """Гарантирует запись с ролью admin для каждого ID из .env. Возвращает список выполненных действий."""
        notes: list[str] = []
        for telegram_id in admin_ids:
            row = await self.get_user(telegram_id)
            if row is None:
                await self.execute(
                    "INSERT INTO users (telegram_id, username, role, full_name, phone, created_at) "
                    "VALUES (?, NULL, 'admin', 'Администратор', NULL, ?)", (telegram_id, now_ts()))
                notes.append(f"создана запись администратора {telegram_id}")
            elif row["role"] != "admin":
                await self.execute("UPDATE users SET role = 'admin' WHERE id = ?", (row["id"],))
                notes.append(f"пользователь {telegram_id} ({row['full_name']}) получил роль admin")
        return notes

    # ---------- Статистика по ученику и преподавателю ----------

    async def get_student_stats(self, student_id: int) -> dict:
        """Занятия, оплаты, ДЗ и средний балл одного ученика."""
        lesson_rows = await self.fetchall(
            "SELECT status, COUNT(*) AS c FROM lessons WHERE student_id = ? GROUP BY status", (student_id,))
        payments = await self.fetchone(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total FROM payments "
            "WHERE user_id = ? AND status = 'paid'", (student_id,))
        return {
            "lessons": {row["status"]: row["c"] for row in lesson_rows},
            "payments_count": payments["cnt"],
            "payments_sum": payments["total"],
            "last_payments": await self.list_payments(student_id, limit=3),
            "avg_score": await self._scalar(
                "SELECT AVG(score) FROM submissions WHERE student_id = ? AND score IS NOT NULL", (student_id,)),
            "hw_total": await self._scalar("SELECT COUNT(*) FROM homework WHERE student_id = ?", (student_id,)) or 0,
            "hw_submitted": await self._scalar(
                "SELECT COUNT(DISTINCT homework_id) FROM submissions WHERE student_id = ?", (student_id,)) or 0,
            "hw_pending": await self._scalar(
                "SELECT COUNT(*) FROM submissions WHERE student_id = ? AND status = 'pending'", (student_id,)) or 0,
            "hw_unsubmitted": await self.count_unsubmitted(student_id),
        }

    async def get_teacher_stats(self, teacher_id: int) -> dict:
        """Сводка по ученикам одного преподавателя: ученики, проведённые занятия, деньги."""
        month = now_local().strftime("%Y-%m")
        money_sql = ("SELECT COALESCE(SUM(p.amount), 0) FROM payments p JOIN users u ON u.id = p.user_id "
                     "WHERE u.teacher_id = ? AND p.status = 'paid'")
        return {
            "students": await self._scalar(
                "SELECT COUNT(*) FROM users WHERE role = 'student' AND teacher_id = ?", (teacher_id,)) or 0,
            "lessons_done": await self._scalar(
                "SELECT COUNT(*) FROM lessons WHERE teacher_id = ? AND status = 'done'", (teacher_id,)) or 0,
            "lessons_planned": await self._scalar(
                "SELECT COUNT(*) FROM lessons WHERE teacher_id = ? AND status = 'scheduled'", (teacher_id,)) or 0,
            "money_total": await self._scalar(money_sql, (teacher_id,)) or 0,
            "money_month": await self._scalar(
                money_sql + " AND substr(p.paid_at, 1, 7) = ?", (teacher_id, month)) or 0,
        }

    # ---------- Статистика ----------

    async def payments_by_month(self, limit: int = 12) -> list[dict]:
        """Оплаты, сгруппированные по месяцам (новые сверху): число оплат, сумма, занятий в пакетах."""
        return await self.fetchall(
            "SELECT substr(paid_at, 1, 7) AS month, COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total, "
            "COALESCE(SUM(lessons_count), 0) AS lessons FROM payments WHERE status = 'paid' "
            "GROUP BY month ORDER BY month DESC LIMIT ?", (limit,))

    async def get_stats(self) -> dict:
        return {
            "students": await self._scalar("SELECT COUNT(*) FROM users WHERE role = 'student'"),
            "teachers": await self._scalar("SELECT COUNT(*) FROM teachers"),
            "parents": await self._scalar("SELECT COUNT(*) FROM users WHERE role = 'parent'"),
            "blocked": await self._scalar("SELECT COUNT(*) FROM users WHERE is_blocked = 1"),
            "payments_count": await self._scalar("SELECT COUNT(*) FROM payments"),
            "payments_sum": await self._scalar("SELECT COALESCE(SUM(amount), 0) FROM payments"),
            "submissions_total": await self._scalar("SELECT COUNT(*) FROM submissions"),
            "submissions_pending": await self._scalar("SELECT COUNT(*) FROM submissions WHERE status = 'pending'"),
            "lessons_done": await self._scalar("SELECT COUNT(*) FROM lessons WHERE status = 'done'"),
            "bookings_new": await self._scalar("SELECT COUNT(*) FROM bookings WHERE status = 'new'"),
        }
    


    async def add_site_booking(
        self,
        token: str,
        name: str,
        phone: str,
        lesson_format: str,
        goal: str,
        user_role: str,
        subject: str | None = None,
    ) -> int:
        """Заявка с сайта: status='pending', source='site', telegram_id=0, username=NULL.

        lesson_format / goal / subject — русские подписи из config (как в заявках из бота).
        Бросает sqlite3.IntegrityError, если токен уже занят (уникальный индекс idx_bookings_token).
        """
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            cur = await conn.execute(
                """
                INSERT INTO bookings
                    (telegram_id, username, name, phone, lesson_format, goal,
                     subject, user_role, status, source, token, created_at)
                VALUES (0, NULL, ?, ?, ?, ?, ?, ?, 'pending', 'site', ?, datetime('now'))
                """,
                (name, phone, lesson_format, goal, subject, user_role, token),
            )
            await conn.commit()
            return cur.lastrowid

    async def get_booking_by_token(self, token: str) -> dict | None:
        """Только необработанная (pending) заявка — повторный переход по ссылке вернёт None."""
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM bookings WHERE token = ? AND status = 'pending'", (token,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def get_pending_site_booking(self, booking_id: int) -> dict | None:
        """Заявка с сайта, ожидающая подтверждения, по id (для кнопок site:ok / site:edit)."""
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM bookings WHERE id = ? AND source = 'site' AND status = 'pending'",
                (booking_id,),
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def confirm_booking(
        self, booking_id: int, telegram_id: int, username: str | None = None
    ) -> bool:
        """pending → new и привязка к Telegram-аккаунту.

        WHERE status='pending' делает подтверждение одноразовым: повторное нажатие вернёт False.
        """
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            cur = await conn.execute(
                """
                UPDATE bookings
                   SET status = 'new',
                       telegram_id = ?,
                       username = COALESCE(?, username)
                 WHERE id = ? AND status = 'pending'
                """,
                (telegram_id, username, booking_id),
            )
            await conn.commit()
            return cur.rowcount > 0

    async def update_site_booking(self, booking_id: int, goal: str, lesson_format: str) -> bool:
        """Ветка «✏️ Изменить»: правим цель и формат в ещё не подтверждённой заявке."""
        async with aiosqlite.connect(DB_PATH, timeout=10) as conn:
            cur = await conn.execute(
                "UPDATE bookings SET goal = ?, lesson_format = ? WHERE id = ? AND status = 'pending'",
                (goal, lesson_format, booking_id),
            )
            await conn.commit()
            return cur.rowcount > 0



db = Database(DB_PATH)
