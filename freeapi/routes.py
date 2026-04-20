import asyncio
import json
import logging
import os
import time

from flask import Response, jsonify, request, session, stream_with_context

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


def error(message, status=400, log_code=None):
    data = {'error': True, 'message': message}
    if log_code:
        data['log_code'] = log_code
    return jsonify(data), status


def current_user_id():
    return session.get('user_id')


_SUPPORT_PROJECT_CONTEXT_CACHE = None
_SUPPORT_PROJECT_CONTEXT_FILES = (
    'README.md',
    'api.py',
    'freeapi/app.py',
    'freeapi/routes.py',
    'freeapi/repositories.py',
    'freeapi/database.py',
    'freeapi/models.py',
    'freeapi/tg.py',
    'freeapi/agent.py',
    'freeapi/auth_service.py',
    'freeapi/security.py',
    'freeapi/progress.py',
    'freeapi/rate_limit.py',
    'freeapi/log_codes.py',
    'freeapi/tg_notify.py',
    'freeapi/tunnel.py',
    'static/index.html',
)
_SUPPORT_PROJECT_CONTEXT_LIMIT = 260000


def support_project_context():
    global _SUPPORT_PROJECT_CONTEXT_CACHE
    if _SUPPORT_PROJECT_CONTEXT_CACHE:
        return _SUPPORT_PROJECT_CONTEXT_CACHE
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    parts = [
        '=== РАСШИРЕННЫЙ ТЕХНИЧЕСКИЙ КОНТЕКСТ ПРОЕКТА FAVORITEAPI ===',
        'Это внутренний контекст для агента поддержки. Используй его, чтобы отвечать точно по устройству сервиса, маршрутам, UI, настройке Telegram, API-ключам, моделям, ошибкам и админке.',
        'Не цитируй исходный код пользователю большими кусками без необходимости. Объясняй простыми словами и проси детали, если данных недостаточно.',
        'Стек: Flask, SQLite, серверные сессии, Telethon/StringSession, Telegram-бот как прокси к AI, OpenAI-compatible REST API, self-contained frontend static/index.html.',
    ]
    used = sum(len(item) + 2 for item in parts)
    for rel_path in _SUPPORT_PROJECT_CONTEXT_FILES:
        abs_path = os.path.join(root, rel_path)
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as file:
                content = file.read()
        except Exception as exc:
            content = f'[Файл недоступен: {exc}]'
        header = f'\n\n--- FILE: {rel_path} ---\n'
        remaining = _SUPPORT_PROJECT_CONTEXT_LIMIT - used - len(header)
        if remaining <= 0:
            parts.append('\n\n[Контекст проекта обрезан из-за лимита размера prompt.]')
            break
        if len(content) > remaining:
            content = content[:remaining] + '\n\n[Файл обрезан из-за лимита размера prompt.]'
            parts.append(header + content)
            break
        parts.append(header + content)
        used += len(header) + len(content)
    _SUPPORT_PROJECT_CONTEXT_CACHE = '\n'.join(parts)
    return _SUPPORT_PROJECT_CONTEXT_CACHE


def require_user():
    if not current_user_id():
        return error('Требуется авторизация', 401)
    return None


def bearer_value():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    return auth[7:].strip() or None


def authorized_key():
    value = bearer_value()
    if not value:
        return None, error('Отсутствует заголовок Authorization: Bearer <api_key>', 401, 'KEY_INVALID_302')
    key = repo.get_key_by_value(value)
    if not key:
        return None, error('API-ключ не найден или деактивирован', 401, 'KEY_INVALID_302')
    return key, None




def fake_stream(answer, record_id, model):
    """Имитация SSE-стриминга: ИИ уже ответил, подаём текст по словам."""
    opening = {
        'id': str(record_id), 'object': 'chat.completion.chunk', 'model': model,
        'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': ''}, 'finish_reason': None}]
    }
    yield f'data: {json.dumps(opening, ensure_ascii=False)}\n\n'
    words = answer.split(' ')
    for i in range(0, len(words), 2):
        chunk_words = words[i:i + 2]
        text = ' '.join(chunk_words) + (' ' if i + 2 < len(words) else '')
        chunk = {
            'id': str(record_id), 'object': 'chat.completion.chunk', 'model': model,
            'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}]
        }
        yield f'data: {json.dumps(chunk, ensure_ascii=False)}\n\n'
        time.sleep(0.02)
    closing = {
        'id': str(record_id), 'object': 'chat.completion.chunk', 'model': model,
        'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]
    }
    yield f'data: {json.dumps(closing, ensure_ascii=False)}\n\n'
    yield 'data: [DONE]\n\n'


