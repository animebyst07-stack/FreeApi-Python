-- IDEMPOTENT
-- Расширение отзывов: фото, ответ владельца, журнал правок.
ALTER TABLE reviews ADD COLUMN images TEXT DEFAULT '[]';
ALTER TABLE reviews ADD COLUMN admin_images TEXT DEFAULT '[]';
ALTER TABLE reviews ADD COLUMN reply_by TEXT DEFAULT 'ai';
ALTER TABLE reviews ADD COLUMN edit_timestamps TEXT DEFAULT '[]';
