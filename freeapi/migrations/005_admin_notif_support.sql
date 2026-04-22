-- IDEMPOTENT
-- Привязка уведомления админа к диалогу поддержки (для структурированных
-- отчётов от support-агента: review_text=summary, ai_advice=детали,
-- support_chat_id=айди чата, по которому админ открывает всю переписку).
ALTER TABLE admin_notifications ADD COLUMN support_chat_id TEXT;
