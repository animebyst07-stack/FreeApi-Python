"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


def create_support_chat(user_id, subject=None):
    from freeapi.security import uuid4
    chat_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute(
            'INSERT INTO support_chats(id, user_id, status, subject, created_at) VALUES (?, ?, ?, ?, ?)',
            (chat_id, user_id, 'open', subject, now)
        )
        return row(conn.execute('SELECT * FROM support_chats WHERE id=?', (chat_id,)).fetchone())


def get_open_support_chat(user_id):
    with db() as conn:
        return row(conn.execute(
            "SELECT * FROM support_chats WHERE user_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone())


def close_support_chat(chat_id, report_text=None):
    now = msk_now()
    with db() as conn:
        conn.execute(
            "UPDATE support_chats SET status='closed', closed_at=?, report_text=? WHERE id=?",
            (now, report_text, chat_id)
        )


def add_support_message(chat_id, role, content, image_data=None):
    from freeapi.security import uuid4
    msg_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute(
            'INSERT INTO support_messages(id, chat_id, role, content, image_data, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (msg_id, chat_id, role, content, image_data, now)
        )
        return row(conn.execute('SELECT * FROM support_messages WHERE id=?', (msg_id,)).fetchone())


def get_support_messages(chat_id, limit=100):
    with db() as conn:
        return rows(conn.execute(
            'SELECT * FROM support_messages WHERE chat_id=? ORDER BY created_at ASC LIMIT ?',
            (chat_id, limit)
        ).fetchall())


# ─────────── CONTEXT TRACKING ───────────
