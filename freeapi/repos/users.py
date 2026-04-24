"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


def create_user(username, password_hash):
    user_id = uuid4()
    now = msk_now()
    with db() as conn:
        conn.execute('INSERT INTO users(id, username, password_hash, created_at) VALUES (?, ?, ?, ?)', (user_id, username, password_hash, now))
        return row(conn.execute('SELECT id, username, created_at, last_login_at FROM users WHERE id = ?', (user_id,)).fetchone())


def get_user_by_username(username):
    with db() as conn:
        return row(conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone())


def get_user_by_id(user_id):
    with db() as conn:
        return row(conn.execute('SELECT id, username, created_at, last_login_at FROM users WHERE id = ?', (user_id,)).fetchone())


def touch_login(user_id):
    now = msk_now()
    with db() as conn:
        conn.execute('UPDATE users SET last_login_at = ? WHERE id = ?', (now, user_id))


# ─── G5: аватарка профиля ─────────────────────────────────────────────
# Хранится как data URL прямо в users.avatar. В get_user_by_* поле НЕ
# выбирается (тяжёлое), только в явных хелперах ниже.

def get_user_avatar(user_id):
    """Вернуть data URL аватарки или None."""
    with db() as conn:
        r = conn.execute('SELECT avatar FROM users WHERE id = ?', (user_id,)).fetchone()
        return r[0] if r and r[0] else None


def set_user_avatar(user_id, data_url):
    """Сохранить data URL аватарки (валидация — на уровне роута)."""
    with db() as conn:
        conn.execute('UPDATE users SET avatar = ? WHERE id = ?', (data_url, user_id))


def clear_user_avatar(user_id):
    """Сбросить аватарку (NULL)."""
    with db() as conn:
        conn.execute('UPDATE users SET avatar = NULL WHERE id = ?', (user_id,))


# ─── M3: TG-уведомления о @упоминаниях ──────────────────────────────
# Связь юзер→чат с ботом:
#   • tg_notify_chat_id   — числовой chat_id личного диалога с TG_NOTIFY_TOKEN-ботом.
#   • tg_notify_link_token — одноразовый UUID для deep-link привязки через /start <token>.
#   • tg_notify_linked_at  — момент привязки.
# Логика: фронт зовёт GET /api/community/tg_link → бэкенд при необходимости
# генерирует токен, отдаёт ссылку t.me/<bot>?start=<token>. Юзер переходит,
# бот через getUpdates ловит /start, scheduler матчит токен с users.tg_notify_link_token,
# записывает chat_id и обнуляет токен. Альтернатива — ручная привязка по chat_id.

def get_user_tg_notify(user_id):
    """Полный объект состояния привязки (для UI)."""
    with db() as conn:
        r = conn.execute(
            'SELECT tg_notify_chat_id, tg_notify_link_token, tg_notify_linked_at '
            'FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        if not r:
            return None
        return {
            'chat_id': r['tg_notify_chat_id'],
            'link_token': r['tg_notify_link_token'],
            'linked_at': r['tg_notify_linked_at'],
        }


def get_tg_notify_chat_id(user_id):
    with db() as conn:
        r = conn.execute(
            'SELECT tg_notify_chat_id FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        return r['tg_notify_chat_id'] if r and r['tg_notify_chat_id'] else None


def set_tg_notify_chat_id(user_id, chat_id):
    """Привязать chat_id и сбросить link_token (одноразовый)."""
    now = msk_now()
    with db() as conn:
        conn.execute(
            'UPDATE users SET tg_notify_chat_id=?, tg_notify_link_token=NULL, '
            'tg_notify_linked_at=? WHERE id=?',
            (str(chat_id), now, user_id),
        )


def set_tg_notify_link_token(user_id, token):
    """Записать одноразовый токен для deep-link привязки."""
    with db() as conn:
        conn.execute(
            'UPDATE users SET tg_notify_link_token=? WHERE id=?',
            (token, user_id),
        )


def find_user_by_tg_link_token(token):
    """Найти юзера по link_token (для обработчика /start <token>)."""
    if not token:
        return None
    with db() as conn:
        r = conn.execute(
            'SELECT id, username FROM users WHERE tg_notify_link_token=?',
            (token,),
        ).fetchone()
        return row(r) if r else None


def clear_tg_notify(user_id):
    """Полностью отвязать TG-уведомления у юзера."""
    with db() as conn:
        conn.execute(
            'UPDATE users SET tg_notify_chat_id=NULL, tg_notify_link_token=NULL, '
            'tg_notify_linked_at=NULL WHERE id=?',
            (user_id,),
        )
