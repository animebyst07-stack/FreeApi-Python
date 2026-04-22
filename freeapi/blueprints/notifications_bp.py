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

@bp.post('/api/notifications/read_all')
def mark_all_notifs_read():
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    cnt = repo.mark_all_notifications_read(uid)
    logger.info('[NOTIF] read_all uid=%s updated=%s', uid, cnt)
    return jsonify({'ok': True, 'updated': cnt})


@bp.get('/api/notifications')
def get_notifications():
    err = require_user()
    if err:
        return err
    items = repo.get_user_notifications(current_user_id())
    unread = repo.count_unread_notifications(current_user_id())
    return jsonify({'notifications': items, 'unread': unread})


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

