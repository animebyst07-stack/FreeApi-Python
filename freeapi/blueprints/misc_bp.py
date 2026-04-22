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

bp = Blueprint('misc', __name__)

@bp.get('/api/healthz')
def health():
    return jsonify({'status': 'ok'})

# ─────────────────────────────────────────────────────────────────
# Клиентский логгер: фронтенд шлёт сюда события, чтобы они появились
# в Termux-консоли через стандартный logger ('freeapi'). Используется
# для глубокой диагностики (например, окно прикрепления фото к отзыву).
# ─────────────────────────────────────────────────────────────────

@bp.post('/api/_clog')
def client_log():
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    tag = str(data.get('tag') or 'CLIENT')[:40]
    msg = str(data.get('msg') or '')[:2000]
    level = str(data.get('level') or 'info').lower()
    try:
        uid = current_user_id() or '-'
    except Exception:
        uid = '-'
    ua = (request.headers.get('User-Agent') or '')[:120]
    line = '[CLIENT][%s] uid=%s ua=%s :: %s' % (tag, uid, ua, msg)
    if level == 'error':
        logger.error(line)
    elif level == 'warn':
        logger.warning(line)
    else:
        logger.info(line)
    return jsonify({'ok': True})


@bp.get('/api/models')
def models_list():
    stats = {item['model_id']: item for item in repo.get_model_stats()}
    output = []
    for model in AI_MODELS:
        row = stats.get(model['id']) or {}
        output.append({'id': model['id'], 'displayName': model['displayName'], 'contextK': model['contextK'], 'supportsVision': model['supportsVision'], 'isDefault': model['isDefault'], 'isPopular': model['isPopular'], 'avgResponseMs': row.get('avg_response_ms'), 'totalRequests': row.get('total_requests', 0)})
    return jsonify({'models': output})


@bp.get('/api/stats/global')
def stats_global():
    return jsonify(repo.get_global_stats())


@bp.get('/api/stats/keys/<key_id>')
def stats_key(key_id):
    blocked = require_user()
    if blocked:
        return blocked
    key = repo.get_user_key(current_user_id(), key_id)
    if not key:
        return error('Ключ не найден', 404)
    return jsonify(repo.get_key_month_stats(key_id))


@bp.get('/api/log-codes')
def log_codes():
    return jsonify({'codes': repo.get_log_codes()})