def register_routes(app):
    @app.get('/api/healthz')
    def health():
        return jsonify({'status': 'ok'})

    @app.post('/api/auth/register')
    def auth_register():
        data = request.get_json(silent=True) or {}
        user, err, status = register_user(data.get('username', ''), data.get('password', ''))
        if err:
            return error(err, status)
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'ok': True, 'user': user}), status

    @app.post('/api/auth/login')
    def auth_login():
        data = request.get_json(silent=True) or {}
        user, err, status = login_user(data.get('username', ''), data.get('password', ''))
        if err:
            return error(err, status)
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'ok': True, 'user': user})

    @app.post('/api/auth/logout')
    def auth_logout():
        session.clear()
        return jsonify({'ok': True})

    @app.get('/api/auth/me')
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

    @app.post('/api/tg/setup')
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

    @app.post('/api/tg/setup/<setup_id>/code')
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

    @app.get('/api/tg/setup/<setup_id>/status')
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

    @app.post('/api/tg/setup/<setup_id>/retry')
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

    @app.post('/api/tg/setup/<setup_id>/cancel')
    def tg_setup_cancel(setup_id):
        blocked = require_user()
        if blocked:
            return blocked
        repo.update_setup_session(setup_id, status='cancelled', error_msg='SETUP_ABORT_605')
        update_progress(setup_id, done=True, error='SETUP_ABORT_605: Настройка отменена пользователем')
        clear_pending_auth(setup_id)
        return jsonify({'ok': True, 'log_code': 'SETUP_ABORT_605'})

    @app.delete('/api/tg/account')
    def tg_account_delete():
        blocked = require_user()
        if blocked:
            return blocked
        repo.delete_tg_accounts(current_user_id())
        return jsonify({'ok': True})

    def _sanitize_tg_username(username):
        import re as _re
        if not username:
            return ''
        return username if _re.match(r'^[a-zA-Z0-9_]{1,32}$', username) else ''

    def _enrich_key(key):
        item = dict(key)
        item['keyValue'] = mask_key(item['key_value'])
        main_acc = repo.get_tg_account(key.get('tg_account_id')) or {}
        item['setup_done'] = 1 if main_acc.get('setup_done') else 0
        item['tg_username'] = _sanitize_tg_username(main_acc.get('tg_username') or '')
        item['tg_first_name'] = main_acc.get('tg_first_name') or ''
        item['mainAccountInfo'] = {
            'username': _sanitize_tg_username(main_acc.get('tg_username') or ''),
            'firstName': main_acc.get('tg_first_name') or '',
        }
        if key.get('dual_mode') and key.get('translator_account_id'):
            tr_acc = repo.get_tg_account(key['translator_account_id']) or {}
            item['translatorAccountInfo'] = {
                'id': key['translator_account_id'],
                'username': _sanitize_tg_username(tr_acc.get('tg_username') or ''),
                'firstName': tr_acc.get('tg_first_name') or '',
            }
        else:
            item['translatorAccountInfo'] = None
        return item

    @app.get('/api/keys')
    def keys_list():
        blocked = require_user()
        if blocked:
            return blocked
        result = []
        for key in repo.get_user_keys(current_user_id()):
            stats = repo.get_key_month_stats(key['id'])
            item = _enrich_key(key)
            item.update(stats)
            result.append(item)
        return jsonify({'keys': result})

    @app.post('/api/keys')
    def keys_create():
        blocked = require_user()
        if blocked:
            return blocked
        return error('Новый ключ создаётся только после полной настройки нового Telegram-аккаунта. Запустите SetupFlow через /api/tg/setup.', 409)

    @app.get('/api/keys/<key_id>')
    def keys_get(key_id):
        blocked = require_user()
        if blocked:
            return blocked
        key = repo.get_user_key(current_user_id(), key_id)
        if not key:
            return error('Ключ не найден', 404)
        item = dict(key)
        item['keyValue'] = mask_key(item['key_value'])
        return jsonify({'key': item, 'logs': repo.get_key_logs(key_id)})

    @app.put('/api/keys/<key_id>')
    def keys_update(key_id):
        blocked = require_user()
        if blocked:
            return blocked
        key = repo.get_user_key(current_user_id(), key_id)
        if not key:
            return error('Ключ не найден', 404)
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data.get('name') or '')[:100]
        model = data.get('defaultModel') or data.get('default_model')
        if model is not None:
            if not is_valid_model_id(model):
                return error('Указанная модель не существует', 400, 'MDL_INVALID_403')
            updates['default_model'] = model
        if 'skipHints' in data:
            updates['skip_hints'] = 1 if data.get('skipHints') else 0
        if 'skip_hints' in data:
            updates['skip_hints'] = 1 if data.get('skip_hints') else 0
        if 'dualMode' in data or 'dual_mode' in data:
            val = data.get('dualMode') if 'dualMode' in data else data.get('dual_mode')
            updates['dual_mode'] = 1 if val else 0
        if 'translatorAccountId' in data or 'translator_account_id' in data:
            tr_id = data.get('translatorAccountId') or data.get('translator_account_id')
            if tr_id:
                if tr_id == key['tg_account_id']:
                    return error('Аккаунт-переводчик не может совпадать с основным', 400)
                tr_acc = repo.get_tg_account(tr_id)
                if not tr_acc or tr_acc.get('user_id') != current_user_id():
                    return error('Аккаунт-переводчик не найден', 404)
                if not tr_acc.get('setup_done'):
                    return error('Аккаунт-переводчик не настроен — завершите Setup', 400)
                updates['translator_account_id'] = tr_id
            else:
                updates['translator_account_id'] = None
        updated = repo.update_api_key(key_id, **updates)
        if model is not None and model != key.get('current_model'):
            switch_model_background(key_id, model)
        return jsonify({'key': _enrich_key(updated)})

    @app.delete('/api/keys/<key_id>')
    def keys_delete(key_id):
        blocked = require_user()
        if blocked:
            return blocked
        key = repo.get_user_key(current_user_id(), key_id)
        if not key:
            return error('Ключ не найден', 404)
        repo.deactivate_key(key_id)
        return jsonify({'ok': True})

    @app.post('/api/keys/<key_id>/regen')
    def keys_regen(key_id):
        blocked = require_user()
        if blocked:
            return blocked
        key = repo.get_user_key(current_user_id(), key_id)
        if not key:
            return error('Ключ не найден', 404)
        new_value = generate_api_key()
        updated = repo.update_api_key(key_id, key_value=new_value)
        item = dict(updated)
        # B-07: rawKey — полное значение, показывается единожды
        item['rawKey'] = new_value
        item['keyValue'] = mask_key(new_value)
        return jsonify({'key': item})

    @app.get('/api/keys/<key_id>/logs')
    def keys_logs(key_id):
        blocked = require_user()
        if blocked:
            return blocked
        key = repo.get_user_key(current_user_id(), key_id)
        if not key:
            return error('Ключ не найден', 404)
        return jsonify({'logs': repo.get_key_logs(key_id)})

    @app.get('/api/keys/<key_id>/session')
    def key_session_download(key_id):
        blocked = require_user()
        if blocked:
            return blocked
        key = repo.get_user_key(current_user_id(), key_id)
        if not key:
            return error('Ключ не найден', 404)
        tg_account_id = key.get('tg_account_id')
        if not tg_account_id:
            return error('К этому ключу не привязан Telegram-аккаунт', 404)
        account = repo.get_tg_account(tg_account_id)
        if not account or not account.get('session_string'):
            return error('Сессия Telethon недоступна для этого аккаунта', 404)
        from freeapi.security import decrypt_text
        from flask import send_file
        import io, sqlite3, tempfile, os
        from telethon.sessions import StringSession
        raw = account['session_string']
        try:
            session_value = decrypt_text(raw)
        except Exception:
            session_value = raw
        if not session_value:
            return error('Сессия Telethon пуста или повреждена', 404)
        fmt = request.args.get('format', 'session')
        if fmt == 'txt':
            return Response(
                session_value,
                mimetype='text/plain',
                headers={'Content-Disposition': 'attachment; filename=session_string.txt'}
            )
        try:
            ss = StringSession(session_value)
            fd, tmp_path = tempfile.mkstemp(suffix='.session')
            os.close(fd)
            os.unlink(tmp_path)
            conn = sqlite3.connect(tmp_path)
            conn.execute('CREATE TABLE version (version integer primary key)')
            conn.execute('''CREATE TABLE sessions (
                dc_id integer primary key,
                server_address text,
                port integer,
                auth_key blob,
                takeout_id integer
            )''')
            conn.execute('''CREATE TABLE entities (
                id integer primary key,
                hash integer not null,
                username text,
                phone integer,
                name text,
                date integer
            )''')
            conn.execute('''CREATE TABLE sent_files (
                md5_digest blob,
                file_size integer,
                type integer,
                id integer,
                hash integer,
                primary key(md5_digest, file_size, type)
            )''')
            conn.execute('''CREATE TABLE update_state (
                id integer primary key,
                pts integer,
                qts integer,
                date integer,
                seq integer
            )''')
            conn.execute('INSERT INTO version VALUES (7)')
            auth_key_bytes = ss.auth_key.key if ss.auth_key else b''
            conn.execute(
                'INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)',
                (ss.dc_id, ss.server_address, ss.port, auth_key_bytes, None)
            )
            conn.commit()
            conn.close()
            with open(tmp_path, 'rb') as f:
                data = f.read()
            os.unlink(tmp_path)
            phone_raw = account.get('phone') or ''
            safe_phone = phone_raw.lstrip('+').replace(' ', '').replace('-', '')
            if not safe_phone:
                import re as _re
                safe_phone = _re.sub(r'[^\w]', '_', key.get('name') or 'session')
            fname = f'{safe_phone}.session'
            return send_file(
                io.BytesIO(data),
                mimetype='application/octet-stream',
                as_attachment=True,
                download_name=fname
            )
        except Exception as exc:
            return error(f'Ошибка создания .session файла: {exc}', 500)

    @app.post('/api/tg/session/import')
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
            try:
                fd, tmp = _tmp.mkstemp(suffix='.session')
                _os.close(fd)
                with open(tmp, 'wb') as wf:
                    wf.write(data)
                conn = _sql.connect(tmp)
                row = conn.execute('SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1').fetchone()
                conn.close()
                _os.unlink(tmp)
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
        # Try as plain text StringSession
        try:
            text = data.decode('utf-8').strip()
            if text:
                return jsonify({'session_string': text})
        except Exception:
            pass
        return error('Неподдерживаемый формат файла', 400)

    @app.post('/api/chat/test')
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

    @app.post('/api/chat/reset')
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

    @app.post('/api/chat/reset/apply')
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

    @app.get('/api/models')
    def models_list():
        stats = {item['model_id']: item for item in repo.get_model_stats()}
        output = []
        for model in AI_MODELS:
            row = stats.get(model['id']) or {}
            output.append({'id': model['id'], 'displayName': model['displayName'], 'contextK': model['contextK'], 'supportsVision': model['supportsVision'], 'isDefault': model['isDefault'], 'isPopular': model['isPopular'], 'avgResponseMs': row.get('avg_response_ms'), 'totalRequests': row.get('total_requests', 0)})
        return jsonify({'models': output})

    @app.get('/api/stats/global')
    def stats_global():
        return jsonify(repo.get_global_stats())

    @app.get('/api/stats/keys/<key_id>')
    def stats_key(key_id):
        blocked = require_user()
        if blocked:
            return blocked
        key = repo.get_user_key(current_user_id(), key_id)
        if not key:
            return error('Ключ не найден', 404)
        return jsonify(repo.get_key_month_stats(key_id))

    @app.get('/api/log-codes')
    def log_codes():
        return jsonify({'codes': repo.get_log_codes()})

    @app.post('/api/v1/chat')
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

    @app.post('/api/v1/stop')
    def v1_stop():
        key, blocked = authorized_key()
        if blocked:
            return blocked
        try:
            run_control(key, '/stop')
        except Exception:
            pass
        return jsonify({'stopped': True, 'log_code': 'STOP_REQ_901'})

    @app.post('/api/v1/reset')
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

    @app.post('/api/v1/reset/apply')
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

    @app.get('/api/reviews')
    def get_reviews():
        try:
            page = max(1, int(request.args.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        limit = 10
        offset = (page - 1) * limit
        items, total = repo.get_approved_reviews(limit=limit, offset=offset)
        avg_score = repo.get_avg_review_score()
        return jsonify({
            'reviews': items,
            'total': total,
            'page': page,
            'pages': max(1, (total + limit - 1) // limit),
            'avg_score': avg_score,
        })

    @app.get('/api/reviews/mine')
    def get_my_review():
        err = require_user()
        if err:
            return err
        review = repo.get_review_by_user(current_user_id())
        return jsonify({'review': review})

    @app.post('/api/reviews')
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
        if score < 1 or score > 10:
            return error('Оценка должна быть числом от 1 до 10', 400)
        if not text or len(text) < 10:
            return error('Текст отзыва слишком короткий (минимум 10 символов)', 400)
        if len(text) > 1000:
            return error('Текст отзыва слишком длинный (максимум 1000 символов)', 400)
        images = data.get('images') or []
        if not isinstance(images, list):
            images = []
        # Фильтруем невалидные изображения (max 7MB base64 ≈ 5MB raw, только изображения)
        MAX_IMG_B64 = 7 * 1024 * 1024  # 7MB base64
        ALLOWED_IMG_MIME = ('data:image/jpeg;base64,', 'data:image/jpg;base64,', 'data:image/png;base64,', 'data:image/gif;base64,', 'data:image/webp;base64,', 'data:image/heic;base64,', 'data:image/heif;base64,')
        def _is_valid_img(img):
            if not isinstance(img, str): return False
            if len(img) > MAX_IMG_B64: return False
            lower = img[:40].lower()
            return any(lower.startswith(m) for m in ALLOWED_IMG_MIME)
        images = [img for img in images if _is_valid_img(img)]
        images = images[:10]
        agent_ready = repo.get_admin_setting('agent_enabled', '0') == '1' and bool(repo.get_admin_setting('agent_key_id', ''))
        if is_admin:
            review = repo.create_review(uid, score, text, 'approved', images=images)
        else:
            review = repo.create_review(uid, score, text, 'pending' if agent_ready else 'approved', images=images)
        if agent_ready and not is_admin:
            try:
                from freeapi.agent import start_agent, trigger_agent
                start_agent()
                trigger_agent()
            except Exception as exc:
                logger.warning('[Reviews] Не удалось разбудить AI Agent: %s', exc)
        return jsonify({'review': review})

    @app.delete('/api/reviews/<review_id>')
    def delete_review_admin(review_id):
        err = require_user()
        if err:
            return err
        user = repo.get_user_by_id(current_user_id())
        if not user or user['username'] != 'ReZero':
            return error('Нет доступа', 403)
        repo.delete_review(review_id)
        return jsonify({'deleted': True})

    @app.put('/api/reviews/<review_id>/status')
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
        admin_images = data.get('admin_images')
        if admin_images is not None:
            if not isinstance(admin_images, list):
                admin_images = []
            MAX_IMG_B64 = 7 * 1024 * 1024
            _ALLOWED = ('data:image/jpeg;base64,', 'data:image/jpg;base64,', 'data:image/png;base64,', 'data:image/gif;base64,', 'data:image/webp;base64,', 'data:image/heic;base64,', 'data:image/heif;base64,')
            admin_images = [img for img in admin_images if isinstance(img, str) and len(img) <= MAX_IMG_B64 and any(img[:40].lower().startswith(m) for m in _ALLOWED)]
            admin_images = admin_images[:10]
        review = repo.update_review_status(review_id, status, ai_response=ai_response, admin_images=admin_images)
        return jsonify({'review': review})

    # ═══════════════════════════════════════════════
    #  USER NOTIFICATIONS
    # ═══════════════════════════════════════════════

    @app.get('/api/notifications')
    def get_notifications():
        err = require_user()
        if err:
            return err
        items = repo.get_user_notifications(current_user_id())
        unread = repo.count_unread_notifications(current_user_id())
        return jsonify({'notifications': items, 'unread': unread})

    @app.post('/api/notifications/<notif_id>/read')
    def mark_notif_read(notif_id):
        err = require_user()
        if err:
            return err
        repo.mark_notification_read(notif_id, current_user_id())
        return jsonify({'ok': True})

    @app.delete('/api/notifications/<notif_id>')
    def delete_notif(notif_id):
        err = require_user()
        if err:
            return err
        repo.delete_user_notification(notif_id, current_user_id())
        return jsonify({'deleted': True})

    # ═══════════════════════════════════════════════
    #  ADMIN PANEL (только ReZero)
    # ═══════════════════════════════════════════════

    def require_admin():
        if not current_user_id():
            return error('Требуется авторизация', 401)
        user = repo.get_user_by_id(current_user_id())
        if not user or user['username'] != 'ReZero':
            return error('Нет доступа', 403)
        return None

    @app.get('/api/admin/settings')
    def admin_get_settings():
        err = require_admin()
        if err:
            return err
        settings = repo.get_all_admin_settings()
        keys = repo.get_all_keys_for_admin()
        return jsonify({'settings': settings, 'keys': keys})

    @app.put('/api/admin/settings')
    def admin_update_settings():
        err = require_admin()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        allowed = (
            'agent_enabled', 'agent_key_id',
            'moderator_enabled', 'moderator_key_id', 'moderator_model', 'moderator_system_prompt',
            'support_enabled', 'support_key_id', 'support_model', 'support_system_prompt',
        )
        for k, v in data.items():
            if k in allowed:
                repo.set_admin_setting(k, str(v))
        if 'moderator_enabled' in data:
            repo.set_admin_setting('agent_enabled', str(data['moderator_enabled']))
        if 'moderator_key_id' in data:
            repo.set_admin_setting('agent_key_id', str(data['moderator_key_id']))
        mod_enabled = str(data.get('moderator_enabled', repo.get_admin_setting('moderator_enabled', '0')))
        try:
            if mod_enabled == '1':
                from freeapi.agent import start_agent, trigger_agent
                start_agent()
                trigger_agent()
            else:
                from freeapi.agent import stop_agent
                stop_agent()
        except Exception as exc:
            logger.warning('[Admin] Не удалось изменить состояние AI Agent: %s', exc)
        return jsonify({'ok': True, 'settings': repo.get_all_admin_settings()})

    @app.get('/api/admin/notifications')
    def admin_get_notifications():
        err = require_admin()
        if err:
            return err
        items = repo.get_admin_notifications()
        return jsonify({'notifications': items})

    @app.delete('/api/admin/notifications/<notif_id>')
    def admin_delete_notification(notif_id):
        err = require_admin()
        if err:
            return err
        repo.delete_admin_notification(notif_id)
        return jsonify({'deleted': True})

    @app.get('/api/admin/reviews')
    def admin_get_reviews():
        err = require_admin()
        if err:
            return err
        try:
            page = max(1, int(request.args.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        limit = 10
        offset = (page - 1) * limit
        items, total = repo.get_all_reviews_admin(limit=limit, offset=offset)
        return jsonify({'reviews': items, 'total': total, 'page': page, 'pages': max(1, (total + limit - 1) // limit)})

    # ═══════════════════════════════════════════════
    #  SUPPORT CHAT — Favorite AI Agent
    # ═══════════════════════════════════════════════

    DEFAULT_SUPPORT_PROMPT = """Ты — Favorite AI Agent, ИИ-ассистент технической поддержки сервиса FavoriteAPI.
Никогда не говори, что ты "языковая модель Google" или любой другой компании. Ты — Favorite AI Agent.
Ты работаешь именно на сайте FavoriteAPI и помогаешь пользователям разобраться с сервисом.

══════════════════════════════════════════════════════════════════════
  ПОЛНАЯ ДОКУМЕНТАЦИЯ СЕРВИСА FAVORITEAPI — База знаний агента поддержки
══════════════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────────────────
§1. ЧТО ТАКОЕ FAVORITEAPI
────────────────────────────────────────────────────────────────────
FavoriteAPI — это БЕСПЛАТНЫЙ AI API-прокси, который предоставляет
программный доступ к мощным ИИ-моделям (Gemini и другим) через
Telegram-ботов. Сервис позволяет использовать AI-модели с огромным
контекстом (до 200 000 токенов!) совершенно бесплатно.

Ключевые преимущества:
• Бесплатный доступ к Gemini-моделям с контекстом до 200k токенов
• Полная совместимость с OpenAI API — работает с любым клиентом/SDK
• Поддержка Vision (анализ изображений)
• Dual-режим: автоперевод на английский экономит ~60% токенов
• Удобный веб-интерфейс с тестовым чатом, историей, настройками ключей
• Поддержка нескольких Telegram-аккаунтов и ключей

────────────────────────────────────────────────────────────────────
§2. ПРИНЦИП РАБОТЫ (АРХИТЕКТУРА)
────────────────────────────────────────────────────────────────────
1. Пользователь регистрируется на FavoriteAPI и привязывает
   Telegram-аккаунт (через API ID + API Hash + номер телефона
   либо session string от Telethon).
2. При Setup сервис автоматически:
   a) Авторизуется в Telegram под этим аккаунтом
   b) Находит Telegram-бота с ИИ (бот «Сэм» — ChatGPT-бот в Telegram)
   c) Выполняет обучение бота (отправляет тестовые сообщения)
   d) Сохраняет сессию и настройки
   Весь Setup занимает 3–5 минут.
3. Пользователь получает API-ключ формата: fa_sk_xxxxxxxxxxxxxxxx
4. Любой запрос через этот ключ:
   a) Принимается сервером FavoriteAPI
   b) Форматируется и отправляется в Telegram-бот через привязанный аккаунт
   c) Ответ бота (ИИ-ответ) получается и возвращается клиенту
      в формате OpenAI-совместимого JSON
5. Время ответа: 1–30 секунд (зависит от сложности и модели).
   Модели с "-thinking" работают медленнее, но дают более точные ответы.

────────────────────────────────────────────────────────────────────
§3. ДОСТУПНЫЕ МОДЕЛИ
────────────────────────────────────────────────────────────────────
Все модели основаны на Google Gemini.
Суффикс "-thinking" = включён режим размышлений (Chain-of-Thought).
Без суффикса = быстрый режим без CoT.
Суффикс "-64k" = контекст 64 000 токенов (меньше, но некоторые боты поддерживают только его).
Без суффикса числа = контекст 200 000 токенов.

Полный список моделей:
  gemini-3.0-flash-thinking      — 200k, Vision ✓ — ФЛАГМАН: мышление + Flash (рекомендуется)
  gemini-3.0-flash               — 200k, Vision ✓ — Быстрый, без мышления
  gemini-2.5-flash-thinking      — 200k, Vision ✓ — Gemini 2.5: мышление + Flash
  gemini-2.5-flash               — 200k, Vision ✓ — Gemini 2.5: быстрый
  gemini-2.5-mini-thinking       — 200k, Vision ✓ — Лёгкий с мышлением
  gemini-2.5-mini                — 200k, Vision ✓ — Самый лёгкий и быстрый
  gemini-2.5-flash-thinking-64k  — 64k,  Vision ✓ — Gemini 2.5: мышление, 64k контекст
  gemini-2.5-flash-64k           — 64k,  Vision ✓ — Gemini 2.5: быстрый, 64k контекст
  gemini-3.0-flash-thinking-64k  — 64k,  Vision ✓ — Gemini 3.0: мышление, 64k контекст
  gemini-3.0-flash-64k           — 64k,  Vision ✓ — Gemini 3.0: быстрый, 64k контекст
  gemini-1.5-robotics-er-preview — 200k, Vision ✓ — Специализированная, экспериментальная

Модель по умолчанию при создании ключа: gemini-3.0-flash-thinking

────────────────────────────────────────────────────────────────────
§4. ПОЛНАЯ ДОКУМЕНТАЦИЯ API
────────────────────────────────────────────────────────────────────
Базовый URL: https://<домен-сервиса>
Аутентификация: заголовок Authorization: Bearer <ваш-ключ>
Формат ключа: fa_sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

━━━ 4.1. POST /api/v1/chat/completions ━━━
Главный эндпоинт. ПОЛНОСТЬЮ совместим с OpenAI Chat Completions API.
Можно использовать любой OpenAI SDK, просто поменяв base_url и api_key.

Минимальный запрос:
  POST /api/v1/chat/completions
  Authorization: Bearer fa_sk_...
  Content-Type: application/json
  {
    "model": "gemini-3.0-flash-thinking",
    "messages": [
      {"role": "user", "content": "Привет! Как дела?"}
    ]
  }

Расширенный запрос с system message:
  {
    "model": "gemini-2.5-flash",
    "messages": [
      {"role": "system", "content": "Ты полезный ассистент. Отвечай на русском."},
      {"role": "user", "content": "Объясни квантовую запутанность"},
      {"role": "assistant", "content": "Квантовая запутанность — это..."},
      {"role": "user", "content": "Дай пример"}
    ]
  }

Запрос с изображением (Vision):
  {
    "model": "gemini-3.0-flash",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Что изображено на картинке?"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<base64>"}}
      ]
    }]
  }

Ответ (200 OK):
  {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "model": "gemini-3.0-flash-thinking",
    "choices": [{
      "index": 0,
      "message": {"role": "assistant", "content": "Привет! Всё хорошо."},
      "finish_reason": "stop"
    }],
    "usage": {
      "prompt_tokens": 45,
      "completion_tokens": 28,
      "total_tokens": 73
    }
  }

ВАЖНО: параметр "stream": true НЕ поддерживается (стриминг отсутствует).

━━━ 4.2. GET /api/models ━━━
Список всех доступных моделей. Авторизация НЕ нужна.
Ответ: {"models": [{"id": "...", "displayName": "...", "contextK": 200,
                     "supportsVision": true, "hasThinking": true}, ...]}

━━━ 4.3. GET /api/keys ━━━
Список API-ключей текущего пользователя (требует cookie-сессии, только через веб).

━━━ 4.4. POST /api/keys ━━━
Создать новый API-ключ. Требует настроенного Telegram-аккаунта.
Body: {"name": "Название ключа"}
Ответ (201): {"key": {"id": "...", "key_value": "fa_sk_...", "name": "...", ...}}

━━━ 4.5. DELETE /api/keys/<id> ━━━
Удалить (деактивировать) ключ. Ответ: {"ok": true}

━━━ 4.6. PUT /api/keys/<id> ━━━
Обновить настройки ключа. Body (все поля опциональны):
  {
    "name": "Новое название",
    "defaultModel": "gemini-3.0-flash",
    "skipHints": false,
    "dualMode": true,
    "translatorAccountId": "acc_id_или_null"
  }

━━━ 4.7. POST /api/keys/<id>/regen ━━━
Перегенерировать ключ (старое значение fa_sk_... перестаёт работать).
Ответ: {"key": {"rawKey": "fa_sk_ПОЛНОЕ_ЗНАЧЕНИЕ", ...}}
ВАЖНО: rawKey показывается только один раз — при регенерации.

━━━ 4.8. GET /api/stats/global ━━━
Глобальная статистика сервиса. Авторизация НЕ нужна.
Ответ: {"users": 123, "todayRequests": 456}

━━━ Примеры использования с Python (OpenAI SDK) ━━━
  import openai
  client = openai.OpenAI(
      base_url="https://<домен>/api/v1",
      api_key="fa_sk_ваш_ключ"
  )
  response = client.chat.completions.create(
      model="gemini-3.0-flash-thinking",
      messages=[{"role": "user", "content": "Привет!"}]
  )
  print(response.choices[0].message.content)

━━━ Пример с curl ━━━
  curl -X POST https://<домен>/api/v1/chat/completions \
    -H "Authorization: Bearer fa_sk_ваш_ключ" \
    -H "Content-Type: application/json" \
    -d '{"model":"gemini-3.0-flash","messages":[{"role":"user","content":"Привет"}]}'

────────────────────────────────────────────────────────────────────
§5. КОДЫ ОШИБОК И РЕШЕНИЯ
────────────────────────────────────────────────────────────────────
200 KEY_BUSY_301   — Ключ занят параллельным запросом.
                     Решение: подождать 1–2 секунды и повторить.
400 EMPTY_REQUEST  — Пустое сообщение в запросе.
                     Решение: добавить текст в поле content.
400 MDL_INVALID_403— Неверный ID модели.
                     Решение: использовать ID из GET /api/models.
400 Диалог завершён— При попытке написать в закрытый чат поддержки.
                     Решение: начать новый диалог поддержки.
401 Unauthorized   — Отсутствует или неверный API-ключ.
                     Решение: проверить заголовок Authorization: Bearer fa_sk_...
402 KEY_NO_TG_303  — К ключу не привязан TG-аккаунт или Setup не завершён.
                     Решение: зайти в ЛК → Настройка Telegram, проверить статус.
404 MODEL_NOT_FOUND— Модель не найдена.
                     Решение: использовать актуальный список из /api/models.
429 RATE_LIMIT     — Превышен лимит запросов.
                     Решение: подождать несколько секунд.
503 TG_TIMEOUT     — Telegram-бот не ответил вовремя.
                     Решение: повторить запрос, сократить длину, сменить модель.
503 TG_NOT_READY   — Telegram-сессия недоступна.
                     Решение: переподключить аккаунт в настройках ЛК.

────────────────────────────────────────────────────────────────────
§6. ПОШАГОВАЯ ИНСТРУКЦИЯ: КАК НАСТРОИТЬ TELEGRAM-АККАУНТ
────────────────────────────────────────────────────────────────────
Шаг 1. Перейти на https://my.telegram.org → войти под своим номером Telegram.
Шаг 2. Открыть раздел "API development tools" → создать приложение (любое название).
Шаг 3. Скопировать API ID (число, например 12345678) и API Hash (строка 32 символа).
Шаг 4. Зайти в Личный кабинет FavoriteAPI → раздел "Настройка Telegram".
Шаг 5. Ввести API ID, API Hash и номер телефона (формат: +79001234567).
Шаг 6. Telegram пришлёт код в приложение → ввести этот код на сайте.
Шаг 7. Дождаться завершения Setup (~3–5 минут): бот будет найден и обучен.
        Прогресс отображается в разделе "Настройка выполняется" (6 шагов).
Шаг 8. После завершения — API-ключ автоматически появится в "API Ключи".

АЛЬТЕРНАТИВА — Session String:
Можно использовать готовую StringSession от Telethon вместо телефона.
Вкладка "По сессии" в форме настройки. Загрузить .session файл или вставить строку.

ВАЖНО: каждый TG-аккаунт можно привязать только к одному пользователю FavoriteAPI.
Для Dual-режима нужен ВТОРОЙ отдельный TG-аккаунт с отдельным Setup.

────────────────────────────────────────────────────────────────────
§7. ФУНКЦИИ ЛИЧНОГО КАБИНЕТА (ВЕБ-ИНТЕРФЕЙС)
────────────────────────────────────────────────────────────────────

▶ Дашборд (главная страница после входа):
  • Статус Telegram-аккаунта (зелёный = подключён, красный = не подключён)
  • Список API-ключей с масками значений (вид: fa_sk_3•••••94c)
  • Статистика по каждому ключу: запросов в месяц, среднее время ответа
  • Кнопки действий для каждого ключа:
    - Открыть чат (тестовый чат с этим ключом)
    - Скачать сессию (скачать session_string.txt)
    - История (журнал последних 50 запросов)
    - Настройки (шестерёнка — настройки ключа)
    - Копировать ключ
    - Перегенерировать ключ (старый перестаёт работать!)
    - Удалить ключ

▶ Тестовый чат (раздел Чат):
  • Выбор ключа и модели прямо в шапке чата
  • Индикатор размера контекста (в KB и % от лимита)
  • Кнопка "Сбросить" — очищает контекст разговора
  • Поддержка изображений (прикрепить через скрепку)
  • Markdown-форматирование ответов

▶ Настройки ключа (кнопка шестерёнки в дашборде):
  • Название ключа — произвольное имя для идентификации
  • Модель по умолчанию — какую модель использует этот ключ
    ВНИМАНИЕ: смена модели сбрасывает контекст диалога!
  • Скрыть подсказки бота (Skip hints) — фильтрует служебные
    сообщения-лампочки от бота
  • Dual-режим (EN-экономия) — переключатель автоперевода
    При включении появляется поле "Аккаунт-переводчик"
  • Аккаунт-переводчик — второй TG-аккаунт для перевода запросов
    (требует второй аккаунт с завершённым Setup)

▶ История запросов:
  • Список последних 50 запросов через этот ключ
  • Для каждого: дата, время, модель, объём запроса/ответа, время обработки

▶ Уведомления:
  • Системные уведомления от администратора
  • Уведомления по результатам обращений в поддержку

▶ Поддержка (текущий раздел):
  • AI-агент отвечает на вопросы по сервису
  • Можно прикреплять скриншоты
  • При завершении диалога — отчёт автоматически отправляется
    администратору (если была нерешённая проблема)

────────────────────────────────────────────────────────────────────
§8. DUAL-РЕЖИМ — ЭКОНОМИЯ ТОКЕНОВ (ПОДРОБНО)
────────────────────────────────────────────────────────────────────
Проблема: русский язык требует ~3.3 токена на слово, а английский ~1.3.
При большом контексте это критично — лимит 200k токенов исчерпывается быстрее.

Решение — Dual-режим:
1. Пользователь пишет запрос на русском.
2. FavoriteAPI отправляет текст второму TG-аккаунту (переводчику).
3. Переводчик переводит запрос на английский.
4. Переведённый текст отправляется основному боту с ИИ.
5. ИИ отвечает (обычно на языке запроса — английском, но можно
   задать язык ответа через system message).

Математика экономии:
  1 слово на русском  ≈ 3.3 токена (кириллица)
  1 слово на английском ≈ 1.3 токена (латиница)
  Экономия = 3.3 / 1.3 ≈ 2.5x (около 60%) при активном Dual-режиме

Требования:
  • Второй Telegram-аккаунт (ОТДЕЛЬНЫЙ от основного)
  • Setup второго аккаунта должен быть полностью завершён
  • В настройках ключа: включить Dual-режим + выбрать аккаунт-переводчик

Ограничения:
  • Если нет второго аккаунта — поле "Аккаунт-переводчик" показывает
    "Нет готовых аккаунтов" → нужно добавить второй аккаунт
  • Время ответа немного увеличивается (дополнительный шаг перевода)

────────────────────────────────────────────────────────────────────
§9. РАСПРОСТРАНЁННЫЕ ПРОБЛЕМЫ И РЕШЕНИЯ
────────────────────────────────────────────────────────────────────

П: Ошибка 503 TG_TIMEOUT при запросах
Р: Telegram-бот не ответил вовремя. Попробуйте:
   1) Повторить запрос (боты иногда медленно реагируют)
   2) Сократить длину сообщения
   3) Попробовать более быструю модель (без -thinking)
   4) Если проблема постоянная — переподключить аккаунт в ЛК

П: Ошибка 402 KEY_NO_TG_303
Р: К ключу не привязан или не настроен TG-аккаунт.
   Зайдите в ЛК → Настройка Telegram → проверьте статус.
   Если Setup завис на шаге — нажмите "Повторить с шага X".

П: Долгое время ответа (больше 30 секунд)
Р: Нормально для -thinking моделей и длинных запросов.
   Для скорости используйте gemini-3.0-flash или gemini-2.5-mini.

П: Ответ обрезается / неполный
Р: Достигнут лимит контекста. Сбросьте контекст кнопкой "Сбросить"
   в тестовом чате или начните новый диалог в своём приложении.

П: Ошибка "Код не принят" при Setup
Р: Коды Telegram действуют ~1 минуту. Запросите новый код и введите быстрее.

П: "Нет готовых аккаунтов" в Dual-режиме
Р: Нужен второй TG-аккаунт с завершённым Setup.
   Добавьте второй аккаунт (другой номер телефона) и дождитесь Setup.

П: Ключ fa_sk_... перестал работать
Р: Ключ мог быть перегенерирован или удалён. Проверьте в ЛК.
   При регенерации старый ключ СРАЗУ перестаёт работать.

П: Модель не отвечает на русском языке
Р: Добавьте system message: {"role":"system","content":"Всегда отвечай на русском."}

П: Как использовать с Python / JavaScript / другим SDK
Р: Любой OpenAI-совместимый SDK работает. Нужно только:
   - base_url = "https://<домен-сервиса>/api/v1"
   - api_key = "fa_sk_ваш_ключ"
   - model = любой ID из GET /api/models

П: Хочу использовать несколько ключей / аккаунтов
Р: Можно создать несколько ключей — каждый будет независимым.
   Для второго ключа нужен второй TG-аккаунт (или тот же, если Setup уже завершён).

────────────────────────────────────────────────────────────────────
§10. ПРАВИЛА РАБОТЫ АГЕНТА ПОДДЕРЖКИ
────────────────────────────────────────────────────────────────────
• Отвечай дружелюбно, по существу, на русском языке.
• ВСЕГДА ориентируйся на логин пользователя из раздела КОНТЕКСТ ТЕКУЩЕГО ОБРАЩЕНИЯ.
• Каждый диалог ведётся с конкретным пользователем — его логин указан в каждом сообщении.
• Если не знаешь точного ответа — честно скажи об этом, не придумывай.
• Не давай обещаний от имени администрации.
• При сообщении о баге — уточни детали (шаги воспроизведения, ошибку, браузер).
• Представляйся кратко: "Favorite AI Agent | Поддержка FavoriteAPI"
• При ПЕРВОМ сообщении в диалоге — поприветствуй пользователя по его логину.
• Если проблема нерешаема без вмешательства администратора — сообщи об этом
  и предложи завершить диалог, чтобы информация дошла до администратора.
"""

    def _get_support_prompt():
        custom = repo.get_admin_setting('support_system_prompt', '')
        if custom and custom.strip():
            return custom.strip()
        return DEFAULT_SUPPORT_PROMPT

    def _get_support_prompt_with_context(uid):
        base_prompt = _get_support_prompt()
        username = session.get('username') or ''
        if not username and uid:
            user = repo.get_user_by_id(uid)
            username = user.get('username') if user else ''
        from freeapi.database import msk_now
        return (
            f'{base_prompt}\n\n'
            f'=== КОНТЕКСТ ТЕКУЩЕГО ОБРАЩЕНИЯ ===\n'
            f'Логин пользователя: {username or "неизвестно"}\n'
            f'Текущие дата и время: {msk_now()} МСК\n\n'
            f'{support_project_context()}'
        )

    def _format_support_dialog_for_ai(messages, username=''):
        lines = ['=== ИСТОРИЯ ДИАЛОГА ПОДДЕРЖКИ ===']
        user_label = f'Пользователь (@{username})' if username else 'Пользователь'
        for msg in messages:
            role = msg.get('role')
            if role == 'agent':
                role_name = 'Favorite AI Agent'
            elif role == 'user':
                role_name = user_label
            else:
                role_name = str(role or 'unknown')
            content = msg.get('content') or ''
            if msg.get('image_data'):
                content = (content + '\n' if content else '') + '[Пользователь приложил изображение. Если изображение доступно в текущем сообщении, проанализируй его.]'
            lines.append(f'{role_name}: {content}')
        closer = f'Ответь на последнее сообщение пользователя (@{username}) как Favorite AI Agent | Поддержка FavoriteAPI.' if username else 'Ответь на последнее сообщение пользователя как Favorite AI Agent | Поддержка FavoriteAPI.'
        lines.append(closer)
        return '\n\n'.join(lines)

    SUPPORT_CLOSE_PROMPT = """Ты — Favorite AI Agent. Проанализируй следующий диалог поддержки и реши:
нужно ли отправить отчёт администратору (ReZero)?

Отправляй отчёт ТОЛЬКО если:
- Пользователь сообщил о баге, критической ошибке или уязвимости
- Пользователь сообщил о проблеме, которую ты не смог решить
- Есть техническая проблема требующая вмешательства администратора
- Пользователь выражает серьёзное недовольство

НЕ отправляй отчёт если:
- Вопрос был решён в диалоге
- Это общий вопрос о работе сервиса
- Пользователь просто поболтал

Ответь СТРОГО в формате JSON без лишнего текста:
{
  "needs_report": true/false,
  "report_text": "Краткое описание проблемы для администратора (или null если не нужен отчёт)",
  "summary": "Одна фраза — о чём был диалог"
}"""

    @app.get('/api/support/chat')
    def support_get_chat():
        err = require_user()
        if err:
            return err
        uid = current_user_id()
        chat = repo.get_open_support_chat(uid)
        if not chat:
            return jsonify({'chat': None, 'messages': []})
        messages = repo.get_support_messages(chat['id'])
        return jsonify({'chat': chat, 'messages': messages})

    @app.post('/api/support/chat')
    def support_send_message():
        err = require_user()
        if err:
            return err
        uid = current_user_id()
        data = request.get_json(silent=True) or {}
        content = (data.get('content') or '').strip()
        image_data = data.get('image_data')

        if not content and not image_data:
            return error('Сообщение не может быть пустым', 400)
        if len(content) > 4000:
            return error('Сообщение слишком длинное', 400)

        chat = repo.get_open_support_chat(uid)
        if not chat:
            subject = content[:80] if content else 'Запрос с изображением'
            chat = repo.create_support_chat(uid, subject)

        if chat['status'] == 'closed':
            return error('Диалог завершён. Начните новый.', 400)

        repo.add_support_message(chat['id'], 'user', content or '[изображение]', image_data)

        all_messages = repo.get_support_messages(chat['id'])
        _support_username = session.get('username') or ''
        if not _support_username and uid:
            _uobj = repo.get_user_by_id(uid)
            _support_username = _uobj.get('username') if _uobj else ''
        support_request_text = (
            f'{_get_support_prompt_with_context(uid)}\n\n'
            f'{_format_support_dialog_for_ai(all_messages, _support_username)}'
        )
        last_user_message = next((m for m in reversed(all_messages) if m.get('role') == 'user'), None)
        if last_user_message and last_user_message.get('image_data'):
            ai_content = [
                {'type': 'text', 'text': support_request_text},
                {'type': 'image_url', 'image_url': {'url': last_user_message['image_data']}}
            ]
        else:
            ai_content = support_request_text
        ai_messages = [{'role': 'user', 'content': ai_content}]

        try:
            support_key_id = repo.get_admin_setting('support_key_id', '')
            if not support_key_id:
                support_key_id = repo.get_admin_setting('agent_key_id', '')
            if support_key_id:
                from freeapi.database import db as _db, row as _row
                with _db() as conn:
                    key = _row(conn.execute('SELECT * FROM api_keys WHERE id=? AND is_active=1', (support_key_id,)).fetchone())
            else:
                key = None

            if key:
                from freeapi.tg import run_chat
                from freeapi.models import DEFAULT_MODEL_ID
                _support_model = repo.get_admin_setting('support_model', '') or key.get('default_model') or DEFAULT_MODEL_ID
                answer = run_chat(key, _support_model, ai_messages)
            else:
                answer = ('Привет! Я Favorite AI Agent — ваш помощник по сервису FavoriteAPI.\n\n'
                          'Для работы AI-поддержки администратору необходимо настроить ключ агента поддержки. '
                          'Пока что я могу сообщить о вашем вопросе администратору при завершении диалога.\n\n'
                          f'Ваш вопрос: {content or "(изображение)"}')

        except Exception as exc:
            logger.error('[Support] Ошибка AI ответа: %s', exc)
            answer = 'Извините, возникла временная ошибка. Попробуйте ещё раз или завершите диалог — я передам ваш запрос администратору.'

        repo.add_support_message(chat['id'], 'agent', answer, None)
        user_msg = repo.get_support_messages(chat['id'])[-2] if len(all_messages) > 0 else None
        agent_msg = repo.get_support_messages(chat['id'])[-1]

        return jsonify({
            'user_message': {'id': repo.get_support_messages(chat['id'])[-2]['id'] if len(repo.get_support_messages(chat['id'])) > 1 else None, 'content': content, 'role': 'user'},
            'agent_message': agent_msg,
            'chat': chat
        })

    @app.post('/api/support/close')
    def support_close_chat():
        err = require_user()
        if err:
            return err
        uid = current_user_id()
        chat = repo.get_open_support_chat(uid)
        if not chat:
            return jsonify({'ok': True, 'reported': False, 'info': 'Нет активного диалога'})

        messages = repo.get_support_messages(chat['id'])
        if not messages:
            repo.close_support_chat(chat['id'], None)
            return jsonify({'ok': True, 'reported': False})

        dialog_text = '\n'.join([
            f"{'Пользователь' if m['role'] == 'user' else 'Агент'}: {m['content']}" + (' [прикреплено изображение]' if m.get('image_data') else '')
            for m in messages
        ])

        close_messages = [
            {'role': 'user', 'content': f"{SUPPORT_CLOSE_PROMPT}\n\nДИАЛОГ:\n{dialog_text}"}
        ]

        reported = False
        report_text = None

        try:
            support_key_id = repo.get_admin_setting('support_key_id', '')
            if not support_key_id:
                support_key_id = repo.get_admin_setting('agent_key_id', '')
            key = None
            if support_key_id:
                from freeapi.database import db as _db, row as _row
                with _db() as conn:
                    key = _row(conn.execute('SELECT * FROM api_keys WHERE id=? AND is_active=1', (support_key_id,)).fetchone())

            if key:
                from freeapi.tg import run_chat
                from freeapi.models import DEFAULT_MODEL_ID
                import json as _json
                _support_model_close = repo.get_admin_setting('support_model', '') or key.get('default_model') or DEFAULT_MODEL_ID
                raw = run_chat(key, _support_model_close, close_messages)
                start = raw.find('{')
                end = raw.rfind('}')
                if start != -1 and end != -1:
                    decision = _json.loads(raw[start:end+1])
                    if decision.get('needs_report'):
                        report_text = decision.get('report_text', '')
                        reported = True
        except Exception as exc:
            logger.error('[Support] Ошибка анализа диалога: %s', exc)

        if not reported:
            problem_words = ('баг', 'ошибк', 'не работает', 'сломал', 'сломано', 'уязвим', 'критич', 'проблем', 'не смог', 'не получается', 'завис', 'краш', 'crash', 'bug', 'error', 'fail')
            lowered = dialog_text.lower()
            if any(word in lowered for word in problem_words):
                user = repo.get_user_by_id(uid)
                username = user['username'] if user else 'неизвестен'
                report_text = f'Пользователь {username} завершил диалог поддержки с признаками нерешённой проблемы.\n\n{dialog_text[:1800]}'
                reported = True

        repo.close_support_chat(chat['id'], report_text)

        if reported and report_text:
            user = repo.get_user_by_id(uid)
            username = user['username'] if user else 'неизвестен'
            repo.create_admin_notification(
                review_id=None,
                review_text=f"[SUPPORT] {report_text}\n\nПользователь: {username}",
                review_score=0,
                review_author=username,
                ai_response=f"Диалог завершён. Отчёт передан администратору.",
                ai_advice=f"Обратите внимание на обращение пользователя {username}.\n{report_text}"
            )

        return jsonify({'ok': True, 'reported': reported, 'report_text': report_text})
