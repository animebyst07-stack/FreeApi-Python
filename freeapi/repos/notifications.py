"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


_VALID_KINDS = ('review', 'support', 'system')


def _norm_kind(kind):
    return kind if kind in _VALID_KINDS else 'system'


def create_user_notification(user_id, message, kind='system', ref_id=None):
    """B2: добавлены поля kind/ref_id для группировки и дип-линков."""
    notif_id = uuid4()
    now = msk_now()
    kind = _norm_kind(kind)
    with db() as conn:
        conn.execute(
            'INSERT INTO user_notifications(id, user_id, message, created_at, kind, ref_id) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (notif_id, user_id, message, now, kind, ref_id)
        )
        return row(conn.execute('SELECT * FROM user_notifications WHERE id=?', (notif_id,)).fetchone())


def get_user_notifications(user_id, kind=None, limit=50, offset=0):
    """B2: kind=None → все типы; kind='review'|'support'|'system' → только указанный."""
    sql = 'SELECT * FROM user_notifications WHERE user_id=?'
    params = [user_id]
    if kind:
        sql += ' AND kind=?'
        params.append(_norm_kind(kind))
    sql += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
    params.extend([int(limit), int(offset)])
    with db() as conn:
        return rows(conn.execute(sql, tuple(params)).fetchall())


def mark_notification_read(notif_id, user_id):
    with db() as conn:
        conn.execute('UPDATE user_notifications SET is_read=1 WHERE id=? AND user_id=?', (notif_id, user_id))


def delete_user_notification(notif_id, user_id):
    with db() as conn:
        conn.execute('DELETE FROM user_notifications WHERE id=? AND user_id=?', (notif_id, user_id))


def mark_all_notifications_read(user_id, kind=None):
    """B2: kind=None → все; иначе помечает только указанный тип. Возвращает кол-во обновлённых."""
    sql = 'UPDATE user_notifications SET is_read=1 WHERE user_id=? AND is_read=0'
    params = [user_id]
    if kind:
        sql += ' AND kind=?'
        params.append(_norm_kind(kind))
    with db() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.rowcount or 0


def count_unread_notifications(user_id, kind=None):
    """B2: kind=None → общий счётчик непрочитанных; иначе — по типу."""
    sql = 'SELECT COUNT(*) as cnt FROM user_notifications WHERE user_id=? AND is_read=0'
    params = [user_id]
    if kind:
        sql += ' AND kind=?'
        params.append(_norm_kind(kind))
    with db() as conn:
        r = conn.execute(sql, tuple(params)).fetchone()
        return r['cnt'] if r else 0


def count_unread_notifications_by_kind(user_id):
    """B2: возвращает {'all': N, 'review': N, 'support': N, 'system': N}."""
    with db() as conn:
        rs = conn.execute(
            'SELECT kind, COUNT(*) as cnt FROM user_notifications '
            'WHERE user_id=? AND is_read=0 GROUP BY kind',
            (user_id,)
        ).fetchall()
    out = {'all': 0, 'review': 0, 'support': 0, 'system': 0}
    for r in rs:
        k = _norm_kind(r['kind'])
        c = int(r['cnt'] or 0)
        out[k] = out.get(k, 0) + c
        out['all'] += c
    return out


# ─────────── ADMIN NOTIFICATIONS ───────────


def create_admin_notification(review_id, review_text, review_score, review_author,
                              ai_response, ai_advice, support_chat_id=None):
    """support_chat_id — опциональный айди чата поддержки (для отчётов от
    support-агента: тогда review_text = краткое summary от ИИ, ai_advice =
    подробности отчёта, а сам диалог админ откроет в модалке по chat_id).
    Для обычных уведомлений по отзывам остаётся None."""
    notif_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute(
            'INSERT INTO admin_notifications(id, review_id, review_text, review_score, '
            'review_author, ai_response, ai_advice, support_chat_id, created_at) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            (notif_id, review_id, review_text, review_score, review_author,
             ai_response, ai_advice, support_chat_id, now)
        )
        return row(conn.execute('SELECT * FROM admin_notifications WHERE id=?', (notif_id,)).fetchone())


def get_admin_notifications():
    with db() as conn:
        return rows(conn.execute('SELECT * FROM admin_notifications ORDER BY created_at DESC LIMIT 100').fetchall())


def delete_admin_notification(notif_id):
    with db() as conn:
        conn.execute('DELETE FROM admin_notifications WHERE id=?', (notif_id,))


# ─────────── ADMIN SETTINGS ───────────
