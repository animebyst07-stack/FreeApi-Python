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
    return jsonify({'user': user, 'authenticated': True, 'has_tg_account': has_tg, 'has_keys': has_keys})

