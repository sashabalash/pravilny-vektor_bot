"""
Резервные копии базы: sqlite3 online backup (корректно работает и в режиме WAL)
+ ротация последних KEEP файлов. Запускается планировщиком раз в сутки.
"""
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, DB_PATH

logger = logging.getLogger(__name__)

BACKUP_DIR = BASE_DIR / "backups"
KEEP = 14


def make_backup(db_path: str | None = None, backup_dir: str | Path | None = None,
                keep: int = KEEP) -> str:
    """Создаёт копию базы и удаляет старые. Возвращает путь к новому файлу."""
    source_path = str(db_path or DB_PATH)
    directory = Path(backup_dir or BACKUP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{Path(source_path).stem}-{datetime.now():%Y-%m-%d_%H%M}.db"

    source = sqlite3.connect(source_path, timeout=15)
    try:
        with sqlite3.connect(target) as destination:
            source.backup(destination)
    finally:
        source.close()

    files = sorted(directory.glob("*.db"))
    for old in files[:-keep]:
        try:
            old.unlink()
        except OSError:
            logger.warning("Не удалось удалить старый бэкап %s", old)
    logger.info("Бэкап базы создан: %s (файлов в папке: %s)", target.name, len(files))
    return str(target)


async def daily_backup_job() -> None:
    """Задача планировщика: не падать, если бэкап не удался."""
    try:
        make_backup()
    except Exception:
        logger.exception("Не удалось создать резервную копию базы")
