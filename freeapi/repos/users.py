"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


def create_user(username, password_hash):
    user_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute('INSERT INTO users(id, username, password_hash, created_at) VALUES (?, ?, ?, ?)', (user_id, username, password_hash, now))
        return row(conn.execute('SELECT id, username, created_at, last_login_at FROM users WHERE id = ?', (user_id,)).fetchone())


def get_user_by_username(username):
    with db() as conn:
        return row(conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone())


def get_user_by_id(user_id):
    with db() as conn:
        return row(conn.execute('SELECT id, username, created_at, last_login_at FROM users WHERE id = ?', (user_id,)).fetchone())


def touch_login(user_id):
    now = msk_now()
    with db() as conn:
        conn.execute('UPDATE users SET last_login_at = ? WHERE id = ?', (now, user_id))
