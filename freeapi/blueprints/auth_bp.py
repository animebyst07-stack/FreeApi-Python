# Auto-generated blueprint (см. план рефакторинга, шаг 0.2).
# Бизнес-логика не менялась: код перенесён из freeapi/routes.py как есть.
import asyncio
import glob
import json
import logging
import os
import time

from flask import Blueprint, Response, jsonify, request, send_from_directory, session, stream_with_context

from freeapi.config import (
    AVATARS_DIR,
    AVATAR_MAX_BYTES,
    AVATAR_VIDEO_MAX_DURATION,
    UPLOADS_DIR,
)

logger = logging.getLogger('freeapi')

from freeapi import repositories as repo
from freeapi.auth_service import login_user, register_user
from freeapi.memory import (
    parse_tags, process_commands, get_memory, clear_context, clear_favorite,
    estimate_tokens, tokens_to_kb, build_context_warning, format_memory_injection,
    CONTEXT_WARN_KB, CONTEXT_LIMIT_KB,
)
from freeapi.models import AI_MODELS, DEFAULT_MODEL_ID, is_valid_model_id
from freeapi.progress import clear_pending_auth, event_stream, get_pending_auth, get_progress, set_pending_auth, update_progress
from freeapi.security import encrypt_text, generate_api_key, mask_key
from freeapi.tg import run_chat, run_control, run_dual_chat, run_setup_background, send_code_request, sign_in_with_code, switch_model_background

from freeapi.blueprints._helpers import (
    error, current_user_id, support_project_context, require_user,
    bearer_value, authorized_key, fake_stream,
)

bp = Blueprint('auth', __name__)

@bp.post('/api/auth/register')
def auth_register():
    data = request.get_json(silent=True) or {}
    user, err, status = register_user(data.get('username', ''), data.get('password', ''))
    if err:
        return error(err, status)
    session.permanent = True
    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'ok': True, 'user': user}), status


@bp.post('/api/auth/login')
def auth_login():
    data = request.get_json(silent=True) or {}
    user, err, status = login_user(data.get('username', ''), data.get('password', ''))
    if err:
        return error(err, status)
    session.permanent = True
    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'ok': True, 'user': user})


@bp.post('/api/auth/logout')
def auth_logout():
    session.clear()
    return jsonify({'ok': True})


@bp.get('/api/auth/me')
def auth_me():
    if not current_user_id():
        return jsonify({'user': None, 'authenticated': False, 'has_tg_account': False, 'has_keys': False})
    user = repo.get_user_by_id(current_user_id())
    if not user:
        session.clear()
        return error('Сессия недействительна', 401)
    # B-08: расширенный ответ — состояние аккаунта
    uid = current_user_id()
    has_tg = repo.get_ready_tg_account(uid) is not None
    has_keys = len(repo.get_user_keys(uid)) > 0
    # G5: подмешиваем avatar отдельным запросом, чтобы не тащить TEXT-блоб
    # через все остальные обращения к users (get_user_by_id остался лёгким).
    user['avatar'] = repo.get_user_avatar(uid)
    # T10: новое унифицированное поле avatar_media — фронт умеет рендерить
    # image / gif / video с обрезкой и циклом. Для старых аккаунтов с data
    # URL вернётся kind='image' с этим же URL — фронт нарисует <img>.
    user['avatar_media'] = repo.get_user_avatar_media(uid)
    return jsonify({'user': user, 'authenticated': True, 'has_tg_account': has_tg, 'has_keys': has_keys})


# ─── G5: аватарка профиля ────────────────────────────────────────────
# Кадрирование делается на клиенте (квадрат 256x256 JPEG q≈0.78..0.92).
# Сервер только валидирует размер/MIME и сохраняет data URL как есть.

_AVATAR_MAX_BYTES = 200 * 1024          # после base64-decode
_AVATAR_MAX_DATA_URL = 280_000          # длина строки data URL — защита от ОЗУ
_AVATAR_PREFIXES = (
    'data:image/jpeg;base64,',
    'data:image/png;base64,',
)


@bp.put('/api/auth/avatar')
def auth_set_avatar():
    blocked = require_user()
    if blocked:
        return blocked
    uid = current_user_id()
    data = request.get_json(silent=True) or {}
    data_url = data.get('data_url')
    if not isinstance(data_url, str) or not data_url:
        return error('Не указано поле data_url', 400)
    if len(data_url) > _AVATAR_MAX_DATA_URL:
        return error('Аватарка слишком большая', 413)
    if not data_url.startswith(_AVATAR_PREFIXES):
        return error('Поддерживаются только image/jpeg и image/png', 415)
    # Грубая проверка размера: длина base64 * 3/4 ≈ размер в байтах
    try:
        b64 = data_url.split(',', 1)[1]
        approx_size = (len(b64) * 3) // 4
    except Exception:
        return error('Некорректный data URL', 400)
    if approx_size > _AVATAR_MAX_BYTES:
        return error('Аватарка слишком большая (макс. 200 KB)', 413)
    repo.set_user_avatar(uid, data_url)
    logger.info('[AVA_SET_111] user=%s size=%dB', uid, approx_size)
    return jsonify({'ok': True, 'avatar': data_url})


@bp.delete('/api/auth/avatar')
def auth_delete_avatar():
    blocked = require_user()
    if blocked:
        return blocked
    uid = current_user_id()
    # Чистим и legacy data URL, и медиа-файл (если он есть).
    repo.clear_user_avatar(uid)
    _purge_avatar_files(uid)
    repo.clear_user_avatar_media(uid)
    logger.info('[AVA_DEL_112] user=%s', uid)
    return jsonify({'ok': True})


