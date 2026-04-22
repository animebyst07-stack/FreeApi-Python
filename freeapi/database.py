import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from freeapi.config import DATABASE_PATH
from freeapi.log_codes import LOG_CODES
from freeapi.models import AI_MODELS

logger = logging.getLogger('freeapi')

_lock = threading.RLock()

MSK = timezone(timedelta(hours=3))

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), 'migrations')


def msk_now():
    return datetime.now(MSK).strftime('%Y-%m-%d %H:%M:%S')


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def db():
    with _lock:
        conn = get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _list_migration_files():
    if not os.path.isdir(MIGRATIONS_DIR):
        return []
    files = [f for f in os.listdir(MIGRATIONS_DIR) if f.endswith('.sql')]
    files.sort()
    return files


def _execute_migration_sql(conn, sql_text, idempotent):
    """Выполнить SQL миграции. Если idempotent=True — глушить ошибки на отдельных
    statement'ах (нужно для ALTER TABLE ADD COLUMN, который в SQLite не имеет
    IF NOT EXISTS до 3.35)."""
    if not idempotent:
        conn.executescript(sql_text)
        return
    statements = []
    buf = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('--'):
            buf.append(line)
            continue
        buf.append(line)
        if stripped.endswith(';'):
            statements.append('\n'.join(buf).strip())
            buf = []
    if buf and ''.join(buf).strip():
        statements.append('\n'.join(buf).strip())
    for stmt in statements:
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            logger.info('[MIGRATIONS] idempotent skip: %s (%s)', stmt.split('\n', 1)[0][:80], exc)


def _run_migrations(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT)')
    applied = {row_obj[0] for row_obj in conn.execute('SELECT version FROM schema_migrations').fetchall()}

    has_users_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    has_users = has_users_row is not None
    bootstrap_mark = has_users and not applied

    files = _list_migration_files()
    for fname in files:
        version = os.path.splitext(fname)[0]
        if version in applied:
            continue
        path = os.path.join(MIGRATIONS_DIR, fname)
        with open(path, 'r', encoding='utf-8') as fp:
            sql_text = fp.read()
        if bootstrap_mark:
            conn.execute(
                'INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)',
                (version, msk_now()),
            )
            logger.info('[MIGRATIONS] bootstrap mark %s', version)
            continue
        idempotent = sql_text.lstrip().startswith('-- IDEMPOTENT')
        _execute_migration_sql(conn, sql_text, idempotent)
        conn.execute(
            'INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)',
            (version, msk_now()),
        )
        logger.info('[MIGRATIONS] applied %s', version)


def _seed_reference_data(conn):
    conn.execute(
        "UPDATE setup_sessions SET status='error', error_msg='SERVER_RESTART' WHERE status='running'"
    )
    for item in LOG_CODES:
        conn.execute(
            'INSERT OR IGNORE INTO log_codes(code, category, description, solution) VALUES (?, ?, ?, ?)',
            (item['code'], item['category'], item['description'], item.get('solution')),
        )
    for model in AI_MODELS:
        conn.execute(
            "INSERT OR IGNORE INTO model_stats(model_id, stat_month, avg_response_ms, total_requests, successful_reqs) VALUES (?, date('now', 'start of month'), NULL, 0, 0)",
            (model['id'],),
        )
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('agent_enabled', '0')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('agent_key_id', '')")

    row_me = conn.execute("SELECT value FROM admin_settings WHERE key='moderator_enabled'").fetchone()
    if not row_me:
        old_enabled = conn.execute("SELECT value FROM admin_settings WHERE key='agent_enabled'").fetchone()
        old_key = conn.execute("SELECT value FROM admin_settings WHERE key='agent_key_id'").fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_enabled', ?)",
            (old_enabled[0] if old_enabled else '0',),
        )
        conn.execute(
            "INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_key_id', ?)",
            (old_key[0] if old_key else '',),
        )
    else:
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_enabled', '0')")
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_key_id', '')")

    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_system_prompt', '')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_model', '')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_enabled', '0')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_key_id', '')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_model', '')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_system_prompt', '')")


def init_database():
    with db() as conn:
        _run_migrations(conn)
        _seed_reference_data(conn)


def row(row_obj):
    return None if row_obj is None else {key: row_obj[key] for key in row_obj.keys()}


def rows(row_list):
    return [row(item) for item in row_list]
