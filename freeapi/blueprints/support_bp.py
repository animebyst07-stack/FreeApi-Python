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

bp = Blueprint('support', __name__)

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


@bp.get('/api/support/chat')
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


@bp.post('/api/support/chat')
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
    # Валидация изображения: MIME + размер (защита от OOM в Termux)
    if image_data is not None:
        _ALLOWED_MIME = ('data:image/jpeg;base64,', 'data:image/jpg;base64,', 'data:image/png;base64,', 'data:image/gif;base64,', 'data:image/webp;base64,', 'data:image/heic;base64,', 'data:image/heif;base64,')
        if not isinstance(image_data, str):
            return error('Некорректный формат изображения', 400)
        if not any(image_data[:40].lower().startswith(m) for m in _ALLOWED_MIME):
            return error('Поддерживаются только изображения (JPEG, PNG, GIF, WebP)', 400)
        if len(image_data) > 14 * 1024 * 1024:  # ~10MB raw → ~14MB base64
            return error('Изображение слишком большое (максимум 10 МБ)', 400)

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


@bp.post('/api/support/close')
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
