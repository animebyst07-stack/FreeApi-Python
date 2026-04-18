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
