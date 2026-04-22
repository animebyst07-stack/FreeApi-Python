-- IDEMPOTENT
-- Доп. колонки api_keys: dual_mode, переводчик, контекст, лимиты, отложенное восстановление.
ALTER TABLE api_keys ADD COLUMN dual_mode INTEGER DEFAULT 0;
ALTER TABLE api_keys ADD COLUMN translator_account_id TEXT REFERENCES tg_accounts(id) ON DELETE SET NULL;
ALTER TABLE api_keys ADD COLUMN context_tokens INTEGER DEFAULT 0;
ALTER TABLE api_keys ADD COLUMN context_kb REAL DEFAULT 0.0;
ALTER TABLE api_keys ADD COLUMN limit_hit INTEGER DEFAULT 0;
ALTER TABLE api_keys ADD COLUMN pending_restore TEXT DEFAULT NULL;
