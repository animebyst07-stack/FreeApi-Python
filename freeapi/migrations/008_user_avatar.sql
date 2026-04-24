-- G5: аватарка профиля. Хранится как data URL (image/jpeg или image/png),
-- кадрирование выполняется в браузере (256x256, JPEG q=0.78..0.92), лимит 200 KB.
ALTER TABLE users ADD COLUMN avatar TEXT;
