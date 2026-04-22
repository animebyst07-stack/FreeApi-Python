"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


def get_admin_setting(key, default=None):
    with db() as conn:
        r = conn.execute('SELECT value FROM admin_settings WHERE key=?', (key,)).fetchone()
        return r['value'] if r else default


def set_admin_setting(key, value):
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO admin_settings(key, value) VALUES (?, ?)', (key, value))


def get_all_admin_settings():
    with db() as conn:
        result = conn.execute('SELECT key, value FROM admin_settings').fetchall()
        return {r['key']: r['value'] for r in result}


# ─────────── ADMIN HELPERS ───────────


def get_all_keys_for_admin():
    with db() as conn:
        return rows(conn.execute(
            'SELECT k.id, k.name, k.default_model, k.is_active, u.username '
            'FROM api_keys k JOIN users u ON k.user_id = u.id ORDER BY k.created_at DESC'
        ).fetchall())


# ─────────── SUPPORT CHAT ───────────
