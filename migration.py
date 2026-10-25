"""
Миграция данных бота «Правильный Вектор» со старой структуры базы на новую (версия 2).

Что делает:
  1. Открывает СТАРУЮ базу только для чтения (она не изменяется).
  2. Создаёт НОВУЮ базу (по умолчанию school_new.db) с обновлённой структурой
     (преподаватели, связь ученик → преподаватель, роль admin и т. д.).
  3. Переносит всех пользователей, заявки, занятия, домашние задания и работы, оплаты,
     отчёты, FAQ и материалы с теми же идентификаторами.
  4. Назначает роль admin Telegram ID из .env (ADMIN_IDS или ADMIN_ID); если записи нет — создаёт её.
  5. Проверяет количество перенесённых строк и целостность, печатает отчёт.

Запуск (из папки проекта, с активным окружением):
    python migration.py                                   # старая база из DB_PATH или pravilny_vektor.db
    python migration.py --old путь/к/старой.db --new school_new.db
    python migration.py --force                           # перезаписать существующую новую базу

После успешной миграции укажите в .env:  DB_PATH=school_new.db
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from schema import SCHEMA, SCHEMA_VERSION

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Порядок важен: сначала таблицы, на которые ссылаются другие
TABLES = ["teachers", "users", "bookings", "lessons", "homework", "submissions",
          "submission_items", "payments", "reports", "faq", "materials"]


def parse_admin_ids() -> list[int]:
    """Telegram ID администраторов из .env (поддерживаются ADMIN_IDS и ADMIN_ID)."""
    raw = ",".join([os.getenv("ADMIN_IDS", ""), os.getenv("ADMIN_ID", "")])
    result: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit() and int(part) not in result:
            result.append(int(part))
    return result


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def copy_table(old: sqlite3.Connection, new: sqlite3.Connection, table: str) -> int:
    """Копирует общие колонки таблицы; новые колонки получают значения по умолчанию."""
    if not table_exists(old, table):
        return 0
    old_columns = set(table_columns(old, table))
    columns = [name for name in table_columns(new, table) if name in old_columns]
    if not columns:
        return 0
    column_list = ", ".join(columns)
    rows = old.execute(f"SELECT {column_list} FROM {table}").fetchall()
    marks = ", ".join("?" for _ in columns)
    new.executemany(f"INSERT INTO {table} ({column_list}) VALUES ({marks})", rows)
    return len(rows)


def ensure_admins(new: sqlite3.Connection, admin_ids: list[int]) -> list[str]:
    """Роль admin для ID из .env: повышает существующую запись или создаёт новую."""
    report: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for telegram_id in admin_ids:
        row = new.execute("SELECT id, role, full_name FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if row is None:
            new.execute(
                "INSERT INTO users (telegram_id, username, role, full_name, phone, created_at) "
                "VALUES (?, NULL, 'admin', 'Администратор', NULL, ?)", (telegram_id, now))
            report.append(f"  ✓ {telegram_id}: записи не было — создана с ролью admin")
        elif row[1] != "admin":
            new.execute("UPDATE users SET role = 'admin' WHERE id = ?", (row[0],))
            report.append(f"  ✓ {telegram_id}: «{row[2]}» была ролью «{row[1]}» — теперь admin")
        else:
            report.append(f"  ✓ {telegram_id}: уже admin")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Миграция базы бота на структуру версии 2")
    parser.add_argument("--old", default=os.getenv("DB_PATH", str(BASE_DIR / "pravilny_vektor.db")),
                        help="путь к старой базе (по умолчанию DB_PATH из .env или pravilny_vektor.db)")
    parser.add_argument("--new", default=str(BASE_DIR / "school_new.db"), help="путь к новой базе")
    parser.add_argument("--force", action="store_true", help="перезаписать новую базу, если она уже есть")
    args = parser.parse_args()

    old_path, new_path = Path(args.old), Path(args.new)
    admin_ids = parse_admin_ids()

    print("=" * 60)
    print("МИГРАЦИЯ БАЗЫ «Правильный Вектор» → структура версии", SCHEMA_VERSION)
    print("=" * 60)
    print(f"Старая база: {old_path}")
    print(f"Новая база:  {new_path}")
    print(f"Администраторы из .env: {admin_ids or 'не заданы'}")

    if old_path.resolve() == new_path.resolve():
        print("\n✗ Старая и новая базы не должны быть одним файлом.")
        return 1
    if new_path.exists():
        if not args.force:
            print(f"\n✗ Файл {new_path} уже существует. Чтобы перезаписать, добавьте --force.")
            return 1
        new_path.unlink()
    if not admin_ids:
        print("\n⚠ В .env не задан ADMIN_IDS (или ADMIN_ID): права администратора назначены не будут.")

    old = None
    if old_path.exists():
        old = sqlite3.connect(f"file:{old_path}?mode=ro", uri=True)  # только чтение
    else:
        print(f"\n⚠ Старая база не найдена: будет создана пустая новая база.")

    new = sqlite3.connect(new_path)
    try:
        new.execute("PRAGMA foreign_keys = OFF")  # на время копирования
        new.executescript(SCHEMA)
        new.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        print("\nПеренос данных:")
        print(f"  {'таблица':<18}{'было':>8}{'стало':>8}")
        problems = []
        for table in TABLES:
            before = count_rows(old, table) if old else 0
            copied = copy_table(old, new, table) if old else 0
            after = count_rows(new, table)
            mark = "" if before == after else "  ← РАСХОЖДЕНИЕ"
            if before != after:
                problems.append(table)
            print(f"  {table:<18}{before:>8}{after:>8}{mark}")

        print("\nПрава администратора:")
        for line in ensure_admins(new, admin_ids) or ["  (нет ID администраторов)"]:
            print(line)
        new.commit()

        new.execute("PRAGMA foreign_keys = ON")
        fk_errors = new.execute("PRAGMA foreign_key_check").fetchall()
        integrity = new.execute("PRAGMA integrity_check").fetchone()[0]
        print("\nПроверка целостности:", integrity)
        if fk_errors:
            problems.append("foreign_key_check")
            print(f"  ⚠ Нарушений связей между таблицами: {len(fk_errors)}")
    except Exception as exc:
        new.close()
        if new_path.exists():
            new_path.unlink()  # не оставляем недоделанную базу
        print(f"\n✗ Ошибка миграции: {exc}\nНовая база удалена, старая не изменялась.")
        return 1
    finally:
        if old:
            old.close()
    new.close()

    print("\n" + "=" * 60)
    if problems:
        print("⚠ Миграция завершена с замечаниями:", ", ".join(problems))
    else:
        print("✓ Миграция завершена успешно.")
    print(f"Новая база сохранена: {new_path}")
    print("Старая база не изменена и может быть использована как резервная копия.")
    print("\nДальше: укажите в .env  DB_PATH=" + new_path.name + "  и запустите бота (python bot.py).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
