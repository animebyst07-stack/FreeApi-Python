-- Базовая схема (исторический init).
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
