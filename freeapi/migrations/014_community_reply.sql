-- M3.5: ответы на сообщения в Сообществе (Telegram-style replies).
-- reply_to_id — id сообщения, на которое отвечают. NULL = обычное сообщение.
-- ON DELETE SET NULL: если оригинал жёстко удалён GC, ответ сохраняется,
-- но цитата перестаёт грузиться (фронт покажет «удалено»).
ALTER TABLE community_messages ADD COLUMN reply_to_id TEXT;
CREATE INDEX IF NOT EXISTS idx_community_messages_reply_to
    ON community_messages(reply_to_id);
