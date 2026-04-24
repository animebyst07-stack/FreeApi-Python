import os
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


def _tg_link_poll_worker():
    """M3: непрерывный лонг-поллинг TG-бота уведомлений на /start <token>.

    Запускается отдельным потоком (не каждые 24 часа, как GC), чтобы
    привязка через deep-link срабатывала сразу. Долгий long-poll (timeout=5)
    в самом getUpdates минимизирует RPS к Telegram. Если TG_NOTIFY_TOKEN
    не задан — тред тихо ждёт и периодически перепроверяет.
    """
    from freeapi import tg_notify
    from freeapi.repos import users as users_repo

    def on_link(link_token, chat_id, tg_username):
        user = users_repo.find_user_by_tg_link_token(link_token)
        if not user:
            return False
        users_repo.set_tg_notify_chat_id(user['id'], chat_id)
        logger.info('[Scheduler][TG_LINK] uid=%s linked chat=%s tg=%s',
                    user['id'], chat_id, tg_username)
        return True

    backoff = 5
    while True:
        token = (os.environ.get('TG_NOTIFY_TOKEN') or '').strip()
        if not token:
            time.sleep(60)  # бот не настроен — реже проверяем переменную
            continue
        try:
            n = tg_notify.poll_link_updates(token, on_link)
            if n:
                logger.info('[Scheduler][TG_LINK] обработано /start: %s', n)
            backoff = 5
        except Exception as exc:
            logger.warning('[Scheduler][TG_LINK] poll error: %s (backoff=%ss)',
                           exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
            continue
        # poll_link_updates сам делает long-poll timeout=5, дополнительно
        # ждём 1 сек, чтобы при пустых апдейтах не молотить TG.
        time.sleep(1)


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

    # M3: отдельный поток для polling TG-бота уведомлений.
    t2 = threading.Thread(target=_tg_link_poll_worker, daemon=True,
                          name='tg-link-poll')
    t2.start()
    logger.info('[Scheduler] TG link poller запущен')
