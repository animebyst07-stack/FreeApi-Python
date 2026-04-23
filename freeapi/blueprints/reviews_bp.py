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

bp = Blueprint('reviews', __name__)

@bp.get('/api/reviews')
def get_reviews():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    limit = 10
    offset = (page - 1) * limit
    viewer_uid = current_user_id()
    items, total = repo.get_approved_reviews(limit=limit, offset=offset, viewer_uid=viewer_uid)
    avg_score = repo.get_avg_review_score()
    return jsonify({
        'reviews': items,
        'total': total,
        'page': page,
        'pages': max(1, (total + limit - 1) // limit),
        'avg_score': avg_score,
    })


@bp.get('/api/reviews/mine')
def get_my_review():
    err = require_user()
    if err:
        return err
    review = repo.get_review_by_user(current_user_id())
    return jsonify({'review': review})


@bp.post('/api/reviews')
def submit_review():
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    user = repo.get_user_by_id(uid)
    if not user:
        return error('Пользователь не найден', 404)
    is_admin = user['username'] == 'ReZero'
    ban = repo.get_user_ban(uid) if not is_admin else None
    if ban and ban.get('banned_until'):
        return error(f'Вы не можете оставлять отзывы до {ban["banned_until"]}', 403)
    data = request.get_json(silent=True) or {}
    try:
        score = int(data.get('score'))
    except (TypeError, ValueError):
        score = 0
    text = (data.get('text') or '').strip()
    raw_images = data.get('images') or []
    is_edit = bool(repo.get_review_by_user(uid))
    logger.info('[REVIEWS] POST /api/reviews uid=%s score=%s text_len=%s images_in=%s is_edit=%s body_size=%s',
                uid, score, len(text), (len(raw_images) if isinstance(raw_images, list) else 'not_list'),
                is_edit, request.content_length)
    # Лимит редактирований: 3 в 7 дней (не для владельца)
    if is_edit and not is_admin:
        week_edits = repo.get_week_edits(uid)
        logger.info('[REVIEWS] редактирование uid=%s week_edits=%s', uid, week_edits)
        if week_edits >= 3:
            logger.warning('[REVIEWS] лимит правок исчерпан uid=%s week_edits=%s', uid, week_edits)
            return error('Лимит редактирований исчерпан: не более 3 правок в 7 дней', 429)
    if score < 1 or score > 10:
        logger.warning('[REVIEWS] отклонён: невалидная оценка score=%s uid=%s', score, uid)
        return error('Оценка должна быть числом от 1 до 10', 400)
    if not text or len(text) < 10:
        logger.warning('[REVIEWS] отклонён: текст слишком короткий len=%s uid=%s', len(text), uid)
        return error('Текст отзыва слишком короткий (минимум 10 символов)', 400)
    if len(text) > 1000:
        logger.warning('[REVIEWS] отклонён: текст слишком длинный len=%s uid=%s', len(text), uid)
        return error('Текст отзыва слишком длинный (максимум 1000 символов)', 400)
    images = raw_images
    if not isinstance(images, list):
        images = []
    MAX_IMG_B64 = 7 * 1024 * 1024
    ALLOWED_IMG_MIME = ('data:image/jpeg;base64,', 'data:image/jpg;base64,', 'data:image/png;base64,', 'data:image/gif;base64,', 'data:image/webp;base64,', 'data:image/heic;base64,', 'data:image/heif;base64,')
    def _is_valid_img(img):
        if not isinstance(img, str): return False
        if len(img) > MAX_IMG_B64: return False
        lower = img[:40].lower()
        return any(lower.startswith(m) for m in ALLOWED_IMG_MIME)
    before = len(images)
    images = [img for img in images if _is_valid_img(img)]
    if len(images) != before:
        logger.warning('[REVIEWS] отфильтровано невалидных картинок: %s (осталось %s) uid=%s',
                       before - len(images), len(images), uid)
    images = images[:10]
    logger.info('[REVIEWS] финально к сохранению: score=%s images=%s uid=%s', score, len(images), uid)
    # FIX: UI «Модератор отзывов» сохраняет настройки в moderator_*; старые
    # ключи agent_* остаются как fallback для совместимости. Без этого новый
    # отзыв всегда создавался как approved и AI-модерация не срабатывала.
    _mod_enabled = repo.get_admin_setting('moderator_enabled', repo.get_admin_setting('agent_enabled', '0'))
    _mod_key_id  = repo.get_admin_setting('moderator_key_id',  repo.get_admin_setting('agent_key_id',  ''))
    agent_ready = (_mod_enabled == '1') and bool(_mod_key_id)
    if is_admin:
        review = repo.create_review(uid, score, text, 'approved', images=images, is_admin=True)
    else:
        review = repo.create_review(uid, score, text, 'pending' if agent_ready else 'approved', images=images)
    if agent_ready and not is_admin:
        try:
            from freeapi.agent import start_agent, trigger_agent
            start_agent()
            trigger_agent()
        except Exception as exc:
            logger.warning('[Reviews] Не удалось разбудить AI Agent: %s', exc)
    week_edits_after = repo.get_week_edits(uid)
    logger.info('[REVIEWS] сохранено uid=%s week_edits_after=%s', uid, week_edits_after)
    review['week_edits'] = week_edits_after
    return jsonify({'review': review})


@bp.delete('/api/reviews/<review_id>')
def delete_review_admin(review_id):
    err = require_user()
    if err:
        return err
    user = repo.get_user_by_id(current_user_id())
    if not user or user['username'] != 'ReZero':
        return error('Нет доступа', 403)
    logger.info('[REVIEWS] DELETE review_id=%s by uid=%s', review_id, current_user_id())
    repo.delete_review(review_id)
    return jsonify({'deleted': True})


@bp.put('/api/reviews/<review_id>/status')
def set_review_status(review_id):
    err = require_user()
    if err:
        return err
    user = repo.get_user_by_id(current_user_id())
    if not user or user['username'] != 'ReZero':
        return error('Нет доступа', 403)
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in ('approved', 'deleted', 'pending'):
        return error('Некорректный статус', 400)
    ai_response = data.get('ai_response')
    reply_by = data.get('reply_by', 'ai')
    if reply_by not in ('ai', 'manual'):
        reply_by = 'ai'
    admin_images = data.get('admin_images')
    if admin_images is not None:
        if not isinstance(admin_images, list):
            admin_images = []
        MAX_IMG_B64 = 7 * 1024 * 1024
        _ALLOWED = ('data:image/jpeg;base64,', 'data:image/jpg;base64,', 'data:image/png;base64,', 'data:image/gif;base64,', 'data:image/webp;base64,', 'data:image/heic;base64,', 'data:image/heif;base64,')
        admin_images = [img for img in admin_images if isinstance(img, str) and len(img) <= MAX_IMG_B64 and any(img[:40].lower().startswith(m) for m in _ALLOWED)]
        admin_images = admin_images[:10]
    logger.info('[REVIEWS] status_update review_id=%s status=%s reply_by=%s ai_resp_len=%s admin_imgs=%s uid=%s',
                review_id, status, reply_by, len(ai_response or ''), len(admin_images or []), current_user_id())
    review = repo.update_review_status(review_id, status, ai_response=ai_response, admin_images=admin_images, reply_by=reply_by)
    # Уведомление автору отзыва, если ответ оставил владелец вручную
    if review and reply_by == 'manual':
        target_uid = review.get('user_id')
        if target_uid and target_uid != current_user_id():
            snippet = (ai_response or '').strip()
            if len(snippet) > 200:
                snippet = snippet[:200].rstrip() + '…'
            has_imgs = bool(admin_images)
            if snippet and has_imgs:
                msg = f'👑 Владелец ответил на ваш отзыв (с фото): {snippet}'
            elif snippet:
                msg = f'👑 Владелец ответил на ваш отзыв: {snippet}'
            elif has_imgs:
                msg = '👑 Владелец прикрепил фото к ответу на ваш отзыв.'
            else:
                msg = '👑 Владелец отметил ваш отзыв.'
            try:
                repo.create_user_notification(target_uid, msg)
                logger.info('[REVIEWS] user_notification создано: target_uid=%s review_id=%s len=%s',
                            target_uid, review_id, len(msg))
            except Exception as exc:
                logger.warning('[REVIEWS] не удалось создать user_notification: %s', exc)
    return jsonify({'review': review})


@bp.post('/api/reviews/<review_id>/like')
def like_review(review_id):
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    data = request.get_json(silent=True) or {}
    try:
        value = int(data.get('value', 1))
    except (TypeError, ValueError):
        value = 1
    if value not in (1, -1):
        return error('value должен быть 1 (лайк) или -1 (дизлайк)', 400)
    result = repo.upsert_review_like(review_id, uid, value)
    logger.info('[REVIEWS] like uid=%s review=%s value=%s → likes=%s dislikes=%s user_like=%s',
                uid, review_id, value, result['likes'], result['dislikes'], result['user_like'])
    return jsonify(result)

# ═══════════════════════════════════════════════
#  USER NOTIFICATIONS
# ═══════════════════════════════════════════════

