import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _resolve_db():
    raw = os.environ.get('DATABASE_PATH', 'database.db')
    p = Path(raw)
    if not p.is_absolute():
        return str(_ROOT / p)
    return raw


DATABASE_PATH = _resolve_db()
SESSION_SECRET = os.environ.get('SESSION_SECRET', 'change-me-in-production')
SAM_BOT_USERNAME = os.environ.get('SAM_BOT_USERNAME', 'SamGPTrobot')
DEFAULT_MODEL_ID = 'gemini-3.0-flash-thinking'
REQUEST_TIMEOUT_SECONDS = int(os.environ.get('REQUEST_TIMEOUT_SECONDS', '600'))
BOT_QUIET_SECONDS = float(os.environ.get('BOT_QUIET_SECONDS', '3.0'))

# T10: загрузка медиа-файлов аватарок (image/gif/video ≤10с).
# Файлы хранятся на диске рядом с пакетом, отдаются через
# GET /api/auth/avatar/<uid>?v=<ts>. URL клиентский, ts = avatar_updated_at,
# нужен только для cache-busting.
UPLOADS_DIR = str(_ROOT / 'freeapi' / 'uploads')
AVATARS_DIR = str(Path(UPLOADS_DIR) / 'avatars')
# Лимиты по kind (заранее, чтобы отбивать гигантские файлы до полного чтения).
AVATAR_MAX_BYTES = {
    'image': 1 * 1024 * 1024,   # 1 MB — JPEG/PNG/WebP кадрированный
    'gif':   3 * 1024 * 1024,   # 3 MB — GIF без перекодировки
    'video': 6 * 1024 * 1024,   # 6 MB — короткое видео ≤10с
}
AVATAR_VIDEO_MAX_DURATION = 10.0  # секунд (валидация на клиенте + бэке)
