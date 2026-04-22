"""Общие helpers для всех blueprints (вынесены из старого freeapi/routes.py)."""
import json
import logging
import os
import time

from flask import jsonify, request, session

logger = logging.getLogger('freeapi')

from freeapi import repositories as repo


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
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
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
