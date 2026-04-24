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


# ─────────────────────────────────────────────────────────────────
# E1 — публичный список моделей под Bearer-ключом.
# Внешний ИИ (через system prompt) может подтянуть актуальный
# список доступных моделей, рекомендованные id и default ключа,
# чтобы не передавать неподдерживаемые id (например, gemini-2.5-pro).
# Ответ намеренно лаконичный: без статистики по запросам и без
# tgCallback — это «потребительский» вид, безопасный для клиента.
# ─────────────────────────────────────────────────────────────────

RECOMMENDED_MODEL_IDS = ('gemini-3.0-flash-thinking', 'gemini-3.0-flash')


@bp.get('/api/v1/me')
def v1_me():
    """E2 — самодиагностика для внешнего ИИ.

    Возвращает все полезные «контекстные» поля ключа за один запрос:
    кому он принадлежит, какая модель используется по умолчанию, занят
    ли он, сколько KB контекста уже накопил и где пороги предупреждения
    /лимита. Внешний клиент может вызвать /api/v1/me один раз, понять
    окружение, и потом слать /api/v1/chat без model/без догадок.

    Чувствительные поля наружу не уходят: сам api-key маскируется,
    user_id/key_id не возвращаются.
    """
    key, blocked = authorized_key()
    if blocked:
        return blocked
    from freeapi.security import mask_key as _mask_key
    owner = repo.get_user_by_id(key.get('user_id')) or {}
    stats = repo.get_key_month_stats(key['id'])
    ctx_kb = float(key.get('context_kb') or 0.0)
    return jsonify({
        'key': {
            'name': key.get('name') or '—',
            'masked': _mask_key(key.get('key_value') or ''),
            'default_model': key.get('default_model') or DEFAULT_MODEL_ID,
            'dual_mode': bool(key.get('dual_mode') and key.get('translator_account_id')),
            'context_kb': round(ctx_kb, 1),
            'context_warn_kb': CONTEXT_WARN_KB,
            'context_limit_kb': CONTEXT_LIMIT_KB,
            'context_warn': ctx_kb >= CONTEXT_WARN_KB,
            'limit_hit': bool(key.get('limit_hit')),
            'is_busy': bool(key.get('is_busy')),
            'created_at': key.get('created_at'),
        },
        'owner': {
            'username': owner.get('username') or '—',
            'is_admin': bool(owner and __import__('freeapi.repos.admins', fromlist=['is_admin_user']).is_admin_user(owner.get('id'))),
        },
        'stats': {
            'monthly_requests': stats.get('monthlyRequests', 0),
            'avg_response_ms': stats.get('avgResponseMs', 0),
        },
        'service': {
            'default_model_id': DEFAULT_MODEL_ID,
            'recommended': list(RECOMMENDED_MODEL_IDS),
            'models_endpoint': '/api/v1/models',
        },
    })


@bp.get('/api/v1/models')
def v1_models_list():
    key, blocked = authorized_key()
    if blocked:
        return blocked
    output = []
    for model in AI_MODELS:
        output.append({
            'id': model['id'],
            'displayName': model['displayName'],
            'contextK': model['contextK'],
            'supportsVision': model['supportsVision'],
            'isDefault': model['isDefault'],
            'isPopular': model['isPopular'],
            'isRecommended': model['id'] in RECOMMENDED_MODEL_IDS,
        })
    key_default = key.get('default_model') or DEFAULT_MODEL_ID
    return jsonify({
        'models': output,
        'defaultModelId': DEFAULT_MODEL_ID,
        'keyDefaultModelId': key_default,
        'recommended': list(RECOMMENDED_MODEL_IDS),
    })


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

