-- T10: расширенные аватарки (фото / GIF / видео ≤10с с обрезкой и циклом).
-- Старая колонка avatar (TEXT data URL) остаётся для обратной совместимости —
-- сериализатор отдаёт её как media kind='image' пока юзер не загрузит новый
-- файл через POST /api/auth/avatar/upload.
--
-- avatar_kind:        'image' | 'gif' | 'video' (NULL = старое или нет аватарки)
-- avatar_path:        относительный путь от freeapi/uploads/, например
--                     'avatars/<uid>.mp4'. NULL когда нет файла.
-- avatar_clip_start:  для video — секунда начала «петли» (0..duration).
-- avatar_clip_end:    для video — секунда конца «петли» (start+0.1..start+10).
--                     Для image/gif оба NULL.
-- avatar_updated_at:  ISO-таймстемп последней загрузки. Используется как
--                     ?v=<ts> в URL — побеждает кэш браузера.
ALTER TABLE users ADD COLUMN avatar_kind TEXT;
ALTER TABLE users ADD COLUMN avatar_path TEXT;
ALTER TABLE users ADD COLUMN avatar_clip_start REAL;
ALTER TABLE users ADD COLUMN avatar_clip_end REAL;
ALTER TABLE users ADD COLUMN avatar_updated_at TEXT;
