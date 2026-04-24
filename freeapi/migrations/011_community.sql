-- Блок 1: схема «Сообщество» (общий чат + посты администраторов).
-- См. plan.txt блоки 1.1—1.9.

-- 1.1 Сообщения (kind = 'message' для чата, 'admin_post' для постов).
CREATE TABLE IF NOT EXISTS community_messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'message',
    text TEXT NOT NULL DEFAULT '',
    is_deleted INTEGER NOT NULL DEFAULT 0,
    deleted_by TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cm_kind_created ON community_messages(kind, is_deleted, created_at);
CREATE INDEX IF NOT EXISTS idx_cm_user ON community_messages(user_id);

-- 1.2 История правок (каждая правка — новая версия).
CREATE TABLE IF NOT EXISTS community_message_versions (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    text TEXT NOT NULL,
    images_json TEXT,
    edited_at TEXT NOT NULL,
    edited_by TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES community_messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cmv_msg ON community_message_versions(message_id, edited_at);

-- 1.3 Картинки (data URL, до 10 на сообщение, лимит 200 KB каждая).
CREATE TABLE IF NOT EXISTS community_message_images (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    data_url TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES community_messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cmi_msg ON community_message_images(message_id, sort);

-- 1.4 Закреп (несколько одновременно, сортировка по pinned_at DESC).
CREATE TABLE IF NOT EXISTS community_pins (
    message_id TEXT PRIMARY KEY,
    pinned_by TEXT NOT NULL,
    pinned_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES community_messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cp_pinned_at ON community_pins(pinned_at);

-- 1.5 Реакции (эмодзи). Один юзер — одна реакция данным эмодзи на сообщение.
CREATE TABLE IF NOT EXISTS community_reactions (
    message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    emoji TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id, emoji),
    FOREIGN KEY (message_id) REFERENCES community_messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cr_msg ON community_reactions(message_id);

-- 1.6 Упоминания @username — для уведомлений.
CREATE TABLE IF NOT EXISTS community_mentions (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    mentioned_user_id TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES community_messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cmen_user ON community_mentions(mentioned_user_id, notified);
CREATE INDEX IF NOT EXISTS idx_cmen_msg ON community_mentions(message_id);

-- 1.7 Бан в чате (отдельно от review_restrictions).
CREATE TABLE IF NOT EXISTS community_chat_bans (
    user_id TEXT PRIMARY KEY,
    banned_until TEXT NOT NULL,
    reason TEXT,
    banned_by TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 1.9 Mute упоминаний — добавляем как колонку у users (минимизирует доп. таблицы).
ALTER TABLE users ADD COLUMN notif_mute_mentions INTEGER NOT NULL DEFAULT 0;
