import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from freeapi.config import DATABASE_PATH
from freeapi.log_codes import LOG_CODES
from freeapi.models import AI_MODELS

_lock = threading.RLock()

MSK = timezone(timedelta(hours=3))


def msk_now():
    return datetime.now(MSK).strftime('%Y-%m-%d %H:%M:%S')

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS tg_accounts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    api_id TEXT NOT NULL,
    api_hash TEXT NOT NULL,
    phone TEXT,
    session_string TEXT,
    is_valid INTEGER DEFAULT 0,
    setup_done INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_checked_at TEXT
);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tg_account_id TEXT NOT NULL REFERENCES tg_accounts(id) ON DELETE CASCADE,
    key_value TEXT UNIQUE NOT NULL,
    name TEXT DEFAULT 'Мой ключ',
    default_model TEXT DEFAULT 'gemini-3.0-flash-thinking',
    current_model TEXT DEFAULT 'gemini-3.0-flash-thinking',
    skip_hints INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    is_busy INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    api_key_id TEXT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    request_at TEXT DEFAULT CURRENT_TIMESTAMP,
    response_at TEXT,
    response_ms INTEGER,
    status TEXT NOT NULL,
    log_code TEXT NOT NULL,
    error_msg TEXT,
    has_images INTEGER DEFAULT 0,
    images_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS model_stats (
    model_id TEXT NOT NULL,
    stat_month TEXT NOT NULL,
    avg_response_ms INTEGER,
    total_requests INTEGER DEFAULT 0,
    successful_reqs INTEGER DEFAULT 0,
    PRIMARY KEY (model_id, stat_month)
);
CREATE TABLE IF NOT EXISTS log_codes (
    code TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    solution TEXT
);
CREATE TABLE IF NOT EXISTS setup_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tg_account_id TEXT REFERENCES tg_accounts(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER DEFAULT 0,
    step_label TEXT,
    error_msg TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    ai_response TEXT,
    banned_until TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS review_restrictions (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    banned_until TEXT NOT NULL,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS admin_notifications (
    id TEXT PRIMARY KEY,
    review_id TEXT,
    review_text TEXT,
    review_score INTEGER,
    review_author TEXT,
    ai_response TEXT,
    ai_advice TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS admin_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS support_chats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'open',
    subject TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    report_text TEXT
);
CREATE TABLE IF NOT EXISTS support_messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES support_chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    image_data TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_api_keys_value ON api_keys(key_value);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_requests_key_time ON requests(api_key_id, request_at DESC);
CREATE INDEX IF NOT EXISTS idx_tg_accounts_user ON tg_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id);
DELETE FROM reviews WHERE rowid NOT IN (SELECT MIN(rowid) FROM reviews GROUP BY user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_one_per_user ON reviews(user_id);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);
CREATE INDEX IF NOT EXISTS idx_review_restrictions_until ON review_restrictions(banned_until);
CREATE INDEX IF NOT EXISTS idx_user_notifications_user ON user_notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_support_chats_user ON support_chats(user_id);
CREATE INDEX IF NOT EXISTS idx_support_messages_chat ON support_messages(chat_id);
CREATE TABLE IF NOT EXISTS agent_memory (
    key_id          TEXT PRIMARY KEY REFERENCES api_keys(id) ON DELETE CASCADE,
    context_md      TEXT DEFAULT '',
    favorite_md     TEXT DEFAULT '',
    lang_hint       TEXT DEFAULT 'ru',
    context_updated_at TEXT,
    favorite_updated_at TEXT
);
"""

_MIGRATIONS = [
    "ALTER TABLE api_keys ADD COLUMN dual_mode INTEGER DEFAULT 0",
    "ALTER TABLE api_keys ADD COLUMN translator_account_id TEXT REFERENCES tg_accounts(id) ON DELETE SET NULL",
    "ALTER TABLE api_keys ADD COLUMN context_tokens INTEGER DEFAULT 0",
    "ALTER TABLE api_keys ADD COLUMN context_kb REAL DEFAULT 0.0",
    "ALTER TABLE api_keys ADD COLUMN limit_hit INTEGER DEFAULT 0",
    "ALTER TABLE api_keys ADD COLUMN pending_restore TEXT DEFAULT NULL",
    "ALTER TABLE tg_accounts ADD COLUMN tg_username TEXT",
    "ALTER TABLE tg_accounts ADD COLUMN tg_first_name TEXT",
    "ALTER TABLE reviews ADD COLUMN images TEXT DEFAULT '[]'",
    "ALTER TABLE reviews ADD COLUMN admin_images TEXT DEFAULT '[]'",
    "ALTER TABLE reviews ADD COLUMN reply_by TEXT DEFAULT 'ai'",
    "ALTER TABLE reviews ADD COLUMN edit_timestamps TEXT DEFAULT '[]'",
    """CREATE TABLE IF NOT EXISTS review_likes (
        review_id TEXT NOT NULL,
        user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        value     INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(review_id, user_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_review_likes_review ON review_likes(review_id)",
]


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


def init_database():
    with db() as conn:
        conn.executescript(SCHEMA_SQL)
        for migration in _MIGRATIONS:
            try:
                conn.execute(migration)
            except Exception:
                pass
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
            conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_enabled', ?)",
                         (old_enabled[0] if old_enabled else '0',))
            conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_key_id', ?)",
                         (old_key[0] if old_key else '',))
        else:
            conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_enabled', '0')")
            conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_key_id', '')")

        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_system_prompt', '')")
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_model', '')")
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_enabled', '0')")
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_key_id', '')")
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_model', '')")
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_system_prompt', '')")


def row(row_obj):
    return None if row_obj is None else {key: row_obj[key] for key in row_obj.keys()}


def rows(row_list):
    return [row(item) for item in row_list]