# ─── T10: загрузка/раздача медиа-аватарок (image/gif/video ≤10с) ─────

_AVATAR_KIND_MIME = {
    'image': ('image/jpeg', 'image/png', 'image/webp'),
    'gif':   ('image/gif',),
    'video': ('video/mp4', 'video/webm', 'video/quicktime'),
}
_AVATAR_MIME_EXT = {
    'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp',
    'image/gif': 'gif',
    'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov',
}


def _purge_avatar_files(uid):
    """Удалить ВСЕ файлы этого uid из uploads/avatars/ (любое расширение)."""
    try:
        for old in glob.glob(os.path.join(AVATARS_DIR, uid + '.*')):
            try:
                os.unlink(old)
            except OSError:
                pass
    except Exception:
        pass


@bp.post('/api/auth/avatar/upload')
def auth_avatar_upload():
    """T10: загрузка фото / GIF / короткого видео с обрезкой.

    multipart/form-data:
      file        — бинарник (один)
      kind        — 'image' | 'gif' | 'video'
      clip_start  — секунды начала петли (для video, опционально, default 0)
      clip_end    — секунды конца петли (для video, опционально, default duration)

    Сервер сохраняет файл as-is в freeapi/uploads/avatars/<uid>.<ext>,
    проверяет MIME и размер. Длительность видео не валидируется на бэке
    (нет ffprobe в Termux), но clip_end-clip_start ограничивается
    AVATAR_VIDEO_MAX_DURATION (=10с). Плеер всё равно петляет по этому
    диапазону, поэтому даже если юзер «запихнул» 30-секундное видео —
    фронту покажется только обрезанный фрагмент.
    """
    blocked = require_user()
    if blocked:
        return blocked
    uid = current_user_id()

    f = request.files.get('file')
    kind = (request.form.get('kind') or '').strip().lower()
    if not f:
        return error('Не приложен файл', 400)
    if kind not in _AVATAR_KIND_MIME:
        return error('Неизвестный тип медиа: ' + str(kind), 400)

    mime = (f.mimetype or '').lower()
    if mime not in _AVATAR_KIND_MIME[kind]:
        return error(f'Неподдерживаемый тип файла {mime} для kind={kind}', 415)

    # Читаем в память (лимит уже выставлен в app.config['MAX_CONTENT_LENGTH']),
    # но всё равно подсчитаем size и сравним с per-kind лимитом.
    data = f.read()
    max_bytes = AVATAR_MAX_BYTES.get(kind, 1024 * 1024)
    if len(data) > max_bytes:
        return error(
            f'Файл слишком большой ({len(data)//1024} КБ). '
            f'Максимум для {kind}: {max_bytes//1024} КБ.',
            413,
        )
    if len(data) < 64:
        return error('Файл подозрительно маленький', 400)

    clip_start, clip_end = None, None
    if kind == 'video':
        try:
            cs = float(request.form.get('clip_start') or 0)
            ce = float(request.form.get('clip_end') or 0)
        except ValueError:
            return error('clip_start/clip_end должны быть числами', 400)
        if cs < 0 or ce <= cs:
            return error('clip_end должен быть строго больше clip_start', 400)
        if ce - cs > AVATAR_VIDEO_MAX_DURATION + 0.05:
            return error(
                f'Максимальная длина петли — {AVATAR_VIDEO_MAX_DURATION:g} секунд', 400,
            )
        clip_start, clip_end = cs, ce

    ext = _AVATAR_MIME_EXT.get(mime, 'bin')
    os.makedirs(AVATARS_DIR, exist_ok=True)
    _purge_avatar_files(uid)  # удаляем старые файлы юзера (любые расширения)
    fname = f'{uid}.{ext}'
    fpath = os.path.join(AVATARS_DIR, fname)
    try:
        with open(fpath, 'wb') as out:
            out.write(data)
    except OSError as exc:
        logger.error('[AVA_V2_WRITE_ERR] uid=%s path=%s err=%s', uid, fpath, exc)
        return error('Не удалось сохранить файл на диск', 500)

    rel_path = f'avatars/{fname}'
    repo.set_user_avatar_media(uid, kind, rel_path, clip_start, clip_end)
    media = repo.get_user_avatar_media(uid)
    logger.info(
        '[AVA_V2_SET] uid=%s kind=%s mime=%s size=%dB clip=%s..%s',
        uid, kind, mime, len(data), clip_start, clip_end,
    )
    return jsonify({'ok': True, 'avatar_media': media})


@bp.get('/api/auth/avatar/<uid>')
def auth_avatar_get(uid):
    """Раздача файла аватарки. Публичный URL — кешируется на сутки.

    Для старых аккаунтов (legacy data URL в users.avatar) сюда уже
    никто не зайдёт: фронт получит kind='image' с inline-data URL
    в /api/auth/me.
    """
    rel = repo.get_user_avatar_path(uid)
    if not rel:
        return error('Аватарка не задана', 404)
    full = os.path.join(UPLOADS_DIR, rel)
    if not os.path.isfile(full):
        logger.warning('[AVA_V2_GET_404] uid=%s rel=%s', uid, rel)
        return error('Файл аватарки не найден', 404)
    resp = send_from_directory(
        UPLOADS_DIR, rel,
        max_age=86400, conditional=True,
    )
    # Не индексировать — это пользовательский контент.
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return resp

