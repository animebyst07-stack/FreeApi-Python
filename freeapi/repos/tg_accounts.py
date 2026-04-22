"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


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
