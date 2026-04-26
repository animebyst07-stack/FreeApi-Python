-- Хранить @username Telegram-аккаунта, который привязали через /start.
-- Нужно для UI: после привязки показывать "Уведомления привязаны к @user"
-- вместо нейтрального "chat_id: 12345". Поле опционально (юзер мог
-- скрыть @username в Telegram → тогда оставляем NULL и показываем ник
-- сайта или просто chat_id).
ALTER TABLE users ADD COLUMN tg_notify_username TEXT;
