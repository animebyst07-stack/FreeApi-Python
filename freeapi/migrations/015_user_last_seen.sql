-- M3.6: трекинг last_seen для отображения «онлайн / был N минут назад»
-- рядом с ником в Сообществе. Хранится как INTEGER (unix epoch seconds).
-- 0 = никогда не заходил после этой миграции.
ALTER TABLE users ADD COLUMN last_seen_at INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_users_last_seen_at ON users(last_seen_at);
