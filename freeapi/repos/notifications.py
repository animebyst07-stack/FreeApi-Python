"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


def create_user_notification(user_id, message):
    notif_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute('INSERT INTO user_notifications(id, user_id, message, created_at) VALUES (?, ?, ?, ?)', (notif_id, user_id, message, now))
        return row(conn.execute('SELECT * FROM user_notifications WHERE id=?', (notif_id,)).fetchone())


def get_user_notifications(user_id):
    with db() as conn:
        return rows(conn.execute(
            'SELECT * FROM user_notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50',
            (user_id,)
        ).fetchall())


def mark_notification_read(notif_id, user_id):
    with db() as conn:
        conn.execute('UPDATE user_notifications SET is_read=1 WHERE id=? AND user_id=?', (notif_id, user_id))


def delete_user_notification(notif_id, user_id):
    with db() as conn:
        conn.execute('DELETE FROM user_notifications WHERE id=? AND user_id=?', (notif_id, user_id))


def mark_all_notifications_read(user_id):
    """Помечает все уведомления пользователя как прочитанные. Возвращает кол-во обновлённых."""
    with db() as conn:
        cur = conn.execute(
            'UPDATE user_notifications SET is_read=1 WHERE user_id=? AND is_read=0',
            (user_id,)
        )
        return cur.rowcount or 0


def count_unread_notifications(user_id):
    with db() as conn:
        r = conn.execute('SELECT COUNT(*) as cnt FROM user_notifications WHERE user_id=? AND is_read=0', (user_id,)).fetchone()
        return r['cnt'] if r else 0


# ─────────── ADMIN NOTIFICATIONS ───────────


def create_admin_notification(review_id, review_text, review_score, review_author, ai_response, ai_advice):
    notif_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute(
            'INSERT INTO admin_notifications(id, review_id, review_text, review_score, review_author, ai_response, ai_advice, created_at) VALUES (?,?,?,?,?,?,?,?)',
            (notif_id, review_id, review_text, review_score, review_author, ai_response, ai_advice, now)
        )
        return row(conn.execute('SELECT * FROM admin_notifications WHERE id=?', (notif_id,)).fetchone())


def get_admin_notifications():
    with db() as conn:
        return rows(conn.execute('SELECT * FROM admin_notifications ORDER BY created_at DESC LIMIT 100').fetchall())


def delete_admin_notification(notif_id):
    with db() as conn:
        conn.execute('DELETE FROM admin_notifications WHERE id=?', (notif_id,))


# ─────────── ADMIN SETTINGS ───────────
