"""Репозиторий «Сообщество» (общий чат + посты администраторов).

См. plan.txt блок 2. Все таблицы созданы в миграции 011_community.sql.
Логирование — детальное, потому что отлаживать SQLite-чат через WebView
без логов очень больно.
"""
import json
import logging
import re
from datetime import datetime, timedelta

from freeapi.database import db, row, rows, msk_now, MSK
from freeapi.security import uuid4

logger = logging.getLogger('freeapi')


# ─── ВАЛИДАЦИЯ КАРТИНОК ──────────────────────────────────────────────
# M3.5: лимит поднят с 200 KB до 2.5 MB. Современные смартфонные фото
# весят 1–3 MB после JPEG-сжатия 0.85, и старый лимит молча отбрасывал
# почти всё (логи 25.04: images=0 при попытках прислать фото). Фронт
# дополнительно ужимает картинку через canvas (max сторона 1280, q=0.85),
# но даже без него теперь будет проходить.
MAX_IMG_BYTES = 2_500_000
ALLOWED_IMG_PREFIXES = (
    'data:image/jpeg;base64,',
    'data:image/jpg;base64,',
    'data:image/png;base64,',
    'data:image/webp;base64,',
)
MAX_IMAGES_PER_MESSAGE = 10  # M3.4: согласовано с фронтом (CM_MAX_IMAGES = 10)
MAX_TEXT_LEN = 2000


def _is_valid_image(data_url):
    if not isinstance(data_url, str):
        return False
    if len(data_url) > MAX_IMG_BYTES:
        return False
    head = data_url[:48].lower()
    return any(head.startswith(p) for p in ALLOWED_IMG_PREFIXES)


def _filter_images(raw):
    if not isinstance(raw, list):
        return []
    out = [img for img in raw if _is_valid_image(img)]
    return out[:MAX_IMAGES_PER_MESSAGE]


# ─── УПОМИНАНИЯ @username ────────────────────────────────────────────
_MENTION_RE = re.compile(r'(?:^|[\s])@([A-Za-z0-9_]{2,32})')


def _extract_mention_usernames(text):
    if not text:
        return []
    seen = []
    for m in _MENTION_RE.finditer(text):
        u = m.group(1)
        if u not in seen:
            seen.append(u)
    return seen[:20]


# ─── ОСНОВНЫЕ CRUD ───────────────────────────────────────────────────


def get_chat_ban(user_id):
    """Активный бан в чате или None."""
    if not user_id:
        return None
    now = msk_now()
    with db() as conn:
        r = conn.execute(
            'SELECT user_id, banned_until, reason, banned_by '
            'FROM community_chat_bans WHERE user_id=? AND banned_until > ?',
            (user_id, now),
        ).fetchone()
        return row(r)


def ban_in_chat(user_id, days, reason, banned_by):
    """Забанить юзера в чате на N дней."""
    until = (datetime.now(MSK) + timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
    now = msk_now()
    with db() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO community_chat_bans'
            '(user_id, banned_until, reason, banned_by, created_at) '
            'VALUES (?, ?, ?, ?, ?)',
            (user_id, until, reason, banned_by, now),
        )
        logger.info('[COMMUNITY][BAN] uid=%s days=%s by=%s reason=%r → until %s',
                    user_id, days, banned_by, (reason or '')[:80], until)
        return until


def unban_in_chat(user_id):
    with db() as conn:
        conn.execute('DELETE FROM community_chat_bans WHERE user_id=?', (user_id,))
        logger.info('[COMMUNITY][BAN] removed uid=%s', user_id)


def list_chat_bans():
    now = msk_now()
    with db() as conn:
        return rows(conn.execute(
            'SELECT b.user_id, b.banned_until, b.reason, b.banned_by, b.created_at, '
            '       u.username, bb.username AS banned_by_username '
            'FROM community_chat_bans b '
            'JOIN users u ON u.id = b.user_id '
            'LEFT JOIN users bb ON bb.id = b.banned_by '
            'WHERE b.banned_until > ? '
            'ORDER BY b.created_at DESC',
            (now,),
        ).fetchall())


# ─── СООБЩЕНИЯ ───────────────────────────────────────────────────────


