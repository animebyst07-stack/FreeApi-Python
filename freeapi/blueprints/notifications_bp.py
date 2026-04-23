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

bp = Blueprint('notifications', __name__)

_VALID_NOTIF_KINDS = ('review', 'support', 'system')


def _norm_kind_arg(raw):
    """Возвращает нормализованный kind либо None (если фильтр не задан/некорректен)."""
    if not raw:
        return None
    raw = str(raw).strip().lower()
    if raw in ('all', '*', ''):
        return None
    return raw if raw in _VALID_NOTIF_KINDS else None


@bp.post('/api/notifications/read_all')
def mark_all_notifs_read():
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    kind = _norm_kind_arg(request.args.get('kind') or (request.get_json(silent=True) or {}).get('kind'))
    cnt = repo.mark_all_notifications_read(uid, kind=kind)
    logger.info('[NOTIF] read_all uid=%s kind=%s updated=%s', uid, kind, cnt)
    return jsonify({'ok': True, 'updated': cnt, 'kind': kind or 'all'})


@bp.get('/api/notifications')
def get_notifications():
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    kind = _norm_kind_arg(request.args.get('kind'))
    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 200))
    except Exception:
        limit = 50
    try:
        offset = max(0, int(request.args.get('offset', 0)))
    except Exception:
        offset = 0
    items = repo.get_user_notifications(uid, kind=kind, limit=limit, offset=offset)
    unread_breakdown = repo.count_unread_notifications_by_kind(uid)
    # Совместимость: поле 'unread' оставляем числом (общий счётчик), плюс новый объект 'unread_by_kind'.
    return jsonify({
        'notifications': items,
        'unread': unread_breakdown.get('all', 0),
        'unread_by_kind': unread_breakdown,
        'kind': kind or 'all',
    })


@bp.post('/api/notifications/<notif_id>/read')
def mark_notif_read(notif_id):
    err = require_user()
    if err:
        return err
    repo.mark_notification_read(notif_id, current_user_id())
    return jsonify({'ok': True})


@bp.delete('/api/notifications/<notif_id>')
def delete_notif(notif_id):
    err = require_user()
    if err:
        return err
    repo.delete_user_notification(notif_id, current_user_id())
    return jsonify({'deleted': True})

# ═══════════════════════════════════════════════
#  ADMIN PANEL (только ReZero)
# ═══════════════════════════════════════════════

