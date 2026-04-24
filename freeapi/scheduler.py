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


def _cleanup_community():
    """Жёстко удалить soft-deleted сообщения «Сообщества» старше 30 дней."""
    try:
        from freeapi.repos.community import gc_old_soft_deleted
        n = gc_old_soft_deleted(days=30)
        if n:
            logger.info('[Scheduler] community: hard-deleted %s soft-deleted messages', n)
    except Exception as exc:
        logger.error('[Scheduler] community GC: %s', exc)


def _cleanup_review_removals():
    """Удалить записи review_removals старше 60 дней (для журнала достаточно)."""
    try:
        with db() as conn:
            result = conn.execute(
                "DELETE FROM review_removals "
                "WHERE datetime(removed_at) < datetime('now', '-60 days')"
            )
            n = result.rowcount or 0
            if n:
                logger.info('[Scheduler] review_removals: deleted %s old rows', n)
    except Exception as exc:
        logger.error('[Scheduler] review_removals GC: %s', exc)


def start_background_tasks():
    def worker():
        while True:
            # Каждые 24 часа — все GC-задачи последовательно.
            time.sleep(86400)
            _cleanup_old_sessions()
            _cleanup_community()
            _cleanup_review_removals()

    t = threading.Thread(target=worker, daemon=True, name='scheduler')
    t.start()
    logger.info('[Scheduler] Фоновые задачи запущены (sessions/community/review_removals GC каждые 24ч)')
