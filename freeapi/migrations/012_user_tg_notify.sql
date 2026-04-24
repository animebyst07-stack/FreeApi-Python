-- M3: Telegram-пуши на @упоминания (см. plan.txt блок 11).
-- Колонки в users:
--   tg_notify_chat_id   — числовой chat_id привязанного личного диалога с ботом TG_NOTIFY_TOKEN.
--                         Заполняется либо ручной привязкой (если юзер сам знает свой chat_id),
--                         либо автоматически после команды /start <link_token> в боте
--                         (см. tg_notify.poll_link_updates).
--   tg_notify_link_token — одноразовый токен для deep-link привязки.
--                         Генерируется по запросу GET /api/community/tg_link, сбрасывается после
--                         успешной привязки.
--   tg_notify_linked_at  — момент привязки (для UI и аудита).
ALTER TABLE users ADD COLUMN tg_notify_chat_id TEXT;
ALTER TABLE users ADD COLUMN tg_notify_link_token TEXT;
ALTER TABLE users ADD COLUMN tg_notify_linked_at TEXT;

CREATE INDEX IF NOT EXISTS idx_users_tg_notify_link_token ON users(tg_notify_link_token);
