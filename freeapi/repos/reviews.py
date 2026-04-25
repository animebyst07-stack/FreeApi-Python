"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


def _attach_avatar_media(items):
    """T10: после rows() добавляем avatar_media каждому отзыву.

    items — список dict (после row()/rows()). Каждый элемент должен содержать
    user_id и поля u.avatar*/u.avatar_kind/* (мы их выбрали в SELECT).
    """
    if not items:
        return items
    from freeapi.repos.users import build_avatar_media
    for it in items:
        uid = it.get('user_id') or ''
        it['avatar_media'] = build_avatar_media(uid, it)
    return items


def _count_week_edits(edit_timestamps_json):
    """Считает количество правок за последние 7 дней из JSON-списка timestamp строк."""
    import json as _json
    from datetime import datetime, timezone, timedelta
    try:
        ts_list = _json.loads(edit_timestamps_json or '[]')
        if not isinstance(ts_list, list):
            ts_list = []
    except Exception:
        ts_list = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return [t for t in ts_list if isinstance(t, str) and t >= cutoff], len([t for t in ts_list if isinstance(t, str) and t >= cutoff])


def _add_edit_timestamp(edit_timestamps_json):
    """Добавляет текущий timestamp в список и возвращает обновлённый JSON."""
    import json as _json
    from datetime import datetime, timezone, timedelta
    try:
        ts_list = _json.loads(edit_timestamps_json or '[]')
        if not isinstance(ts_list, list):
            ts_list = []
    except Exception:
        ts_list = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    ts_list = [t for t in ts_list if isinstance(t, str) and t >= cutoff]
    ts_list.append(datetime.now(timezone.utc).isoformat())
    return _json.dumps(ts_list)


def get_week_edits(user_id):
    """Возвращает количество правок текущего пользователя за последние 7 дней."""
    with db() as conn:
        r = conn.execute('SELECT edit_timestamps FROM reviews WHERE user_id=?', (user_id,)).fetchone()
        if not r:
            return 0
        _, cnt = _count_week_edits(r['edit_timestamps'] if r['edit_timestamps'] is not None else '[]')
        return cnt


def create_review(user_id, score, text, status='pending', images=None, is_admin=False):
    import json as _json
    review_id = uuid4()
    now = msk_now()
    images_json = _json.dumps(images or [])
    with db() as conn:
        existing = conn.execute('SELECT id, edit_timestamps FROM reviews WHERE user_id = ?', (user_id,)).fetchone()
        if existing:
            old_ts = existing['edit_timestamps'] if existing['edit_timestamps'] is not None else '[]'
            new_ts = _add_edit_timestamp(old_ts)
            conn.execute(
                'UPDATE reviews SET score=?, text=?, status=?, ai_response=NULL, reply_by=?, images=?, edit_timestamps=?, updated_at=? WHERE user_id=?',
                (score, text, status, 'ai', images_json, new_ts, now, user_id)
            )
            return row(conn.execute('SELECT * FROM reviews WHERE user_id = ?', (user_id,)).fetchone())
        conn.execute(
            'INSERT INTO reviews(id, user_id, score, text, status, images, edit_timestamps, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (review_id, user_id, score, text, status, images_json, '[]', now, now)
        )
        return row(conn.execute('SELECT * FROM reviews WHERE id = ?', (review_id,)).fetchone())


def get_review_by_user(user_id):
    with db() as conn:
        r = row(conn.execute('SELECT * FROM reviews WHERE user_id = ?', (user_id,)).fetchone())
        if r:
            _, cnt = _count_week_edits(r.get('edit_timestamps') or '[]')
            r['week_edits'] = cnt
        return r


def _enrich_reviews_with_likes(conn, items, viewer_uid=None):
    """Добавляет поля likes, dislikes, user_value к каждому отзыву."""
    if not items:
        return items
    ids = [r['id'] for r in items]
    placeholders = ','.join('?' * len(ids))
    like_rows = conn.execute(
        f'SELECT review_id, value, user_id FROM review_likes WHERE review_id IN ({placeholders})',
        ids
    ).fetchall()
    likes_map = {}
    dislikes_map = {}
    user_map = {}
    for lr in like_rows:
        rid = lr['review_id']
        v = lr['value']
        uid = lr['user_id']
        if v == 1:
            likes_map[rid] = likes_map.get(rid, 0) + 1
        elif v == -1:
            dislikes_map[rid] = dislikes_map.get(rid, 0) + 1
        if viewer_uid and uid == viewer_uid:
            user_map[rid] = v
    for r in items:
        rid = r['id']
        r['likes'] = likes_map.get(rid, 0)
        r['dislikes'] = dislikes_map.get(rid, 0)
        r['user_like'] = user_map.get(rid, 0) if viewer_uid else 0
    return items


