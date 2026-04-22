"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


def create_api_key(user_id, account_id, key_value, name, default_model):
    key_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute('INSERT INTO api_keys(id, user_id, tg_account_id, key_value, name, default_model, current_model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (key_id, user_id, account_id, key_value, name, default_model, default_model, now))
        return row(conn.execute('SELECT * FROM api_keys WHERE id = ?', (key_id,)).fetchone())


def get_user_keys(user_id):
    with db() as conn:
        return rows(conn.execute('SELECT * FROM api_keys WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC', (user_id,)).fetchall())


def get_account_key(user_id, account_id):
    with db() as conn:
        return row(conn.execute('SELECT * FROM api_keys WHERE user_id = ? AND tg_account_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1', (user_id, account_id)).fetchone())


def get_user_key(user_id, key_id):
    with db() as conn:
        return row(conn.execute('SELECT * FROM api_keys WHERE id = ? AND user_id = ? AND is_active = 1', (key_id, user_id)).fetchone())


def get_key_by_value(value):
    with db() as conn:
        return row(conn.execute('SELECT * FROM api_keys WHERE key_value = ? AND is_active = 1', (value,)).fetchone())


def get_key_by_id(key_id):
    with db() as conn:
        return row(conn.execute('SELECT * FROM api_keys WHERE id = ?', (key_id,)).fetchone())


def update_api_key(key_id, **fields):
    if not fields:
        return get_key_by_id(key_id)
    keys = list(fields.keys())
    values = [fields[key] for key in keys] + [key_id]
    with db() as conn:
        conn.execute(f"UPDATE api_keys SET {', '.join([key + ' = ?' for key in keys])} WHERE id = ?", values)
        return row(conn.execute('SELECT * FROM api_keys WHERE id = ?', (key_id,)).fetchone())


def deactivate_key(key_id):
    with db() as conn:
        conn.execute('UPDATE api_keys SET is_active = 0 WHERE id = ?', (key_id,))


def create_request(api_key_id, model, log_code, has_images=False, images_count=0):
    request_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute('INSERT INTO requests(id, api_key_id, model, status, log_code, has_images, images_count, request_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (request_id, api_key_id, model, 'processing', log_code, int(has_images), int(images_count), now))
        return row(conn.execute('SELECT * FROM requests WHERE id = ?', (request_id,)).fetchone())


def finish_request(request_id, status, log_code, response_ms=None, error_msg=None):
    now = msk_now()
    with db() as conn:
        conn.execute('UPDATE requests SET status = ?, log_code = ?, response_at = ?, response_ms = ?, error_msg = ? WHERE id = ?', (status, log_code, now, response_ms, error_msg, request_id))


def get_key_logs(api_key_id, limit=50):
    with db() as conn:
        return rows(conn.execute('SELECT * FROM requests WHERE api_key_id = ? ORDER BY request_at DESC LIMIT ?', (api_key_id, limit)).fetchall())


def get_key_month_stats(api_key_id):
    with db() as conn:
        data = conn.execute("SELECT COUNT(*) AS total, COALESCE(AVG(response_ms), 0) AS avg_ms FROM requests WHERE api_key_id = ? AND request_at >= date('now', 'start of month')", (api_key_id,)).fetchone()
        return {'monthlyRequests': int(data['total'] or 0), 'avgResponseMs': round(data['avg_ms'] or 0)}


def increment_context_tokens(key_id, tokens):
    with db() as conn:
        conn.execute(
            'UPDATE api_keys SET context_tokens = context_tokens + ?, '
            'context_kb = ROUND((context_tokens + ?) * 4.0 / 1024, 1) WHERE id = ?',
            (tokens, tokens, key_id)
        )


def reset_context_stats(key_id):
    with db() as conn:
        conn.execute(
            'UPDATE api_keys SET context_tokens = 0, context_kb = 0.0, '
            'limit_hit = 0, pending_restore = NULL WHERE id = ?',
            (key_id,)
        )


def set_limit_hit(key_id, value):
    with db() as conn:
        conn.execute('UPDATE api_keys SET limit_hit = ? WHERE id = ?', (int(value), key_id))


def get_pending_restore(key_id):
    import json as _json
    with db() as conn:
        r = conn.execute('SELECT pending_restore FROM api_keys WHERE id = ?', (key_id,)).fetchone()
    if not r or not r['pending_restore']:
        return None
    try:
        return _json.loads(r['pending_restore'])
    except Exception:
        return None


def set_pending_restore(key_id, data):
    import json as _json
    value = _json.dumps(data) if data else None
    with db() as conn:
        conn.execute('UPDATE api_keys SET pending_restore = ? WHERE id = ?', (value, key_id))


# ─────────── TG ACCOUNT INFO ───────────
