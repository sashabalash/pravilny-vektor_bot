"""Схема bookings и миграция school_new.db для «быстрой записи».

bot.py вызывает migrate_bookings(DB_PATH) при каждом старте ДО db.connect(): на старой базе она добавит
колонки через ALTER TABLE, на свежей (файла или таблицы ещё нет) ничего не сделает. Повторный запуск безопасен.

Для schema.py (чтобы свежая установка сразу создавала таблицу с новыми полями): в CREATE TABLE bookings
добавьте две колонки из BOOKINGS_TABLE_SQL (source, token), а индекс BOOKINGS_TOKEN_INDEX_SQL — в SCHEMA
после таблицы; затем поднимите SCHEMA_VERSION. Остальные колонки оставьте как у вас.

Ручной запуск (бот остановлен, делает резервную копию):
    python schema_migration.py school_new.db
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime

# --- для schema.py ---------------------------------------------------------
BOOKINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   INTEGER NOT NULL,
    username      TEXT,
    name          TEXT,
    phone         TEXT,
    lesson_format TEXT,
    goal          TEXT,
    subject       TEXT,
    user_role     TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source        TEXT NOT NULL DEFAULT 'bot',
    token         TEXT
);
"""

BOOKINGS_TOKEN_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_token "
    "ON bookings(token) WHERE token IS NOT NULL;"
)

ALTER_SOURCE_SQL = "ALTER TABLE bookings ADD COLUMN source TEXT NOT NULL DEFAULT 'bot';"
ALTER_TOKEN_SQL = "ALTER TABLE bookings ADD COLUMN token TEXT;"


def migrate_bookings(db_path: str) -> list[str]:
    """Добавляет bookings.source / bookings.token и уникальный индекс. Возвращает выполненные шаги.

    Если файла базы или таблицы bookings ещё нет (первый запуск) — ничего не делает: их создаст SCHEMA.
    """
    if not os.path.exists(db_path):
        return []
    done: list[str] = []
    con = sqlite3.connect(db_path, timeout=10)
    try:
        cols = {row[1] for row in con.execute("PRAGMA table_info(bookings)")}
        if not cols:
            return []
        if "source" not in cols:
            con.execute(ALTER_SOURCE_SQL)
            done.append("ADD COLUMN source")
        if "token" not in cols:
            con.execute(ALTER_TOKEN_SQL)
            done.append("ADD COLUMN token")
        if done:
            # индекс — строго ПОСЛЕ добавления колонки
            con.execute(BOOKINGS_TOKEN_INDEX_SQL)
            done.append("CREATE UNIQUE INDEX idx_bookings_token")
        else:
            con.execute(BOOKINGS_TOKEN_INDEX_SQL)  # IF NOT EXISTS — ничего не меняет, если индекс уже есть
        con.commit()
    finally:
        con.close()
    return done


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "school_new.db"
    if not os.path.exists(path):
        raise SystemExit(f"Файл базы не найден: {path}")
    backup = f"{path}.bak-{datetime.now():%Y%m%d%H%M%S}"
    shutil.copy2(path, backup)
    print(f"Резервная копия: {backup}")
    steps = migrate_bookings(path)
    print("Выполнено:" if steps else "Уже актуально, менять нечего.")
    for step in steps:
        print(" -", step)