def get_approved_reviews(limit=10, offset=0, viewer_uid=None):
    with db() as conn:
        total_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM reviews WHERE status IN ('approved', 'flagged')"
        ).fetchone()
        total = total_row['cnt'] if total_row else 0
        items = rows(conn.execute(
            'SELECT r.id, r.score, r.text, r.ai_response, r.images, r.admin_images, r.reply_by, r.created_at, r.updated_at, r.status, '
            '       r.user_id, u.username, u.avatar, u.avatar_kind, u.avatar_path, '
            '       u.avatar_clip_start, u.avatar_clip_end, u.avatar_updated_at '
            'FROM reviews r JOIN users u ON r.user_id = u.id '
            "WHERE r.status IN ('approved', 'flagged') ORDER BY r.updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall())
        items = _enrich_reviews_with_likes(conn, items, viewer_uid)
        _attach_avatar_media(items)
        return items, total


def get_avg_review_score():
    """Возвращает средний рейтинг всех одобренных отзывов, округлённый до 1 знака."""
    with db() as conn:
        r = conn.execute(
            "SELECT ROUND(AVG(score), 1) AS avg FROM reviews WHERE status IN ('approved', 'flagged')"
        ).fetchone()
        if r and r['avg'] is not None:
            return float(r['avg'])
        return None


def get_pending_reviews():
    with db() as conn:
        items = rows(conn.execute(
            'SELECT r.*, u.username, u.avatar, u.avatar_kind, u.avatar_path, '
            '       u.avatar_clip_start, u.avatar_clip_end, u.avatar_updated_at '
            'FROM reviews r JOIN users u ON r.user_id = u.id '
            "WHERE r.status = 'pending' ORDER BY r.created_at ASC"
        ).fetchall())
        return _attach_avatar_media(items)


def get_all_reviews_admin(limit=10, offset=0):
    with db() as conn:
        total_row = conn.execute('SELECT COUNT(*) AS cnt FROM reviews').fetchone()
        total = total_row['cnt'] if total_row else 0
        items = rows(conn.execute(
            'SELECT r.*, u.username, u.avatar, u.avatar_kind, u.avatar_path, '
            '       u.avatar_clip_start, u.avatar_clip_end, u.avatar_updated_at '
            'FROM reviews r JOIN users u ON r.user_id = u.id ORDER BY r.created_at DESC LIMIT ? OFFSET ?',
            (limit, offset)
        ).fetchall())
        _attach_avatar_media(items)
        return items, total


def update_review_status(review_id, status, ai_response=None, admin_images=None, reply_by='ai'):
    import json as _json
    now = msk_now()
    with db() as conn:
        if admin_images is not None:
            admin_images_json = _json.dumps(admin_images)
            conn.execute(
                'UPDATE reviews SET status=?, ai_response=?, admin_images=?, reply_by=?, updated_at=? WHERE id=?',
                (status, ai_response, admin_images_json, reply_by, now, review_id)
            )
        else:
            conn.execute(
                'UPDATE reviews SET status=?, ai_response=?, reply_by=?, updated_at=? WHERE id=?',
                (status, ai_response, reply_by, now, review_id)
            )
        return row(conn.execute('SELECT * FROM reviews WHERE id=?', (review_id,)).fetchone())


def delete_review(review_id):
    with db() as conn:
        conn.execute('DELETE FROM reviews WHERE id=?', (review_id,))


# ─────────── REVIEW LIKES ───────────


def upsert_review_like(review_id, user_id, value):
    """Лайк/дизлайк. Если value совпадает с текущим — убирает (toggle). Возвращает {likes, dislikes, user_like}."""
    now = msk_now()
    with db() as conn:
        existing = conn.execute(
            'SELECT value FROM review_likes WHERE review_id=? AND user_id=?',
            (review_id, user_id)
        ).fetchone()
        if existing and existing['value'] == value:
            conn.execute('DELETE FROM review_likes WHERE review_id=? AND user_id=?', (review_id, user_id))
            user_like = 0
        else:
            conn.execute(
                'INSERT OR REPLACE INTO review_likes(review_id, user_id, value, created_at) VALUES (?,?,?,?)',
                (review_id, user_id, value, now)
            )
            user_like = value
        likes = conn.execute(
            'SELECT COUNT(*) AS cnt FROM review_likes WHERE review_id=? AND value=1', (review_id,)
        ).fetchone()['cnt']
        dislikes = conn.execute(
            'SELECT COUNT(*) AS cnt FROM review_likes WHERE review_id=? AND value=-1', (review_id,)
        ).fetchone()['cnt']
    return {'likes': likes, 'dislikes': dislikes, 'user_like': user_like}


def get_user_ban(user_id):
    now = msk_now()
    with db() as conn:
        r = conn.execute(
            "SELECT banned_until, reason FROM review_restrictions WHERE user_id=? AND banned_until > ?",
            (user_id, now)
        ).fetchone()
        return row(r)


def restrict_review_access(user_id, banned_until, reason):
    now = msk_now()
    with db() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO review_restrictions(user_id, banned_until, reason, created_at) VALUES (?, ?, ?, ?)',
            (user_id, banned_until, reason, now)
        )


# ─────────── USER NOTIFICATIONS ───────────
