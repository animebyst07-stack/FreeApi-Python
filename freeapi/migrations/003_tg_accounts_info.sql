-- IDEMPOTENT
-- Профиль Telegram-аккаунта.
ALTER TABLE tg_accounts ADD COLUMN tg_username TEXT;
ALTER TABLE tg_accounts ADD COLUMN tg_first_name TEXT;
