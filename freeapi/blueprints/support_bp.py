# Auto-generated blueprint (см. план рефакторинга, шаг 0.2).
# Бизнес-логика не менялась: код перенесён из freeapi/routes.py как есть.
import asyncio
import json
import logging
import os
import re
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
from freeapi.blueprints.admin_bp import DEFAULT_SUPPORT_PROMPT
from freeapi.support_docs import docs_index_text, get_doc

bp = Blueprint('support', __name__)

# Инструкция для ИИ как пользоваться тегами документации.
# Формат [[doc:NAME]] выбран потому, что он не встречается в обычной речи,
# в Markdown и в коде, и его легко парсить простой регуляркой.
_DOC_TAG_INSTRUCTIONS = """=== КАК ПОЛЬЗОВАТЬСЯ ДОКУМЕНТАЦИЕЙ ===
Ты НЕ должен помнить устройство сайта наизусть. Когда пользователь спрашивает
о конкретном разделе/механике, действуй как живой агент:

  1) Сначала коротко напиши пользователю, что ты собираешься сделать
     ("Сейчас посмотрю, как работают отзывы..."). Это твой «шаг работы»,
     он отображается отдельным сообщением в чате.
  2) Сразу после промежуточной фразы поставь тег вида [[doc:NAME]] на
     отдельной строке. Можешь поставить несколько тегов подряд, если нужно
     заглянуть сразу в пару разделов.
  3) Сервер автоматически подгрузит тебе содержимое запрошенных разделов
     и пришлёт следующим сообщением. Тогда ты пишешь полноценный ответ
     пользователю, опираясь на свежеподгруженную документацию.

Пример:
    Сейчас уточню, как у нас работают отзывы.
    [[doc:reviews]]

После того как сервер пришлёт текст справки, отвечай по существу — без
повторных тегов, если уже всё ясно. Если пользователь спросит про другой
раздел — снова сделай шаг + тег.

ВАЖНО: не выдумывай разделы, которых нет в списке ниже. Если подходящего
тега нет — отвечай по общим принципам и при необходимости предложи
завершить диалог, чтобы вопрос дошёл до администратора.
"""


def _get_support_prompt():
    custom = repo.get_admin_setting('support_system_prompt', '')
    if custom and custom.strip():
        return custom.strip()
    return DEFAULT_SUPPORT_PROMPT


def _get_support_prompt_with_context(uid, username_override=None):
    """Полный системный промпт для первого сообщения нового диалога:
    базовый промпт + инструкция по тегам + индекс документации + контекст
    обращения. Тяжёлый дамп исходников (support_project_context) больше
    не используется — вместо него ИИ сам подгружает нужную справку через
    [[doc:NAME]] (см. freeapi/support_docs.py).

    username_override — обязателен, если функция вызывается ВНЕ контекста
    Flask-запроса (например, из фонового worker-потока SSE-стрима).
    Без него мы пытаемся достать username из session, что в потоке
    приведёт к 'Working outside of request context'."""
    base_prompt = _get_support_prompt()
    if username_override is not None:
        username = username_override or ''
    else:
        username = session.get('username') or ''
    if not username and uid:
        user = repo.get_user_by_id(uid)
        username = user.get('username') if user else ''
    from freeapi.database import msk_now
    return (
        f'{base_prompt}\n\n'
        f'{_DOC_TAG_INSTRUCTIONS}\n\n'
        f'{docs_index_text()}\n\n'
        f'=== КОНТЕКСТ ТЕКУЩЕГО ОБРАЩЕНИЯ ===\n'
        f'Логин пользователя: {username or "неизвестно"}\n'
        f'Текущие дата и время: {msk_now()} МСК\n'
    )


# Регулярка тегов документации в ответе ИИ. Регистронезависимо, имя — латиница,
# цифры и _. Захватываем имя в группу 1.
_DOC_TAG_RE = re.compile(r'\[\[doc:([A-Za-z0-9_]+)\]\]', re.IGNORECASE)
# Лимит итераций, чтобы ИИ не зациклился, бесконечно перезапрашивая доки.
_MAX_DOC_ITERATIONS = 3

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

