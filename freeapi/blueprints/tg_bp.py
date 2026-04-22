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

bp = Blueprint('tg', __name__)

@bp.post('/api/tg/setup')
def tg_setup():
    blocked = require_user()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    api_id = str(data.get('apiId') or data.get('api_id') or '').strip()
    api_hash = str(data.get('apiHash') or data.get('api_hash') or '').strip()
    phone = str(data.get('phone') or '').strip() or None
    session_string = str(data.get('sessionString') or data.get('session_string') or '').strip() or None
    skip_training = bool(data.get('skipTraining') or data.get('skip_training'))
    if not api_id or not api_hash:
        return error('API ID и API Hash обязательны', 400)
    # B-03: Валидация api_id — должен быть числом
    if not api_id.isdigit():
        return error('API ID должен быть числом (см. my.telegram.org)', 400, 'TG_INVALID_505')
    running = repo.get_running_setup(current_user_id())
    if running:
        return jsonify({'error': True, 'message': 'Настройка уже выполняется', 'setupId': running['id']}), 409
    account = repo.create_tg_account(current_user_id(), api_id, encrypt_text(api_hash), phone, encrypt_text(session_string) if session_string else None)
    setup_id = repo.create_setup_session(current_user_id(), account['id'])
    update_progress(setup_id, setupId=setup_id, step=0, stepLabel='Инициализация...', done=False, error=None)
    if session_string:
        run_setup_background(setup_id, current_user_id(), account['id'], start_step=6 if skip_training else 1)
        return jsonify({'setupId': setup_id, 'tgAccountId': account['id'], 'status': 'running'}), 202
    if phone:
        try:
            result = asyncio.run(send_code_request(api_id, api_hash, phone))
            set_pending_auth(setup_id, {'api_id': api_id, 'api_hash': api_hash, 'phone': phone, 'phone_code_hash': result['phone_code_hash'], 'session_string': result['session_string'], 'tg_account_id': account['id'], 'user_id': current_user_id(), 'skip_training': skip_training})
            update_progress(setup_id, step=0, stepLabel=f'Введите код Telegram через POST /api/tg/setup/{setup_id}/code', done=False, error=None)
            return jsonify({'setupId': setup_id, 'tgAccountId': account['id'], 'status': 'awaiting_code'}), 202
        except Exception as exc:
            repo.update_setup_session(setup_id, status='error', error_msg=str(exc))
            update_progress(setup_id, done=True, error='TG_INVALID_505: ' + str(exc))
            return error(str(exc), 400, 'TG_INVALID_505')
    update_progress(setup_id, done=True, error='Для Telethon нужен phone или sessionString')
    return jsonify({'setupId': setup_id, 'tgAccountId': account['id'], 'status': 'need_phone', 'message': 'Передайте phone или sessionString'}), 202


@bp.post('/api/tg/setup/<setup_id>/code')
def tg_setup_code(setup_id):
    blocked = require_user()
    if blocked:
        return blocked
    pending = get_pending_auth(setup_id)
    if not pending or pending.get('user_id') != current_user_id():
        return error('Сессия авторизации не найдена', 404)
    data = request.get_json(silent=True) or {}
    code = str(data.get('code') or '').strip()
    password = data.get('password')
    if not code:
        return error('Код Telegram обязателен', 400)
    result = asyncio.run(sign_in_with_code(pending['api_id'], pending['api_hash'], pending['phone'], code, pending['phone_code_hash'], pending['session_string'], password=password))
    if result.get('need_password'):
        pending['session_string'] = result['session_string']
        set_pending_auth(setup_id, pending)
        return jsonify({'setupId': setup_id, 'status': 'need_password', 'message': 'Введите пароль 2FA в поле password'}), 202
    if not result.get('authorized'):
        return error('Telegram не авторизовал сессию', 400, 'TG_INVALID_505')
    repo.update_tg_account(pending['tg_account_id'], session_string=encrypt_text(result['session_string']), is_valid=1)
    pending_skip = bool(pending.get('skip_training'))
    clear_pending_auth(setup_id)
    run_setup_background(setup_id, current_user_id(), pending['tg_account_id'], start_step=6 if pending_skip else 1)
    return jsonify({'setupId': setup_id, 'status': 'running'}), 202


