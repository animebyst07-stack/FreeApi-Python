-- B2: группировка уведомлений по типам.
-- kind: 'review' | 'support' | 'system' (default 'system' для совместимости).
-- ref_id: идентификатор связанной сущности (review_id и т.п.) — для дип-линков.
ALTER TABLE user_notifications ADD COLUMN kind TEXT NOT NULL DEFAULT 'system';
ALTER TABLE user_notifications ADD COLUMN ref_id TEXT;
CREATE INDEX IF NOT EXISTS idx_user_notif_user_kind ON user_notifications(user_id, kind);