def create_message(user_id, text, kind='message', images=None, mentions=None,
                   reply_to_id=None):
    """Создать новое сообщение/пост. Возвращает полный объект сообщения.

    M3.5: поддержка reply_to_id (Telegram-style ответы). Если указанный
    оригинал не существует / удалён — reply_to_id молча обнуляется,
    чтобы UI не сломался.
    """
    if kind not in ('message', 'admin_post'):
        kind = 'message'
    text = (text or '').strip()
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN]
    images = _filter_images(images)
    if not text and not images:
        raise ValueError('Сообщение пустое')

    msg_id = uuid4()
    now = msk_now()

    # Валидируем reply_to_id: оригинал должен существовать и не быть
    # soft-deleted. На посты (admin_post) отвечать тоже можно.
    if reply_to_id is not None:
        reply_to_id = str(reply_to_id).strip() or None
    if reply_to_id:
        with db() as conn:
            ck = conn.execute(
                'SELECT id FROM community_messages WHERE id=? AND is_deleted=0',
                (reply_to_id,),
            ).fetchone()
            if not ck:
                reply_to_id = None

    with db() as conn:
        conn.execute(
            'INSERT INTO community_messages'
            '(id, user_id, kind, text, is_deleted, created_at, updated_at, reply_to_id) '
            'VALUES (?, ?, ?, ?, 0, ?, ?, ?)',
            (msg_id, user_id, kind, text, now, now, reply_to_id),
        )
        for i, img in enumerate(images):
            conn.execute(
                'INSERT INTO community_message_images(id, message_id, data_url, sort, created_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (uuid4(), msg_id, img, i, now),
            )
        # Mentions: детектим из текста + любые явно переданные ники
        usernames = list(_extract_mention_usernames(text))
        if isinstance(mentions, list):
            for m in mentions[:20]:
                if isinstance(m, str) and m and m not in usernames:
                    usernames.append(m)
        mention_user_ids = []
        if usernames:
            placeholders = ','.join('?' * len(usernames))
            users = conn.execute(
                f'SELECT id, username FROM users WHERE username IN ({placeholders})',
                usernames,
            ).fetchall()
            for u in users:
                if u['id'] == user_id:
                    continue
                mention_user_ids.append((u['id'], u['username']))
                conn.execute(
                    'INSERT INTO community_mentions'
                    '(id, message_id, mentioned_user_id, notified, created_at) '
                    'VALUES (?, ?, ?, 0, ?)',
                    (uuid4(), msg_id, u['id'], now),
                )
        logger.info(
            '[COMMUNITY][NEW] msg=%s uid=%s kind=%s text_len=%s images=%s mentions=%s',
            msg_id, user_id, kind, len(text), len(images),
            [u for _, u in mention_user_ids],
        )

    return get_message(msg_id, viewer_uid=user_id), mention_user_ids


def _load_reply_snippet(conn, reply_to_id):
    """Краткая инфа об оригинале для UI-цитаты Telegram-style.

    Возвращает {id, username, text_snippet, is_deleted}, либо None,
    если оригинал вообще не существует (жёстко удалён GC).
    """
    if not reply_to_id:
        return None
    r = conn.execute(
        'SELECT m.id, m.text, m.is_deleted, m.kind, u.username '
        'FROM community_messages m JOIN users u ON u.id = m.user_id '
        'WHERE m.id=?', (reply_to_id,),
    ).fetchone()
    if not r:
        return None
    snippet = (r['text'] or '').strip().replace('\n', ' ')
    if len(snippet) > 140:
        snippet = snippet[:140].rstrip() + '…'
    if r['is_deleted']:
        snippet = '[удалено]'
    elif not snippet:
        snippet = '[медиа]'
    return {
        'id': r['id'],
        'username': r['username'],
        'text_snippet': snippet,
        'is_deleted': bool(r['is_deleted']),
        'kind': r['kind'],
    }


