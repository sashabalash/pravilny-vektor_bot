"""Новые методы для database.py — вставьте их внутрь вашего класса (рядом с add_booking / get_booking).

В верх database.py добавьте импорты, если их там ещё нет:
    import aiosqlite
    from config import DB_PATH

database.py я не видел, поэтому методы открывают собственное короткое соединение. Если вам удобнее
использовать общее соединение вашего класса (после db.connect()), замените строку
`async with aiosqlite.connect(DB_PATH, timeout=10) as conn:` на него — SQL менять не нужно.
"""
from __future__ import annotations

import aiosqlite

from config import DB_PATH


class QuickBookingMethods:
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
