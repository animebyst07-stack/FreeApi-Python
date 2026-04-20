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


def create_tg_account(user_id, api_id, api_hash, phone=None, session_string=None):
    account_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute('INSERT INTO tg_accounts(id, user_id, api_id, api_hash, phone, session_string, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)', (account_id, user_id, str(api_id), api_hash, phone, session_string, now))
        return row(conn.execute('SELECT * FROM tg_accounts WHERE id = ?', (account_id,)).fetchone())


def update_tg_account(account_id, **fields):
    if not fields:
        return get_tg_account(account_id)
    keys = list(fields.keys())
    values = [fields[key] for key in keys] + [msk_now(), account_id]
    with db() as conn:
        conn.execute(f"UPDATE tg_accounts SET {', '.join([key + ' = ?' for key in keys])}, last_checked_at = ? WHERE id = ?", values)
        return row(conn.execute('SELECT * FROM tg_accounts WHERE id = ?', (account_id,)).fetchone())


def get_tg_account(account_id):
    with db() as conn:
        return row(conn.execute('SELECT * FROM tg_accounts WHERE id = ?', (account_id,)).fetchone())


def get_ready_tg_account(user_id):
    with db() as conn:
        return row(conn.execute('SELECT * FROM tg_accounts WHERE user_id = ? AND setup_done = 1 ORDER BY created_at DESC LIMIT 1', (user_id,)).fetchone())


def delete_tg_accounts(user_id):
    with db() as conn:
        conn.execute('DELETE FROM tg_accounts WHERE user_id = ?', (user_id,))