def get_message(message_id, viewer_uid=None, include_deleted=False):
    """Полный объект сообщения с автором/картинками/реакциями/pin-флагом.

    M3.4: дополнительно возвращаем is_admin автора (учитывая ReZero как
    суперадмина). Нужно фронту, чтобы рисовать дефолтный бейдж «Владелец»
    у админов без своего display_prefix.

    M3.5: возвращаем reply_to (краткий объект цитаты), если сообщение
    является ответом на другое.
    """
    with db() as conn:
        r = conn.execute(
            'SELECT m.*, u.username, u.avatar, u.display_prefix, u.last_seen_at, '
            '       (CASE WHEN u.username = ? '
            '             OR EXISTS(SELECT 1 FROM admins a WHERE a.user_id = u.id) '
            '          THEN 1 ELSE 0 END) AS is_admin '
            'FROM community_messages m '
            'JOIN users u ON u.id = m.user_id '
            'WHERE m.id=?',
            ('ReZero', message_id),
        ).fetchone()
        if not r:
            return None
        if r['is_deleted'] and not include_deleted:
            # Возвращаем «огрызок» с пометкой удаления (для UI плашка)
            deleter = None
            if r['deleted_by']:
                d = conn.execute('SELECT username FROM users WHERE id=?',
                                 (r['deleted_by'],)).fetchone()
                deleter = d['username'] if d else None
            return {
                'id': r['id'],
                'user_id': r['user_id'],
                'username': r['username'],
                'avatar': r['avatar'],
                'display_prefix': r['display_prefix'],
                'is_admin': bool(r['is_admin']),
                'last_seen_at': int(r['last_seen_at'] or 0),
                'kind': r['kind'],
                'is_deleted': 1,
                'deleted_by': r['deleted_by'],
                'deleted_by_username': deleter,
                'deleted_at': r['deleted_at'],
                'created_at': r['created_at'],
                'updated_at': r['updated_at'],
            }
        msg = row(r)
        msg['is_admin'] = bool(r['is_admin'])
        msg['last_seen_at'] = int(r['last_seen_at'] or 0)
        # images
        msg['images'] = [
            x['data_url'] for x in conn.execute(
                'SELECT data_url FROM community_message_images '
                'WHERE message_id=? ORDER BY sort ASC',
                (message_id,),
            ).fetchall()
        ]
        # reactions: {emoji: {count, mine}}
        rx = conn.execute(
            'SELECT emoji, COUNT(*) AS cnt, '
            '       SUM(CASE WHEN user_id=? THEN 1 ELSE 0 END) AS mine '
            'FROM community_reactions WHERE message_id=? GROUP BY emoji',
            (viewer_uid or '', message_id),
        ).fetchall()
        msg['reactions'] = [
            {'emoji': x['emoji'], 'count': int(x['cnt']),
             'mine': bool(int(x['mine'] or 0))}
            for x in rx
        ]
        # pinned?
        p = conn.execute(
            'SELECT pinned_at FROM community_pins WHERE message_id=?',
            (message_id,),
        ).fetchone()
        msg['pinned'] = bool(p)
        msg['pinned_at'] = p['pinned_at'] if p else None
        # versions count (для UI «N правок»)
        v = conn.execute(
            'SELECT COUNT(*) AS cnt FROM community_message_versions WHERE message_id=?',
            (message_id,),
        ).fetchone()
        msg['versions_count'] = int(v['cnt']) if v else 0
        # M3.5: цитата ответа (Telegram-style). reply_to_id есть только
        # после миграции 014 — sqlite-row позволяет .get-style через [].
        reply_to_id = msg.get('reply_to_id') if hasattr(msg, 'get') else None
        if reply_to_id is None:
            try:
                reply_to_id = msg['reply_to_id']
            except (KeyError, IndexError):
                reply_to_id = None
        msg['reply_to'] = _load_reply_snippet(conn, reply_to_id) if reply_to_id else None
        return msg


def list_messages(kind='message', limit=50, before_id=None, viewer_uid=None,
                  include_deleted=False):
    """Лента (хронология DESC по created_at). before_id — для пагинации."""
    sql_parts = ['SELECT m.id FROM community_messages m WHERE m.kind=?']
    params = [kind]
    if not include_deleted:
        sql_parts.append('AND m.is_deleted=0')
    if before_id:
        cur = None
        with db() as conn:
            r = conn.execute(
                'SELECT created_at FROM community_messages WHERE id=?',
                (before_id,),
            ).fetchone()
            if r:
                cur = r['created_at']
        if cur:
            sql_parts.append('AND m.created_at < ?')
            params.append(cur)
    sql_parts.append('ORDER BY m.created_at DESC LIMIT ?')
    params.append(int(limit))
    sql = ' '.join(sql_parts)
    with db() as conn:
        ids = [r['id'] for r in conn.execute(sql, tuple(params)).fetchall()]
    items = [get_message(mid, viewer_uid=viewer_uid, include_deleted=include_deleted)
             for mid in ids]
    return [m for m in items if m]


def list_pinned(viewer_uid=None):
    """Все закрепы (по pinned_at DESC)."""
    with db() as conn:
        ids = [r['message_id'] for r in conn.execute(
            'SELECT message_id FROM community_pins ORDER BY pinned_at DESC'
        ).fetchall()]
    items = [get_message(mid, viewer_uid=viewer_uid) for mid in ids]
    return [m for m in items if m]


