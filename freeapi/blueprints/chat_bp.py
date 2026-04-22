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

bp = Blueprint('chat', __name__)

@bp.post('/api/chat/test')
def chat_test():
    blocked = require_user()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    key_id = data.get('keyId')
    key = repo.get_user_key(current_user_id(), key_id)
    if not key:
        return error('Ключ не найден', 404)
    if key.get('is_busy'):
        return error('API-ключ занят другим запросом. Дождитесь завершения.', 429, 'KEY_BUSY_301')
    messages = data.get('messages')
    if not isinstance(messages, list) or not messages:
        return error('Нужно хотя бы одно сообщение', 400)
    model = data.get('model') or key.get('default_model') or DEFAULT_MODEL_ID
    if not is_valid_model_id(model):
        return error(f'Модель "{model}" не существует', 400)
    content = next((m.get('content') for m in reversed(messages) if isinstance(m, dict) and m.get('role') == 'user'), '')
    has_images = isinstance(content, list) and any(x.get('type') == 'image_url' for x in content if isinstance(x, dict))
    images_count = len([x for x in content if isinstance(x, dict) and x.get('type') == 'image_url']) if isinstance(content, list) else 0
    text_content = content if isinstance(content, str) else ' '.join(p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text')
    if has_images:
        logger.info('[INFO] /api/chat/test — запрос содержит изображения, начинаю анализ фото...')
    else:
        logger.info('[INFO] /api/chat/test — текстовый запрос, модель=%s', model)
    new_tokens = estimate_tokens(text_content, images_count)
    current_kb = float(key.get('context_kb') or 0.0)
    new_kb = round(current_kb + tokens_to_kb(new_tokens), 1)
    req = repo.create_request(key_id, model, 'REQ_START_002', has_images, images_count)
    started = time.time()
    trace = {
        'dual_mode': bool(key.get('dual_mode') and key.get('translator_account_id')),
        'key_name': key.get('name') or '—',
        'model': model,
        'user_text': text_content,
    }
    try:
        if key.get('dual_mode') and key.get('translator_account_id'):
            logger.info('[Dual] /api/chat/test — key_id=%s model=%s translator=%s', key_id, model, key.get('translator_account_id'))
            answer = run_dual_chat(key, model, messages, trace=trace)
            log_code = 'DUAL_OK_801'
        else:
            answer = run_chat(key, model, messages, trace=trace)
            log_code = 'REQ_OK_001'
        elapsed = int((time.time() - started) * 1000)
        logger.info('[INFO] /api/chat/test — ответ за %d мс, log_code=%s', elapsed, log_code)
        repo.finish_request(req['id'], 'ok', log_code, elapsed)
        repo.update_model_stats(model, elapsed, True)
        repo.increment_context_tokens(key_id, new_tokens)
        trace['status'] = 'ok'
        trace['log_code'] = log_code
        trace['elapsed_ms'] = elapsed
        trace['answer'] = answer
        return jsonify({
            'answer': answer,
            'model': model,
            'responseMs': elapsed,
            'context_kb': round(new_kb, 1),
            'context_warn': new_kb >= CONTEXT_WARN_KB,
            'trace': trace,
        })
    except Exception as exc:
        elapsed = int((time.time() - started) * 1000)
        exc_text = str(exc)
        logger.error('[ERROR] /api/chat/test — ошибка за %d мс: %s', elapsed, exc_text)
        repo.finish_request(req['id'], 'error', 'REQ_ERR_500', elapsed, exc_text[:500])
        repo.update_model_stats(model, elapsed, False)
        if 'CTX_LIMIT_180' in exc_text:
            repo.set_limit_hit(key_id, 1)
            return error(
                'Контекст диалога переполнен (~180KB). Вызовите сброс.', 413, 'CTX_LIMIT_180'
            )
        return error(exc_text, 502)


@bp.post('/api/chat/reset')
def chat_reset():
    blocked = require_user()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    key_id = data.get('keyId')
    key = repo.get_user_key(current_user_id(), key_id)
    if not key:
        return error('Ключ не найден', 404)
    if key.get('limit_hit'):
        mem = get_memory(key_id)
        return jsonify({
            'ok': True,
            'requires_choice': True,
            'type': 'limit_hit',
            'files': {
                'context': {
                    'exists': bool(mem.get('context_md')),
                    'size_chars': len(mem.get('context_md') or ''),
                    'preview': (mem.get('context_md') or '')[:120],
                    'updated_at': mem.get('context_updated_at'),
                },
                'favorite': {
                    'exists': bool(mem.get('favorite_md')),
                    'size_chars': len(mem.get('favorite_md') or ''),
                    'preview': (mem.get('favorite_md') or '')[:120],
                    'updated_at': mem.get('favorite_updated_at'),
                },
            },
        })
    try:
        run_control(key, '/reset')
    except Exception:
        pass
    repo.reset_context_stats(key_id)
    return jsonify({'ok': True, 'type': 'standard', 'log_code': 'RESET_REQ_902'})


@bp.post('/api/chat/reset/apply')
def chat_reset_apply():
    blocked = require_user()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    key_id = data.get('keyId')
    key = repo.get_user_key(current_user_id(), key_id)
    if not key:
        return error('Ключ не найден', 404)
    ctx_action = data.get('context', 'clear')
    fav_action = data.get('favorite', 'clear')
    restore_data = {}
    if ctx_action == 'clear':
        clear_context(key_id)
    else:
        restore_data['context'] = True
    if fav_action == 'clear':
        clear_favorite(key_id)
    else:
        restore_data['favorite'] = True
    if restore_data:
        repo.set_pending_restore(key_id, restore_data)
    try:
        run_control(key, '/reset')
    except Exception:
        pass
    repo.reset_context_stats(key_id)
    return jsonify({
        'ok': True,
        'type': 'restored' if restore_data else 'cleared',
        'pending_restore': bool(restore_data),
        'log_code': 'MEM_RESTORE_903' if restore_data else 'RESET_REQ_902',
    })


@bp.post('/api/v1/chat')
def v1_chat():
    key, blocked = authorized_key()
    if blocked:
        return blocked
    if key.get('is_busy'):
        return error('API-ключ занят другим запросом. Дождитесь завершения.', 429, 'KEY_BUSY_301')
    data = request.get_json(silent=True) or {}
    messages = data.get('messages')
    if not isinstance(messages, list) or not messages:
        return error('Нужно хотя бы одно сообщение', 400, 'REQ_START_002')
    model = data.get('model') or key.get('default_model') or DEFAULT_MODEL_ID
    if not is_valid_model_id(model):
        return error(f'Модель "{model}" не существует', 400, 'MDL_INVALID_403')
    content = next((m.get('content') for m in reversed(messages) if isinstance(m, dict) and m.get('role') == 'user'), '')
    images_count = len([x for x in content if isinstance(x, dict) and x.get('type') == 'image_url']) if isinstance(content, list) else 0
    text_content = content if isinstance(content, str) else ' '.join(p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text')
    if images_count > 0:
        logger.info('[INFO] /api/v1/chat — запрос содержит %d изображение(й), начинаю анализ фото...', images_count)
    else:
        logger.info('[INFO] /api/v1/chat — текстовый запрос, модель=%s', model)

    key_id = key['id']
    new_tokens = estimate_tokens(text_content, images_count)
    current_kb = float(key.get('context_kb') or 0.0)
    new_kb = round(current_kb + tokens_to_kb(new_tokens), 1)

    memory = get_memory(key_id)
    lang_hint = memory.get('lang_hint', 'ru')

    messages_to_send = list(messages)

    pending = repo.get_pending_restore(key_id)
    if pending:
        mem_text = format_memory_injection(memory)
        if mem_text:
            inject_notice = (
                '[SYSTEM — READ BEFORE RESPONDING]: Your memory from previous session has been restored. '
                'Process it and respond to the user as usual.\n\n' + mem_text
            )
            messages_to_send = list(messages_to_send)
            for i in range(len(messages_to_send) - 1, -1, -1):
                if messages_to_send[i].get('role') == 'user':
                    orig = messages_to_send[i]
                    orig_content = orig.get('content', '')
                    if isinstance(orig_content, str):
                        new_content = inject_notice + '\n\n---\n\n' + orig_content
                    else:
                        new_content = [{'type': 'text', 'text': inject_notice + '\n\n---\n\n'}] + [p for p in orig_content if isinstance(p, dict)]
                    messages_to_send[i] = dict(orig)
                    messages_to_send[i]['content'] = new_content
                    break
        repo.set_pending_restore(key_id, None)
        logger.info('[MEMORY] pending_restore применён для ключа %s', key_id[:8])

    if new_kb >= CONTEXT_WARN_KB:
        warn_text = build_context_warning()
        for i in range(len(messages_to_send) - 1, -1, -1):
            if messages_to_send[i].get('role') == 'user':
                orig = messages_to_send[i]
                orig_content = orig.get('content', '')
                if isinstance(orig_content, str):
                    orig_content = orig_content + warn_text
                elif isinstance(orig_content, list):
                    for j, p in enumerate(orig_content):
                        if isinstance(p, dict) and p.get('type') == 'text':
                            orig_content = list(orig_content)
                            orig_content[j] = {'type': 'text', 'text': p['text'] + warn_text}
                            break
                messages_to_send[i] = dict(orig)
                messages_to_send[i]['content'] = orig_content
                break
        logger.info('[CTX] Предупреждение о лимите инжектировано: %.1f KB', new_kb)

    record = repo.create_request(key_id, model, 'REQ_START_002', images_count > 0, images_count)
    started = time.time()
    try:
        if key.get('dual_mode') and key.get('translator_account_id'):
            logger.info('[Dual] /api/v1/chat — key_id=%s model=%s translator=%s', key_id, model, key.get('translator_account_id'))
            answer = run_dual_chat(key, model, messages_to_send)
            log_code = 'DUAL_OK_801'
        else:
            answer = run_chat(key, model, messages_to_send)
            log_code = 'REQ_OK_001'

        elapsed = int((time.time() - started) * 1000)
        logger.info('[INFO] /api/v1/chat — ответ за %d мс', elapsed)

        clean_answer, mem_commands = parse_tags(answer)
        if mem_commands:
            wrote_ctx, wrote_fav = process_commands(key_id, mem_commands, lang_hint)
            if wrote_ctx or wrote_fav:
                log_code = 'MEM_WRITE_901'

        repo.increment_context_tokens(key_id, new_tokens)
        repo.finish_request(record['id'], 'ok', log_code, response_ms=elapsed)
        repo.update_model_stats(model, elapsed, ok=True)

        final_kb = round(new_kb, 1)
        ctx_warn = final_kb >= CONTEXT_WARN_KB

        if data.get('stream'):
            resp = Response(stream_with_context(fake_stream(clean_answer, record['id'], model)), mimetype='text/event-stream')
            resp.headers['Cache-Control'] = 'no-cache'
            resp.headers['X-Accel-Buffering'] = 'no'
            resp.headers['Connection'] = 'keep-alive'
            return resp
        return jsonify({
            'id': record['id'],
            'model': model,
            'choices': [{'message': {'role': 'assistant', 'content': clean_answer}}],
            'response_time_ms': elapsed,
            'log_code': log_code,
            'context_kb': final_kb,
            'context_warn': ctx_warn,
        })
    except Exception as exc:
        elapsed = int((time.time() - started) * 1000)
        exc_text = str(exc)
        logger.error('[ERROR] /api/v1/chat — ошибка за %d мс: %s', elapsed, exc_text)
        if 'CTX_LIMIT_180' in exc_text:
            repo.set_limit_hit(key_id, 1)
            repo.finish_request(record['id'], 'error', 'CTX_LIMIT_180', response_ms=elapsed, error_msg=exc_text)
            repo.update_model_stats(model, elapsed, ok=False)
            return error(
                'Контекст диалога переполнен (~180KB). Необходимо выполнить сброс. '
                'Вызовите /reset — система предложит сохранить или очистить память.',
                413, 'CTX_LIMIT_180'
            )
        if 'KEY_BUSY_301' in exc_text:
            code, status = 'KEY_BUSY_301', 429
        elif 'KEY_NO_TG_303' in exc_text:
            code, status = 'KEY_NO_TG_303', 400
        elif 'timeout' in exc_text.lower():
            code, status = 'TG_TIMEOUT_501', 504
        else:
            code, status = 'TG_ERROR_506', 502
        repo.finish_request(record['id'], 'timeout' if code == 'TG_TIMEOUT_501' else 'error', code, response_ms=elapsed, error_msg=exc_text)
        repo.update_model_stats(model, elapsed, ok=False)
        return error(exc_text, status, code)


@bp.post('/api/v1/stop')
def v1_stop():
    key, blocked = authorized_key()
    if blocked:
        return blocked
    try:
        run_control(key, '/stop')
    except Exception:
        pass
    return jsonify({'stopped': True, 'log_code': 'STOP_REQ_901'})


@bp.post('/api/v1/reset')
def v1_reset():
    key, blocked = authorized_key()
    if blocked:
        return blocked
    key_id = key['id']
    if key.get('limit_hit'):
        mem = get_memory(key_id)
        return jsonify({
            'reset': False,
            'requires_choice': True,
            'type': 'limit_hit',
            'log_code': 'CTX_LIMIT_180',
            'files': {
                'context': {
                    'exists': bool(mem.get('context_md')),
                    'size_chars': len(mem.get('context_md') or ''),
                    'preview': (mem.get('context_md') or '')[:120],
                },
                'favorite': {
                    'exists': bool(mem.get('favorite_md')),
                    'size_chars': len(mem.get('favorite_md') or ''),
                    'preview': (mem.get('favorite_md') or '')[:120],
                },
            },
        })
    try:
        run_control(key, '/reset')
    except Exception:
        pass
    repo.reset_context_stats(key_id)
    return jsonify({'reset': True, 'log_code': 'RESET_REQ_902', 'context_kb': 0.0})


@bp.post('/api/v1/reset/apply')
def v1_reset_apply():
    key, blocked = authorized_key()
    if blocked:
        return blocked
    key_id = key['id']
    data = request.get_json(silent=True) or {}
    ctx_action = data.get('context', 'clear')
    fav_action = data.get('favorite', 'clear')
    restore_data = {}
    if ctx_action == 'clear':
        clear_context(key_id)
    else:
        restore_data['context'] = True
    if fav_action == 'clear':
        clear_favorite(key_id)
    else:
        restore_data['favorite'] = True
    if restore_data:
        repo.set_pending_restore(key_id, restore_data)
    try:
        run_control(key, '/reset')
    except Exception:
        pass
    repo.reset_context_stats(key_id)
    return jsonify({
        'reset': True,
        'type': 'restored' if restore_data else 'cleared',
        'pending_restore': bool(restore_data),
        'log_code': 'MEM_RESTORE_903' if restore_data else 'RESET_REQ_902',
        'context_kb': 0.0,
    })


# ═══════════════════════════════════════════════
#  REVIEWS
# ═══════════════════════════════════════════════

