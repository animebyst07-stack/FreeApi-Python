import threading
import time
import logging

from freeapi.database import db

logger = logging.getLogger(__name__)


def _cleanup_old_sessions():
    """B-05: Удалить setup_sessions старше 7 дней со статусом error/cancelled."""
    try:
        with db() as conn:
            result = conn.execute(
                "DELETE FROM setup_sessions "
                "WHERE status IN ('error', 'cancelled') "
                "AND datetime(updated_at) < datetime('now', '-7 days')"
            )
            deleted = result.rowcount
            if deleted:
                logger.info(f'[Scheduler] Удалено {deleted} устаревших setup_sessions')
    except Exception as exc:
        logger.error(f'[Scheduler] Ошибка очистки: {exc}')


def start_background_tasks():
    def worker():
        while True:
            # Каждые 24 часа
            time.sleep(86400)
            _cleanup_old_sessions()

    t = threading.Thread(target=worker, daemon=True, name='scheduler')
    t.start()
    logger.info('[Scheduler] Фоновые задачи запущены')