def edit_message(message_id, new_text, new_images, edited_by):
    """Правка своего сообщения. Сохраняет версию в community_message_versions."""
    new_text = (new_text or '').strip()
    if len(new_text) > MAX_TEXT_LEN:
        new_text = new_text[:MAX_TEXT_LEN]
    new_images = _filter_images(new_images)
    if not new_text and not new_images:
        raise ValueError('Сообщение пустое')
    now = msk_now()
    with db() as conn:
        m = conn.execute(
            'SELECT text FROM community_messages WHERE id=? AND is_deleted=0',
            (message_id,),
        ).fetchone()
        if not m:
            return None
        old_text = m['text'] or ''
        old_imgs = [x['data_url'] for x in conn.execute(
            'SELECT data_url FROM community_message_images '
            'WHERE message_id=? ORDER BY sort ASC',
            (message_id,),
        ).fetchall()]
        # Сохраняем СТАРУЮ версию
        conn.execute(
            'INSERT INTO community_message_versions'
            '(id, message_id, text, images_json, edited_at, edited_by) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (uuid4(), message_id, old_text, json.dumps(old_imgs), now, edited_by),
        )
        conn.execute(
            'UPDATE community_messages SET text=?, updated_at=? WHERE id=?',
            (new_text, now, message_id),
        )
        # Перезаписываем картинки полностью
        conn.execute('DELETE FROM community_message_images WHERE message_id=?',
                     (message_id,))
        for i, img in enumerate(new_images):
            conn.execute(
                'INSERT INTO community_message_images(id, message_id, data_url, sort, created_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (uuid4(), message_id, img, i, now),
            )
    logger.info('[COMMUNITY][EDIT] msg=%s by=%s old_len=%s new_len=%s old_imgs=%s new_imgs=%s',
                message_id, edited_by, len(old_text), len(new_text),
                len(old_imgs), len(new_images))
    return get_message(message_id, viewer_uid=edited_by)


def soft_delete(message_id, deleted_by):
    """Soft-delete: текст оставляем как историю, на UI — плашка."""
    now = msk_now()
    with db() as conn:
        m = conn.execute(
            'SELECT user_id, kind FROM community_messages WHERE id=? AND is_deleted=0',
            (message_id,),
        ).fetchone()
        if not m:
            return False, None
        # Сохраняем последнюю версию ПЕРЕД удалением
        old_text_row = conn.execute(
            'SELECT text FROM community_messages WHERE id=?', (message_id,)
        ).fetchone()
        old_imgs = [x['data_url'] for x in conn.execute(
            'SELECT data_url FROM community_message_images '
            'WHERE message_id=? ORDER BY sort ASC',
            (message_id,),
        ).fetchall()]
        conn.execute(
            'INSERT INTO community_message_versions'
            '(id, message_id, text, images_json, edited_at, edited_by) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (uuid4(), message_id,
             (old_text_row['text'] or '') + ' [удалено]',
             json.dumps(old_imgs), now, deleted_by),
        )
        conn.execute(
            'UPDATE community_messages SET is_deleted=1, deleted_by=?, deleted_at=?, updated_at=? '
            'WHERE id=?',
            (deleted_by, now, now, message_id),
        )
        # Открепляем, если был закреп
        conn.execute('DELETE FROM community_pins WHERE message_id=?', (message_id,))
    logger.info('[COMMUNITY][DEL] msg=%s by=%s author=%s kind=%s',
                message_id, deleted_by, m['user_id'], m['kind'])
    return True, m['user_id']


def get_message_versions(message_id):
    with db() as conn:
        return rows(conn.execute(
            'SELECT v.*, u.username AS edited_by_username '
            'FROM community_message_versions v '
            'LEFT JOIN users u ON u.id = v.edited_by '
            'WHERE v.message_id=? ORDER BY v.edited_at ASC',
            (message_id,),
        ).fetchall())


# ─── PIN/UNPIN ───────────────────────────────────────────────────────


def pin_message(message_id, pinned_by):
    now = msk_now()
    with db() as conn:
        m = conn.execute(
            'SELECT id FROM community_messages WHERE id=? AND is_deleted=0',
            (message_id,),
        ).fetchone()
        if not m:
            return False
        conn.execute(
            'INSERT OR REPLACE INTO community_pins(message_id, pinned_by, pinned_at) '
            'VALUES (?, ?, ?)',
            (message_id, pinned_by, now),
        )
        logger.info('[COMMUNITY][PIN] msg=%s by=%s', message_id, pinned_by)
        return True


