# Auto-generated blueprint (см. план рефакторинга, шаг 0.2).
# Бизнес-логика не менялась: код перенесён из freeapi/routes.py как есть.
import asyncio
import json
import logging
import os
import time

from flask import Blueprint, Response, jsonify, request, session, stream_with_context

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
    repo.clear_user_avatar(uid)
    logger.info('[AVA_DEL_112] user=%s', uid)
    return jsonify({'ok': True})

