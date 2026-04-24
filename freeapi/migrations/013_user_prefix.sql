-- Миграция 013: поле prefix у пользователя (короткий тег рядом с ником в чате).
-- Пример: [Новичок], [VIP], [Разработчик]
ALTER TABLE users ADD COLUMN display_prefix TEXT DEFAULT NULL;