def unpin_message(message_id):
    with db() as conn:
        conn.execute('DELETE FROM community_pins WHERE message_id=?', (message_id,))
        logger.info('[COMMUNITY][UNPIN] msg=%s', message_id)


# ─── REACTIONS ───────────────────────────────────────────────────────


_VALID_EMOJI_LEN = (1, 16)  # на всякий случай — emoji могут быть составные


def toggle_reaction(message_id, user_id, emoji):
    """Установить ОДНУ реакцию пользователя на сообщение (Telegram-style).

    M3.5: раньше было multi-reactions per user — но юзер попросил
    Telegram-style: один юзер = одна реакция на сообщение. Логика:
      - если уже стоит ровно этот emoji → удаляем (тоггл off);
      - если стоит другой emoji ИЛИ ничего → удаляем все старые реакции
        этого юзера на это сообщение и ставим новый.
    Имя функции оставлено `toggle_reaction` для совместимости с роутом.
    """
    emoji = (emoji or '').strip()
    if not emoji or len(emoji) > _VALID_EMOJI_LEN[1]:
        raise ValueError('Некорректный emoji')
    now = msk_now()
    with db() as conn:
        existing = conn.execute(
            'SELECT emoji FROM community_reactions WHERE message_id=? AND user_id=?',
            (message_id, user_id),
        ).fetchall()
        existing_emojis = [x['emoji'] for x in existing]
        # Чистим все старые реакции этого юзера на это сообщение —
        # это нормализует случай, когда в БД остались множественные
        # записи от старой логики до миграции на single-reaction.
        if existing_emojis:
            conn.execute(
                'DELETE FROM community_reactions WHERE message_id=? AND user_id=?',
                (message_id, user_id),
            )
        if existing_emojis == [emoji]:
            action = 'removed'  # повторный клик по той же = снять
        else:
            conn.execute(
                'INSERT INTO community_reactions(message_id, user_id, emoji, created_at) '
                'VALUES (?, ?, ?, ?)',
                (message_id, user_id, emoji, now),
            )
            action = 'added' if not existing_emojis else 'replaced'
        logger.info('[COMMUNITY][REACT] msg=%s uid=%s emoji=%r %s (was=%r)',
                    message_id, user_id, emoji, action, existing_emojis)


# ─── ПОИСК ЛЮДЕЙ ДЛЯ @-АВТОКОМПЛИТА ──────────────────────────────────


def lookup_users_by_prefix(prefix, limit=8):
    prefix = (prefix or '').strip()
    if not prefix:
        return []
    with db() as conn:
        return rows(conn.execute(
            'SELECT id, username, avatar FROM users '
            'WHERE username LIKE ? ORDER BY username ASC LIMIT ?',
            (prefix + '%', int(limit)),
        ).fetchall())


# ─── GC ──────────────────────────────────────────────────────────────


def gc_old_soft_deleted(days=30):
    """Жёстко удаляем soft-deleted сообщения старше N дней (вместе с версиями
    и картинками — по ON DELETE CASCADE)."""
    cutoff = (datetime.now(MSK) - timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
    with db() as conn:
        cur = conn.execute(
            'DELETE FROM community_messages WHERE is_deleted=1 AND deleted_at < ?',
            (cutoff,),
        )
        n = cur.rowcount or 0
    if n:
        logger.info('[COMMUNITY][GC] hard-deleted %s soft-deleted messages older than %sd',
                    n, days)
    return n


# ─── MENTIONS ────────────────────────────────────────────────────────


def get_unnotified_mentions(message_id):
    with db() as conn:
        return rows(conn.execute(
            'SELECT id, mentioned_user_id FROM community_mentions '
            'WHERE message_id=? AND notified=0',
            (message_id,),
        ).fetchall())


def mark_mention_notified(mention_id):
    with db() as conn:
        conn.execute('UPDATE community_mentions SET notified=1 WHERE id=?', (mention_id,))


def set_mute_mentions(user_id, value):
    val = 1 if value else 0
    with db() as conn:
        conn.execute('UPDATE users SET notif_mute_mentions=? WHERE id=?', (val, user_id))
    logger.info('[COMMUNITY][MUTE] uid=%s mute=%s', user_id, val)


def get_mute_mentions(user_id):
    with db() as conn:
        r = conn.execute('SELECT notif_mute_mentions FROM users WHERE id=?',
                         (user_id,)).fetchone()
        return bool(int(r['notif_mute_mentions'] or 0)) if r else False
