"""M1: подсчёт удалений отзывов в скользящем окне 7 дней.

Используется agent._do_delete(): каждое удаление логируется здесь, и при
достижении порога (5 удалений за 7 дней) накладывается бан в
review_restrictions на 7 дней с момента ПЕРВОГО удаления в окне.
"""
import logging
from datetime import datetime, timedelta

from freeapi.database import db, msk_now, MSK
from freeapi.security import uuid4

logger = logging.getLogger('freeapi')

REMOVAL_WINDOW_DAYS = 7
REMOVAL_THRESHOLD = 5


def log_removal(user_id, review_id, reason, removed_by=None):
    """Записать удаление отзыва. user_id — автор удалённого отзыва."""
    if not user_id:
        return None
    rid = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute(
            'INSERT INTO review_removals(id, user_id, review_id, reason, removed_by, removed_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (rid, user_id, review_id, reason, removed_by, now),
        )
        logger.info('[REV-REMOVAL] logged uid=%s review=%s reason=%r removed_by=%s',
                    user_id, review_id, (reason or '')[:60], removed_by)
        return rid


def count_recent_removals(user_id, days=REMOVAL_WINDOW_DAYS):
    """Сколько удалений у автора за последние `days` дней (включая текущее)."""
    if not user_id:
        return 0
    cutoff = (datetime.now(MSK) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    with db() as conn:
        r = conn.execute(
            'SELECT COUNT(*) AS cnt FROM review_removals '
            'WHERE user_id=? AND removed_at >= ?',
            (user_id, cutoff),
        ).fetchone()
        return int(r['cnt'] if r else 0)


def first_removal_at_in_window(user_id, days=REMOVAL_WINDOW_DAYS):
    """Время первого удаления в окне (для расчёта banned_until = first + 7d)."""
    if not user_id:
        return None
    cutoff = (datetime.now(MSK) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    with db() as conn:
        r = conn.execute(
            'SELECT MIN(removed_at) AS first_at FROM review_removals '
            'WHERE user_id=? AND removed_at >= ?',
            (user_id, cutoff),
        ).fetchone()
        return r['first_at'] if r else None