SUPPORT_CLOSE_PROMPT = """Ты — Favorite AI Agent. ВАЖНО: сейчас это служебный
запрос на анализ — не отвечай пользователю, не учитывай свою текущую память
о других активных диалогах. Анализируй ТОЛЬКО приведённый ниже диалог
(пользователь там обозначен своим логином `Пользователь (@username)`) и реши:
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


def _support_validate_payload(data):
    """Общая валидация для обычного и стримящего эндпоинтов отправки сообщения.
    Возвращает (content, image_data, err_response_or_None)."""
    content = (data.get('content') or '').strip()
    image_data = data.get('image_data')
    if not content and not image_data:
        return content, image_data, error('Сообщение не может быть пустым', 400)
    if len(content) > 4000:
        return content, image_data, error('Сообщение слишком длинное', 400)
    if image_data is not None:
        _ALLOWED_MIME = ('data:image/jpeg;base64,', 'data:image/jpg;base64,', 'data:image/png;base64,', 'data:image/gif;base64,', 'data:image/webp;base64,', 'data:image/heic;base64,', 'data:image/heif;base64,')
        if not isinstance(image_data, str):
            return content, image_data, error('Некорректный формат изображения', 400)
        if not any(image_data[:40].lower().startswith(m) for m in _ALLOWED_MIME):
            return content, image_data, error('Поддерживаются только изображения (JPEG, PNG, GIF, WebP)', 400)
        if len(image_data) > 14 * 1024 * 1024:
            return content, image_data, error('Изображение слишком большое (максимум 10 МБ)', 400)
    return content, image_data, None


def _support_pick_key():
    """Возвращает (key_row|None, model_id) для агента поддержки."""
    support_key_id = repo.get_admin_setting('support_key_id', '') or repo.get_admin_setting('agent_key_id', '')
    if not support_key_id:
        return None, None
    from freeapi.database import db as _db, row as _row
    with _db() as conn:
        key = _row(conn.execute('SELECT * FROM api_keys WHERE id=? AND is_active=1', (support_key_id,)).fetchone())
    if not key:
        return None, None
    from freeapi.models import DEFAULT_MODEL_ID
    model = repo.get_admin_setting('support_model', '') or key.get('default_model') or DEFAULT_MODEL_ID
    return key, model


def _support_run_ai(uid, chat, content, image_data, on_step=None, username=None):
    """Главный AI-цикл: первое сообщение → возможные итерации с документацией → финальный ответ.

    on_step(step_msg_dict) — необязательный колбэк, вызывается СРАЗУ после
    сохранения каждого промежуточного шага «Читаю документацию: ...»
    в БД (для SSE-стрима). Возвращает (steps_list, final_answer_text).

    username — желательно передавать из endpoint'а (request-context).
    Если функция запускается в фоновом потоке (SSE-worker), доступа к
    session нет, и попытка прочитать его упадёт с 'Working outside of
    request context'. См. _get_support_prompt_with_context().
    """
    _support_username = (username or '').strip()
    if not _support_username:
        # Fallback: пытаемся достать из session (только если есть request-контекст).
        try:
            _support_username = session.get('username') or ''
        except RuntimeError:
            _support_username = ''
    if not _support_username and uid:
        _uobj = repo.get_user_by_id(uid)
        _support_username = _uobj.get('username') if _uobj else ''

    user_label = f'Пользователь (@{_support_username})' if _support_username else 'Пользователь'
    closer = 'Ответь на это сообщение как Favorite AI Agent | Поддержка FavoriteAPI.'
    img_note = '\n[Пользователь приложил изображение — проанализируй его.]' if image_data else ''
    short_user_text = f'{user_label}: {content or "[изображение]"}{img_note}\n\n{closer}'

    def _build_full_text():
        return (
            f'{_get_support_prompt_with_context(uid, username_override=_support_username)}\n\n'
            f'=== ТЕКУЩЕЕ СООБЩЕНИЕ ===\n'
            f'{short_user_text}'
        )

    def _send(key, model, text):
        if image_data:
            ai_content = [
                {'type': 'text', 'text': text},
                {'type': 'image_url', 'image_url': {'url': image_data}},
            ]
        else:
            ai_content = text
        return run_chat(key, model, [{'role': 'user', 'content': ai_content}])

    steps_added = []
    answer = None
    try:
        key, _support_model = _support_pick_key()
        if key:
            all_messages = repo.get_support_messages(chat['id'])
            user_msgs_count = sum(1 for m in all_messages if m.get('role') == 'user')
            is_first = (user_msgs_count == 1)

            text_to_send = _build_full_text() if is_first else short_user_text
            try:
                answer = _send(key, _support_model, text_to_send)
            except RuntimeError as exc:
                if 'CTX_LIMIT' in str(exc):
                    logger.warning('[Support] CTX_LIMIT — сбрасываем контекст и повторяем с полным промптом')
                    try: run_control(key, '/reset')
                    except Exception: pass
                    answer = _send(key, _support_model, _build_full_text())
                else:
                    raise

            iteration = 0
            while iteration < _MAX_DOC_ITERATIONS:
                tags = list(_DOC_TAG_RE.finditer(answer or ''))
                if not tags:
                    break
                step_text = (answer[:tags[0].start()] or '').strip()
                requested = []
                seen = set()
                for m in tags:
                    name = m.group(1).lower()
                    if name not in seen:
                        seen.add(name)
                        requested.append(name)
                step_msg = repo.add_support_message(
                    chat['id'], 'agent_step',
                    step_text or '(читаю документацию...)',
                    ','.join(requested),
                )
                steps_added.append(step_msg)
                if on_step:
                    try: on_step(step_msg)
                    except Exception as _exc:
                        logger.warning('[Support] on_step callback error: %s', _exc)
                parts = []
                for name in requested:
                    doc = get_doc(name)
                    if doc:
                        parts.append(f'=== ДОКУМЕНТАЦИЯ: {name} ===\n{doc}')
                    else:
                        parts.append(
                            f'=== ДОКУМЕНТАЦИЯ: {name} ===\n'
                            '(такого раздела в реестре нет — отвечай по общим '
                            'принципам или предложи завершить диалог.)'
                        )
                followup = (
                    '\n\n'.join(parts)
                    + '\n\nДокументация загружена. Теперь дай пользователю полноценный '
                    'ответ по существу. Не ставь новые теги [[doc:...]], если уже всё ясно.'
                )
                try:
                    answer = _send(key, _support_model, followup)
                except RuntimeError as exc:
                    if 'CTX_LIMIT' in str(exc):
                        logger.warning('[Support] CTX_LIMIT внутри doc-loop, отдаём шаг как финальный ответ')
                        try: run_control(key, '/reset')
                        except Exception: pass
                        answer = step_text or 'Извините, не получилось загрузить документацию.'
                        break
                    raise
                iteration += 1

            if answer:
                answer = _DOC_TAG_RE.sub('', answer).strip()
        else:
            answer = ('Привет! Я Favorite AI Agent — ваш помощник по сервису FavoriteAPI.\n\n'
                      'Для работы AI-поддержки администратору необходимо настроить ключ агента поддержки. '
                      'Пока что я могу сообщить о вашем вопросе администратору при завершении диалога.\n\n'
                      f'Ваш вопрос: {content or "(изображение)"}')
    except Exception as exc:
        logger.error('[Support] Ошибка AI ответа: %s', exc)
        answer = 'Извините, возникла временная ошибка. Попробуйте ещё раз или завершите диалог — я передам ваш запрос администратору.'

    return steps_added, (answer or '')


@bp.post('/api/support/chat/stream')
def support_send_message_stream():
    """SSE-версия отправки сообщения. Шлёт события в порядке появления:
      event: user      data: {message}            — только что сохранённое сообщение пользователя
      event: step      data: {message}            — каждый промежуточный шаг (чтение документации)
      event: final     data: {agent_message,chat} — финальный ответ агента
      event: error     data: {error}              — фатальная ошибка
    Фронт сразу отрисовывает шаги, не дожидаясь финального ответа."""
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    data = request.get_json(silent=True) or {}
    content, image_data, verr = _support_validate_payload(data)
    if verr:
        return verr

    chat = repo.get_open_support_chat(uid)
    if not chat:
        subject = content[:80] if content else 'Запрос с изображением'
        chat = repo.create_support_chat(uid, subject)
    if chat['status'] == 'closed':
        return error('Диалог завершён. Начните новый.', 400)

    user_msg = repo.add_support_message(chat['id'], 'user', content or '[изображение]', image_data)

    # Капчуем username ДО запуска фонового потока: внутри _worker() нет
    # request-контекста Flask, и любое обращение к session.* упадёт с
    # 'Working outside of request context' (этот баг ловили в логах
    # как [Support][stream] worker error).
    _username_for_worker = session.get('username') or ''

    import json as _json
    import queue as _queue
    import threading as _threading

    q = _queue.Queue()

    def _emit(event, payload):
        q.put(f'event: {event}\ndata: {_json.dumps(payload, ensure_ascii=False)}\n\n')

    def _worker():
        try:
            steps, answer = _support_run_ai(
                uid, chat, content, image_data,
                on_step=lambda step_msg: _emit('step', step_msg),
                username=_username_for_worker,
            )
            agent_msg = repo.add_support_message(chat['id'], 'agent', answer or '', None)
            _emit('final', {'agent_message': agent_msg, 'chat': chat})
        except Exception as exc:
            logger.error('[Support][stream] worker error: %s', exc)
            _emit('error', {'error': str(exc)})
        finally:
            q.put(None)  # сигнал «конец»

    _threading.Thread(target=_worker, daemon=True).start()

    @stream_with_context
    def _gen():
        # Сразу шлём user-сообщение и keepalive-комментарий, чтобы прокси
        # (Cloudflare Tunnel / werkzeug) точно открыли стрим клиенту.
        yield ': open\n\n'
        yield f'event: user\ndata: {_json.dumps(user_msg, ensure_ascii=False)}\n\n'
        while True:
            try:
                chunk = q.get(timeout=15)
            except _queue.Empty:
                yield ': keepalive\n\n'
                continue
            if chunk is None:
                break
            yield chunk

    headers = {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    }
    return Response(_gen(), headers=headers)


@bp.post('/api/support/chat')
def support_send_message():
    """Совместимый JSON-эндпоинт (без стрима). Используется fallback'ом фронта
    и сторонними клиентами; новый фронт ходит в /api/support/chat/stream."""
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    data = request.get_json(silent=True) or {}
    content, image_data, verr = _support_validate_payload(data)
    if verr:
        return verr

    chat = repo.get_open_support_chat(uid)
    if not chat:
        subject = content[:80] if content else 'Запрос с изображением'
        chat = repo.create_support_chat(uid, subject)
    if chat['status'] == 'closed':
        return error('Диалог завершён. Начните новый.', 400)

    user_msg = repo.add_support_message(chat['id'], 'user', content or '[изображение]', image_data)
    steps, answer = _support_run_ai(uid, chat, content, image_data)
    agent_msg = repo.add_support_message(chat['id'], 'agent', answer or '', None)

    return jsonify({
        'user_message': user_msg,
        'steps': steps,
        'agent_message': agent_msg,
        'chat': chat,
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

    # Логин юзера в каждой реплике — чтобы AI-анализ (а потом и админ в
    # уведомлении) видел, кто именно писал. Сэм без этого не различает диалоги.
    _user = repo.get_user_by_id(uid)
    _uname = (_user or {}).get('username') or 'неизвестен'
    _user_label = f'Пользователь (@{_uname})'
    dialog_text = '\n'.join([
        f"{_user_label if m['role'] == 'user' else 'Агент'}: {m['content']}" + (' [прикреплено изображение]' if m.get('image_data') else '')
        for m in messages
    ])

    close_messages = [
        {'role': 'user', 'content': f"{SUPPORT_CLOSE_PROMPT}\n\nДИАЛОГ:\n{dialog_text}"}
    ]

    reported = False
    summary = None       # короткая фраза «о чём был диалог» — пойдёт в review_text
    report_text = None   # подробности проблемы — пойдут в ai_advice (раскрываемая часть)
    key = None

    try:
        support_key_id = repo.get_admin_setting('support_key_id', '')
        if not support_key_id:
            support_key_id = repo.get_admin_setting('agent_key_id', '')
        if support_key_id:
            from freeapi.database import db as _db, row as _row
            with _db() as conn:
                key = _row(conn.execute('SELECT * FROM api_keys WHERE id=? AND is_active=1', (support_key_id,)).fetchone())

        if key:
            from freeapi.tg import run_chat
            from freeapi.models import DEFAULT_MODEL_ID
            import json as _json
            _support_model_close = repo.get_admin_setting('support_model', '') or key.get('default_model') or DEFAULT_MODEL_ID
            # БЕЗ /reset: в этот момент с Сэмом могут разговаривать другие
            # пользователи, и сброс затрёт их контекст. В SUPPORT_CLOSE_PROMPT
            # уже сказано «проанализируй ТОЛЬКО приведённый ниже диалог», а сам
            # диалог содержит логины — Сэм не путает с активными чатами.
            raw = run_chat(key, _support_model_close, close_messages)
            start = raw.find('{')
            end = raw.rfind('}')
            if start != -1 and end != -1:
                decision = _json.loads(raw[start:end+1])
                # Уведомление создаётся ТОЛЬКО если ИИ явно сказал needs_report=true.
                # Никаких fallback по словам — раньше фраза самого агента
                # «возникла временная ошибка» триггерила отправку всего диалога.
                if decision.get('needs_report'):
                    summary = (decision.get('summary') or '').strip()
                    report_text = (decision.get('report_text') or '').strip()
                    if report_text:
                        reported = True
    except Exception as exc:
        # KEY_BUSY_301 / CTX_LIMIT / таймаут / неверный JSON — НЕ создаём отчёт.
        # Лучше пропустить уведомление, чем спамить админа дампом переписки.
        logger.warning('[Support] Анализ диалога не удался (отчёт не создаём): %s', exc)

    repo.close_support_chat(chat['id'], report_text)

    # /reset после закрытия НЕ делаем: Сэм может прямо сейчас отвечать другим
    # пользователям, сброс затёр бы их контексты. Новый диалог любого юзера
    # сам пришлёт полный системный промпт на is_first=True, а от переполнения
    # памяти страхует обработка CTX_LIMIT в ветке отправки сообщения.

    if reported and report_text:
        user = repo.get_user_by_id(uid)
        username = user['username'] if user else 'неизвестен'
        # review_text — краткое summary («одна фраза о чём был диалог») —
        # это то, что админ видит в свёрнутом превью карточки уведомления.
        # ai_advice — полный report_text от ИИ (детали, что нужно сделать),
        # раскрывается по клику. Сам диалог при этом НЕ дублируется в
        # уведомлении: админ откроет его модалкой через support_chat_id.
        short = summary or (report_text.splitlines()[0][:140] if report_text else 'Обращение в поддержку')
        repo.create_admin_notification(
            review_id=None,
            review_text=f'Поддержка · @{username}: {short}',
            review_score=0,
            review_author=username,
            ai_response='',
            ai_advice=report_text,
            support_chat_id=chat['id'],
        )

    return jsonify({'ok': True, 'reported': reported})


# ─── Просмотр конкретного диалога поддержки админом ───
@bp.route('/api/admin/support/chat/<chat_id>', methods=['GET'])
def admin_support_chat_detail(chat_id):
    """Возвращает диалог поддержки целиком (chat + messages) для модалки
    «Открыть диалог» в карточке уведомления админа. Требует прав admin."""
    uid = session.get('uid')
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    user = repo.get_user_by_id(uid)
    if not user or not user.get('is_admin'):
        return jsonify({'error': 'forbidden'}), 403
    from freeapi.database import db as _db, row as _row, rows as _rows
    with _db() as conn:
        chat = _row(conn.execute('SELECT * FROM support_chats WHERE id=?', (chat_id,)).fetchone())
        if not chat:
            return jsonify({'error': 'not_found'}), 404
        msgs = _rows(conn.execute(
            'SELECT id, role, content, image_data, created_at FROM support_messages '
            'WHERE chat_id=? ORDER BY created_at ASC', (chat_id,)
        ).fetchall())
        owner = _row(conn.execute('SELECT username FROM users WHERE id=?', (chat['user_id'],)).fetchone())
    return jsonify({
        'chat': {
            'id': chat['id'],
            'status': chat['status'],
            'created_at': chat.get('created_at'),
            'closed_at': chat.get('closed_at'),
            'username': owner['username'] if owner else 'неизвестен',
        },
        'messages': msgs,
    })