def create_setup_session(user_id, account_id):
    setup_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute('INSERT INTO setup_sessions(id, user_id, tg_account_id, status, current_step, step_label, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (setup_id, user_id, account_id, 'running', 0, 'Инициализация...', now, now))
    return setup_id


def get_running_setup(user_id):
    with db() as conn:
        return row(conn.execute('SELECT * FROM setup_sessions WHERE user_id = ? AND status = ? ORDER BY created_at DESC LIMIT 1', (user_id, 'running')).fetchone())


def get_setup_session(setup_id):
    with db() as conn:
        return row(conn.execute('SELECT * FROM setup_sessions WHERE id = ?', (setup_id,)).fetchone())


def update_setup_session(setup_id, **fields):
    if not fields:
        return
    keys = list(fields.keys())
    values = [fields[key] for key in keys] + [msk_now(), setup_id]
    with db() as conn:
        conn.execute(f"UPDATE setup_sessions SET {', '.join([key + ' = ?' for key in keys])}, updated_at = ? WHERE id = ?", values)


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


def get_global_stats():
    with db() as conn:
        users = conn.execute('SELECT COUNT(*) AS c FROM users').fetchone()['c']
        total = conn.execute('SELECT COUNT(*) AS c FROM requests').fetchone()['c']
        today = conn.execute("SELECT COUNT(*) AS c FROM requests WHERE request_at >= date('now')").fetchone()['c']
        return {'users': int(users), 'totalRequests': int(total), 'todayRequests': int(today)}


def get_model_stats():
    with db() as conn:
        return rows(conn.execute("SELECT * FROM model_stats WHERE stat_month = date('now', 'start of month')").fetchall())


def update_model_stats(model_id, response_ms, ok=True):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO model_stats(model_id, stat_month, avg_response_ms, total_requests, successful_reqs) VALUES (?, date('now', 'start of month'), NULL, 0, 0)", (model_id,))
        if ok:
            conn.execute("UPDATE model_stats SET total_requests = total_requests + 1, successful_reqs = successful_reqs + 1, avg_response_ms = CASE WHEN avg_response_ms IS NULL THEN ? ELSE CAST(((avg_response_ms * successful_reqs) + ?) / (successful_reqs + 1) AS INTEGER) END WHERE model_id = ? AND stat_month = date('now', 'start of month')", (response_ms, response_ms, model_id))
        else:
            conn.execute("UPDATE model_stats SET total_requests = total_requests + 1 WHERE model_id = ? AND stat_month = date('now', 'start of month')", (model_id,))


def get_log_codes():
    with db() as conn:
        return rows(conn.execute('SELECT * FROM log_codes ORDER BY category, code').fetchall())


# ─────────── REVIEWS ───────────

def create_review(user_id, score, text, status='pending', images=None):
    import json as _json
    review_id = uuid4()
    now = msk_now()
    images_json = _json.dumps(images or [])
    with db() as conn:
        existing = conn.execute('SELECT id FROM reviews WHERE user_id = ?', (user_id,)).fetchone()
        if existing:
            conn.execute(
                'UPDATE reviews SET score=?, text=?, status=?, ai_response=NULL, images=?, updated_at=? WHERE user_id=?',
                (score, text, status, images_json, now, user_id)
            )
            return row(conn.execute('SELECT * FROM reviews WHERE user_id = ?', (user_id,)).fetchone())
        conn.execute(
            'INSERT INTO reviews(id, user_id, score, text, status, images, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (review_id, user_id, score, text, status, images_json, now, now)
        )
        return row(conn.execute('SELECT * FROM reviews WHERE id = ?', (review_id,)).fetchone())


def get_review_by_user(user_id):
    with db() as conn:
        return row(conn.execute('SELECT * FROM reviews WHERE user_id = ?', (user_id,)).fetchone())


def get_approved_reviews(limit=10, offset=0):
    with db() as conn:
        total_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM reviews WHERE status IN ('approved', 'flagged')"
        ).fetchone()
        total = total_row['cnt'] if total_row else 0
        items = rows(conn.execute(
            'SELECT r.id, r.score, r.text, r.ai_response, r.images, r.admin_images, r.created_at, r.updated_at, r.status, u.username '
            'FROM reviews r JOIN users u ON r.user_id = u.id '
            "WHERE r.status IN ('approved', 'flagged') ORDER BY r.updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall())
        return items, total


def get_avg_review_score():
    """Возвращает средний рейтинг всех одобренных отзывов, округлённый до 1 знака."""
    with db() as conn:
        row = conn.execute(
            "SELECT ROUND(AVG(score), 1) AS avg FROM reviews WHERE status IN ('approved', 'flagged')"
        ).fetchone()
        if row and row['avg'] is not None:
            return float(row['avg'])
        return None


def get_pending_reviews():
    with db() as conn:
        return rows(conn.execute(
            'SELECT r.*, u.username FROM reviews r JOIN users u ON r.user_id = u.id '
            "WHERE r.status = 'pending' ORDER BY r.created_at ASC"
        ).fetchall())


def get_all_reviews_admin(limit=10, offset=0):
    with db() as conn:
        total_row = conn.execute('SELECT COUNT(*) AS cnt FROM reviews').fetchone()
        total = total_row['cnt'] if total_row else 0
        items = rows(conn.execute(
            'SELECT r.*, u.username FROM reviews r JOIN users u ON r.user_id = u.id ORDER BY r.created_at DESC LIMIT ? OFFSET ?',
            (limit, offset)
        ).fetchall())
        return items, total


def update_review_status(review_id, status, ai_response=None, admin_images=None):
    import json as _json
    now = msk_now()
    with db() as conn:
        if admin_images is not None:
            admin_images_json = _json.dumps(admin_images)
            conn.execute(
                'UPDATE reviews SET status=?, ai_response=?, admin_images=?, updated_at=? WHERE id=?',
                (status, ai_response, admin_images_json, now, review_id)
            )
        else:
            conn.execute(
                'UPDATE reviews SET status=?, ai_response=?, updated_at=? WHERE id=?',
                (status, ai_response, now, review_id)
            )
        return row(conn.execute('SELECT * FROM reviews WHERE id=?', (review_id,)).fetchone())


def delete_review(review_id):
    with db() as conn:
        conn.execute('DELETE FROM reviews WHERE id=?', (review_id,))


def get_user_ban(user_id):
    now = msk_now()
    with db() as conn:
        r = conn.execute(
            "SELECT banned_until, reason FROM review_restrictions WHERE user_id=? AND banned_until > ?",
            (user_id, now)
        ).fetchone()
        return row(r)


def restrict_review_access(user_id, banned_until, reason):
    now = msk_now()
    with db() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO review_restrictions(user_id, banned_until, reason, created_at) VALUES (?, ?, ?, ?)',
            (user_id, banned_until, reason, now)
        )


# ─────────── USER NOTIFICATIONS ───────────

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

def get_user_tg_accounts(user_id):
    with db() as conn:
        return rows(conn.execute(
            'SELECT id, api_id, phone, is_valid, setup_done, created_at, '
            'tg_username, tg_first_name FROM tg_accounts WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        ).fetchall())


def update_tg_account_info(account_id, tg_username=None, tg_first_name=None):
    fields = {}
    if tg_username is not None:
        fields['tg_username'] = tg_username
    if tg_first_name is not None:
        fields['tg_first_name'] = tg_first_name
    if not fields:
        return
    keys = list(fields.keys())
    values = [fields[k] for k in keys] + [account_id]
    with db() as conn:
        conn.execute(
            f"UPDATE tg_accounts SET {', '.join([k + '=?' for k in keys])} WHERE id=?",
            values
        )
