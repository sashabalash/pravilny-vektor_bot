"""
Схема базы данных (версия 2) — общая для бота (database.py) и скрипта миграции (migration.py).
Файл не зависит от сторонних библиотек.

Что нового по сравнению с версией 1:
  • таблица teachers (преподаватели);
  • users.teacher_id и lessons.teacher_id — привязка ученика и занятия к преподавателю;
  • роль 'admin' в users;
  • bookings.subject (предмет из заявки), payments.status (статус оплаты).
"""

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    subject TEXT,
    experience_years INTEGER NOT NULL DEFAULT 0,
    bio TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    username TEXT,
    role TEXT NOT NULL CHECK (role IN ('student', 'parent', 'admin')),
    full_name TEXT NOT NULL,
    phone TEXT,
    grade TEXT,
    subject TEXT,
    child_name TEXT,
    teacher_id INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    is_blocked INTEGER NOT NULL DEFAULT 0,
    balance INTEGER NOT NULL DEFAULT 0,
    package_end TEXT,
    payment_reminded INTEGER NOT NULL DEFAULT 0,
    report_comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    username TEXT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    lesson_format TEXT NOT NULL,
    goal TEXT NOT NULL,
    subject TEXT,
    user_role TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_dt TEXT NOT NULL,
    teacher_id INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    link TEXT,
    topic TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    reminded_1h INTEGER NOT NULL DEFAULT 0,
    reminded_10m INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_lessons_dt ON lessons(lesson_dt, status);

CREATE TABLE IF NOT EXISTS homework (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text TEXT,
    file_id TEXT,
    file_type TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    homework_id INTEGER NOT NULL REFERENCES homework(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    score INTEGER,
    teacher_comment TEXT,
    submitted_at TEXT NOT NULL,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS submission_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    text TEXT,
    file_id TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount REAL NOT NULL,
    lessons_count INTEGER NOT NULL,
    valid_until TEXT NOT NULL,
    paid_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'paid'
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    attended INTEGER NOT NULL,
    avg_score REAL,
    unsubmitted INTEGER NOT NULL,
    comment TEXT,
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    file_id TEXT NOT NULL,
    file_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_teacher ON users(teacher_id);
CREATE INDEX IF NOT EXISTS idx_lessons_teacher ON lessons(teacher_id, status);
"""

DEFAULT_FAQ = [
    (
        "Как проходят занятия?",
        "🎥 Занятия проходят онлайн в видеоформате. Преподаватель объясняет тему, "
        "разбирает задачи формата ЦТ/ЦЭ и выдаёт домашнее задание. "
        "Формат — индивидуально или в мини-группе. Ссылку на урок бот пришлёт заранее.",
    ),
    (
        "Как оплатить?",
        "💳 Оплата производится пакетами занятий. Откройте «Баланс занятий» и нажмите "
        "«Оплатить» или напишите преподавателю: @Alexander_Balash. "
        "За 3 дня до окончания пакета бот пришлёт напоминание.",
    ),
    (
        "Что если пропустил?",
        "🗓 Сообщите преподавателю как можно раньше — занятие можно перенести по договорённости. "
        "Напишите: @Alexander_Balash.",
    ),
]
