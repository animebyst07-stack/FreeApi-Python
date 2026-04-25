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
    """Найти пользователя по username.

    Селектим явный список колонок (включая password_hash и display_prefix),
    чтобы login_user мог проверить пароль, а UI получал префикс.
    Раньше в файле было ДВА определения этой функции — второе (ниже по
    файлу) перезатирало первое и не возвращало password_hash, из-за чего
    POST /api/auth/login падал с KeyError: 'password_hash' и сессия
    никогда не выставлялась («вход вроде есть, а юзер гость»).
    """
    with db() as conn:
        r = conn.execute(
            'SELECT id, username, password_hash, display_prefix, '
            'created_at, last_login_at FROM users WHERE username = ?',
            (username,),
        ).fetchone()
        return row(r) if r else None


def get_user_by_id(user_id):
    with db() as conn:
        return row(conn.execute(
            'SELECT id, username, display_prefix, created_at, last_login_at '
            'FROM users WHERE id = ?',
            (user_id,),
        ).fetchone())


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


# ─── T10: расширенные аватарки (image/gif/video с обрезкой) ──────────
# Новые колонки avatar_kind/avatar_path/avatar_clip_start/avatar_clip_end
# хранят медиа-файл на диске. Старая колонка avatar (data URL) тоже
# остаётся валидным источником и читается как kind='image'.

_AVATAR_COLS = (
    'avatar', 'avatar_kind', 'avatar_path',
    'avatar_clip_start', 'avatar_clip_end', 'avatar_updated_at',
)


def _row_to_avatar(uid, r):
    """Внутренний конвертер sqlite-row → payload для UI.

    Приоритет: новый файл (avatar_kind+avatar_path) > старый data URL.
    Возвращает None, если у юзера ничего нет.
    """
    if r is None:
        return None
    kind = r['avatar_kind'] if 'avatar_kind' in r.keys() else None
    path = r['avatar_path'] if 'avatar_path' in r.keys() else None
    if kind in ('image', 'gif', 'video') and path:
        ts = r['avatar_updated_at'] if 'avatar_updated_at' in r.keys() else ''
        ver = (ts or '').replace(' ', '_').replace(':', '') or '1'
        return {
            'kind': kind,
            'url': f'/api/auth/avatar/{uid}?v={ver}',
            'clip_start': r['avatar_clip_start'] if 'avatar_clip_start' in r.keys() else None,
            'clip_end':   r['avatar_clip_end']   if 'avatar_clip_end'   in r.keys() else None,
        }
    legacy = r['avatar'] if 'avatar' in r.keys() else None
    if legacy:
        return {'kind': 'image', 'url': legacy, 'clip_start': None, 'clip_end': None}
    return None


def get_user_avatar_media(user_id):
    """Полный payload медиа-аватарки для /api/auth/me и серверной логики.

    Возвращает dict {kind, url, clip_start, clip_end} либо None.
    """
    with db() as conn:
        r = conn.execute(
            f'SELECT {", ".join(_AVATAR_COLS)} FROM users WHERE id=?',
            (user_id,),
        ).fetchone()
        return _row_to_avatar(user_id, r)


def build_avatar_media(user_id, row_like):
    """Сериализатор для случаев, когда колонки уже выбраны JOIN-ом.

    row_like — sqlite Row или dict с ключами avatar/avatar_kind/avatar_path/
    avatar_clip_start/avatar_clip_end/avatar_updated_at. Если каких-то нет —
    функция отдаст результат по тому, что есть (legacy data URL → image).
    """
    return _row_to_avatar(user_id, row_like)


def set_user_avatar_media(user_id, kind, rel_path, clip_start=None, clip_end=None):
    """Сохранить путь к медиа-файлу. Старый legacy data URL обнуляется.

    rel_path — относительный путь от UPLOADS_DIR (например 'avatars/<uid>.mp4').
    """
    now = msk_now()
    with db() as conn:
        conn.execute(
            'UPDATE users SET avatar=NULL, avatar_kind=?, avatar_path=?, '
            'avatar_clip_start=?, avatar_clip_end=?, avatar_updated_at=? '
            'WHERE id=?',
            (kind, rel_path, clip_start, clip_end, now, user_id),
        )


def clear_user_avatar_media(user_id):
    """Полный сброс — и legacy avatar, и новые поля."""
    with db() as conn:
        conn.execute(
            'UPDATE users SET avatar=NULL, avatar_kind=NULL, avatar_path=NULL, '
            'avatar_clip_start=NULL, avatar_clip_end=NULL, avatar_updated_at=NULL '
            'WHERE id=?',
            (user_id,),
        )


def get_user_avatar_path(user_id):
    """Только относительный путь файла для send_from_directory."""
    with db() as conn:
        r = conn.execute(
            'SELECT avatar_path FROM users WHERE id=?',
            (user_id,),
        ).fetchone()
        return r['avatar_path'] if r and r['avatar_path'] else None


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


def set_display_prefix(user_id, prefix):
    """Установить или убрать display_prefix у пользователя."""
    prefix = (prefix or '').strip()[:30] or None  # макс. 30 символов, None = убрать
    with db() as conn:
        conn.execute(
            'UPDATE users SET display_prefix=? WHERE id=?',
            (prefix, user_id),
        )
    return prefix
