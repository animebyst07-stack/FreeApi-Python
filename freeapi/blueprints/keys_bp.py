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

bp = Blueprint('keys', __name__)

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

@bp.get('/api/keys')
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


@bp.post('/api/keys')
def keys_create():
    blocked = require_user()
    if blocked:
        return blocked
    return error('Новый ключ создаётся только после полной настройки нового Telegram-аккаунта. Запустите SetupFlow через /api/tg/setup.', 409)


@bp.get('/api/keys/<key_id>')
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


@bp.put('/api/keys/<key_id>')
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


@bp.delete('/api/keys/<key_id>')
def keys_delete(key_id):
    blocked = require_user()
    if blocked:
        return blocked
    key = repo.get_user_key(current_user_id(), key_id)
    if not key:
        return error('Ключ не найден', 404)
    repo.deactivate_key(key_id)
    return jsonify({'ok': True})


@bp.post('/api/keys/<key_id>/regen')
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


@bp.get('/api/keys/<key_id>/logs')
def keys_logs(key_id):
    blocked = require_user()
    if blocked:
        return blocked
    key = repo.get_user_key(current_user_id(), key_id)
    if not key:
        return error('Ключ не найден', 404)
    return jsonify({'logs': repo.get_key_logs(key_id)})


@bp.get('/api/keys/<key_id>/session')
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