@bp.get('/api/tg/setup/<setup_id>/status')
def tg_setup_status(setup_id):
    blocked = require_user()
    if blocked:
        return blocked
    if 'text/event-stream' in request.headers.get('Accept', ''):
        resp = Response(event_stream(setup_id), mimetype='text/event-stream')
        resp.headers['Cache-Control'] = 'no-cache'
        resp.headers['X-Accel-Buffering'] = 'no'
        resp.headers['Connection'] = 'keep-alive'
        return resp
    progress = get_progress(setup_id)
    if progress:
        return jsonify(progress)
    setup = repo.get_setup_session(setup_id)
    if setup and setup.get('user_id') == current_user_id():
        status = setup.get('status')
        error_msg = setup.get('error_msg')
        return jsonify({
            'setupId': setup_id,
            'step': setup.get('current_step') or 0,
            'stepLabel': setup.get('step_label') or 'Нет данных',
            'done': status in ('done', 'error', 'cancelled'),
            'error': ('SETUP_FAIL_604: ' + error_msg) if status == 'error' and error_msg else None,
            'canRetry': status == 'error',
        })
    return jsonify({'setupId': setup_id, 'step': 0, 'stepLabel': 'Нет данных', 'done': False, 'error': None})


@bp.post('/api/tg/setup/<setup_id>/retry')
def tg_setup_retry(setup_id):
    blocked = require_user()
    if blocked:
        return blocked
    setup = repo.get_setup_session(setup_id)
    if not setup or setup.get('user_id') != current_user_id():
        return error('Сессия настройки не найдена', 404)
    if setup.get('status') == 'running':
        return error('Настройка уже выполняется', 409)
    if setup.get('status') != 'error':
        return error('Повтор доступен только после ошибки настройки', 400)
    step = int(setup.get('current_step') or 1)
    step = max(1, min(step, 6))
    label = setup.get('step_label') or f'Повтор шага {step}...'
    repo.update_setup_session(setup_id, status='running', current_step=step, step_label=label, error_msg=None)
    update_progress(setup_id, setupId=setup_id, step=step, stepLabel='Повторяем последний шаг...', done=False, error=None, canRetry=False)
    run_setup_background(setup_id, current_user_id(), setup['tg_account_id'], start_step=step)
    return jsonify({'setupId': setup_id, 'status': 'running', 'step': step}), 202


@bp.post('/api/tg/setup/<setup_id>/cancel')
def tg_setup_cancel(setup_id):
    blocked = require_user()
    if blocked:
        return blocked
    repo.update_setup_session(setup_id, status='cancelled', error_msg='SETUP_ABORT_605')
    update_progress(setup_id, done=True, error='SETUP_ABORT_605: Настройка отменена пользователем')
    clear_pending_auth(setup_id)
    return jsonify({'ok': True, 'log_code': 'SETUP_ABORT_605'})


@bp.delete('/api/tg/account')
def tg_account_delete():
    blocked = require_user()
    if blocked:
        return blocked
    repo.delete_tg_accounts(current_user_id())
    return jsonify({'ok': True})


@bp.post('/api/tg/session/import')
def tg_session_import():
    blocked = require_user()
    if blocked:
        return blocked
    if 'file' not in request.files:
        return error('Файл не передан', 400)
    f = request.files['file']
    # Защита от OOM в Termux: ограничиваем размер файла сессии до 5 МБ
    MAX_SESSION_SIZE = 5 * 1024 * 1024  # 5 МБ
    data = f.read(MAX_SESSION_SIZE + 1)
    if len(data) > MAX_SESSION_SIZE:
        return error('Файл слишком большой (максимум 5 МБ)', 400)
    if not data:
        return error('Файл пустой', 400)
    import io as _io, sqlite3 as _sql, tempfile as _tmp, os as _os
    from telethon.sessions import StringSession
    from telethon.crypto import AuthKey
    # Check if SQLite file
    if data[:16] == b'SQLite format 3\x00':
        fd, tmp = None, None
        try:
            fd, tmp = _tmp.mkstemp(suffix='.session')
            _os.close(fd); fd = None
            with open(tmp, 'wb') as wf:
                wf.write(data)
            conn = _sql.connect(tmp)
            try:
                row = conn.execute('SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1').fetchone()
            finally:
                conn.close()
            if not row:
                return error('Таблица sessions пуста', 400)
            dc_id, server_address, port, auth_key_bytes = row
            ss = StringSession()
            ss._dc_id = dc_id
            ss._server_address = server_address
            ss._port = port
            ss._auth_key = AuthKey(auth_key_bytes) if auth_key_bytes else None
            session_str = ss.save()
            return jsonify({'session_string': session_str})
        except Exception as exc:
            return error(f'Ошибка чтения .session файла: {exc}', 400)
        finally:
            # Гарантированное удаление временного файла (защита от утечки данных)
            if tmp and _os.path.exists(tmp):
                try: _os.unlink(tmp)
                except Exception: pass
    # Try as plain text StringSession
    try:
        text = data.decode('utf-8').strip()
        if text:
            return jsonify({'session_string': text})
    except Exception:
        pass
    return error('Неподдерживаемый формат файла', 400)

