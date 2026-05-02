"""
Telegram-уведомитель о ссылке Cloudflare.
Хранит ID последних сообщений в .tg_state.json (рядом с api.py).
Не роняет основной процесс при любых ошибках.
"""
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger('freeapi')

_STATE_PATH = Path(__file__).resolve().parent.parent / '.tg_state.json'

_MSG_MARKER = 'Ссылка на FavoriteAPI'

_MSG_TEMPLATE = (
    '<blockquote expandable>'
    '<a href="{url}">{marker}</a>\n\n'
    'Лучший сайт с бесплатным доступом к ИИ 🔎\n'
    '<i>FavoriteAPI — бесплатный доступ к Google Gemini через Telegram-аккаунты. '
    'Без платных подписок и скрытых ограничений.</i>\n\n'
    '🔗 <a href="{url}">Открыть FavoriteAPI</a>'
    '</blockquote>'
)


def _build_text(url: str) -> str:
    return _MSG_TEMPLATE.format(url=url, marker=_MSG_MARKER)


def _load_state() -> dict:
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text('utf-8'))
    except Exception:
        pass
    return {}


def _save_state(state: dict):
    try:
        _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), 'utf-8')
    except Exception as exc:
        logger.warning('[TgNotify] Не удалось сохранить state: %s', exc)


# T11.2: session-blacklist для chat_id, для которых Telegram уже сказал
# "chat not found"/blocked/deactivated. Чтобы не спамить ошибками каждый
# раз, когда меняется URL Cloudflare-тоннеля.
_RUNTIME_DEAD_CHATS: set = set()
_DEAD_CHAT_MARKERS = (
    'chat not found',
    'bot was blocked',
    'user is deactivated',
    'forbidden: bot was blocked by the user',
    "forbidden: user is deactivated",
    'chat_id is empty',
    'peer_id_invalid',
)


def _is_dead_chat_error(description: str) -> bool:
    if not description:
        return False
    low = description.lower()
    return any(m in low for m in _DEAD_CHAT_MARKERS)


def _is_ok(result) -> bool:
    return bool(result and isinstance(result, dict) and result.get('ok'))


def _tg_api(token: str, method: str, data: dict) -> Optional[dict]:
    """HTTP-вызов Bot API.

    Возвращает:
      - dict {'ok': True, 'result': ...}              — успех
      - dict {'ok': False, 'error_code': int,
               'description': str}                    — Telegram сказал «нет»
      - None                                          — сетевой/прочий сбой
    """
    url = f'https://api.telegram.org/bot{token}/{method}'
    payload = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = {}
        try:
            body = json.loads(exc.read().decode('utf-8'))
        except Exception:
            pass
        description = body.get('description', str(exc))
        logger.warning('[TgNotify] HTTP %s %s: %s', exc.code, method, description)
        return {
            'ok': False,
            'error_code': exc.code,
            'description': description,
        }
    except Exception as exc:
        logger.warning('[TgNotify] Ошибка запроса %s: %s', method, exc)
        return None


def _normalize_chat_id(raw: str):
    """Привести chat_id к виду, понятному Telegram Bot API.

    ВАЖНО: однозначно по строке отличить ЛИЧНЫЙ chat_id (положительное
    число, диалог бот↔юзер) от RAW-id СУПЕРГРУППЫ/КАНАЛА (тоже
    положительное число, требующее префикса -100) — НЕВОЗМОЖНО.
    Поэтому здесь делаем «лучшее предположение», а реальный выбор
    формы происходит в `_resolve_chat_id` через getChat (с кешем).

    Поведение:
      - "@username"                       → как есть (паблик-канал/бот);
      - "-100…", "-…"                     → int (уже в нужной форме);
      - "supergroup:<id>" / "channel:<id>"
                                          → принудительно префикс -100;
      - "user:<id>" / "private:<id>"      → принудительно личный (без -100);
      - просто положительное число        → возвращаем int как есть;
        (если это окажется RAW-id канала, _resolve_chat_id попробует
         форму -100<id> и закеширует рабочую).
    """
    raw = str(raw).strip()
    if not raw:
        return raw
    if raw.startswith('@'):
        return raw
    low = raw.lower()
    for prefix in ('supergroup:', 'channel:'):
        if low.startswith(prefix):
            try:
                num = int(raw.split(':', 1)[1])
                if num > 0:
                    num = int(f'-100{num}')
                return num
            except (ValueError, IndexError):
                return raw
    for prefix in ('user:', 'private:'):
        if low.startswith(prefix):
            try:
                return int(raw.split(':', 1)[1])
            except (ValueError, IndexError):
                return raw
    try:
        return int(raw)
    except ValueError:
        return raw


# T11.4: кеш резолва raw_input → реальный chat_id, понятный TG.
# Заполняется в _resolve_chat_id (через getChat с двумя формами для
# положительных чисел: <id> и -100<id>).
_RESOLVED_CHAT_CACHE: dict = {}


def _resolve_chat_id(token: str, raw_id):
    """Вернуть рабочий chat_id для Bot API, кешируя результат.

    Логика для положительного целого:
      1) пробуем форму как есть (личный диалог);
      2) если getChat вернул "chat not found" — пробуем -100<id>
         (RAW-id супергруппы/канала);
      3) рабочая форма кешируется на сессию.

    Для @username, отрицательных int, явных префиксов supergroup:/channel:/
    user:/private: — берём _normalize_chat_id и доверяем.
    """
    key = str(raw_id).strip()
    if not key:
        return None
    if key in _RESOLVED_CHAT_CACHE:
        return _RESOLVED_CHAT_CACHE[key]

    base = _normalize_chat_id(key)

    needs_probe = (
        token
        and isinstance(base, int)
        and base > 0
        and not key.lower().startswith(('user:', 'private:'))
    )
    if not needs_probe:
        _RESOLVED_CHAT_CACHE[key] = base
        return base

    ok, _descr = _probe_chat(token, base)
    if ok:
        _RESOLVED_CHAT_CACHE[key] = base
        logger.info('[TgNotify] chat resolve: raw=%s → %s (личный/как есть)', key, base)
        return base

    alt = int(f'-100{base}')
    ok2, descr2 = _probe_chat(token, alt)
    if ok2:
        _RESOLVED_CHAT_CACHE[key] = alt
        logger.info('[TgNotify] chat resolve: raw=%s → %s (супергруппа/канал, +префикс -100)',
                    key, alt)
        return alt

    # Обе формы недоступны — кешируем "как есть" + помечаем dead, чтобы
    # дальше не спамить запросами при каждом sendMessage.
    _RESOLVED_CHAT_CACHE[key] = base
    _mark_dead_chat(base, f'getChat провалился в обеих формах ({descr2})')
    return base


def _mark_dead_chat(chat_id, description: str):
    """Добавить chat_id в session-blacklist + понятный warning один раз."""
    key = str(chat_id)
    if key in _RUNTIME_DEAD_CHATS:
        return
    _RUNTIME_DEAD_CHATS.add(key)
    logger.warning(
        '[TgNotify] chat=%s исключён из рассылки до перезапуска: %s. '
        'Если это личный чат — пользователь должен открыть бота '
        'в Telegram и нажать Start.',
        chat_id, description,
    )


def _send_new(token: str, chat_id, text: str) -> Optional[int]:
    if str(chat_id) in _RUNTIME_DEAD_CHATS:
        return None
    result = _tg_api(token, 'sendMessage', {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })
    if _is_ok(result):
        msg_id = result['result']['message_id']
        logger.info('[TgNotify] Отправлено новое сообщение в %s (id=%s)', chat_id, msg_id)
        return msg_id
    if isinstance(result, dict) and _is_dead_chat_error(result.get('description', '')):
        _mark_dead_chat(chat_id, result.get('description', ''))
    return None


def _edit_message(token: str, chat_id, message_id: int, text: str) -> bool:
    if str(chat_id) in _RUNTIME_DEAD_CHATS:
        return False
    result = _tg_api(token, 'editMessageText', {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })
    if _is_ok(result):
        logger.info('[TgNotify] Сообщение отредактировано в %s (id=%s)', chat_id, message_id)
        return True
    if isinstance(result, dict) and _is_dead_chat_error(result.get('description', '')):
        _mark_dead_chat(chat_id, result.get('description', ''))
    return False


def notify_new_url(token: str, chat_ids: List[str], new_url: str):
    """
    Для каждого чата: редактирует предыдущее сообщение или отправляет новое.
    Не выбрасывает исключений.
    """
    if not token or not chat_ids:
        return

    state = _load_state()
    text = _build_text(new_url)
    changed = False

    for raw_id in chat_ids:
        # T11.4: для положительных чисел резолвер сам подберёт нужную
        # форму (личный <id> или RAW-канал -100<id>).
        chat_id = _resolve_chat_id(token, raw_id)
        if chat_id in (None, ''):
            continue
        state_key = str(chat_id)
        try:
            existing_id = state.get(state_key)
            if existing_id:
                ok = _edit_message(token, chat_id, existing_id, text)
                if ok:
                    continue
                logger.info('[TgNotify] Редактирование не удалось для %s, отправляю новое', chat_id)
            new_id = _send_new(token, chat_id, text)
            if new_id:
                state[state_key] = new_id
                changed = True
        except Exception as exc:
            logger.error('[TgNotify] Необработанная ошибка для чата %s: %s', chat_id, exc)

    if changed:
        _save_state(state)


def validate_token(token: str) -> bool:
    result = _tg_api(token, 'getMe', {})
    if _is_ok(result):
        name = result['result'].get('username', '?')
        logger.info('[TgNotify] Токен бота валиден: @%s', name)
        return True
    logger.error('[TgNotify] Токен бота невалиден')
    return False


def _probe_chat(token: str, chat_id) -> Tuple[bool, str]:
    """getChat для конкретного chat_id. (ok, описание_ошибки)."""
    result = _tg_api(token, 'getChat', {'chat_id': chat_id})
    if _is_ok(result):
        return True, ''
    if isinstance(result, dict):
        return False, str(result.get('description') or 'unknown')
    return False, 'network error'



def notify_cli_url(token: str, chat_ids: List[str], url: str) -> None:
    """Отправляет/редактирует машиночитаемое FAPI_URL:-сообщение для FavoriteCLI.

    После отправки пиним его в чате — FavoriteCLI читает pinned_message через getChat.
    """
    if not token or not chat_ids:
        return

    state = _load_state()
    text = f"FAPI_URL:{url}"
    changed = False

    for raw_id in chat_ids:
        chat_id = _resolve_chat_id(token, raw_id)
        if chat_id in (None, ''):
            continue
        state_key = f"cli_url_msg_{chat_id}"
        try:
            existing_id = state.get(state_key)
            msg_id = None
            if existing_id:
                ok = _tg_api(token, 'editMessageText', {
                    'chat_id': chat_id,
                    'message_id': existing_id,
                    'text': text,
                })
                if ok and ok.get('ok'):
                    msg_id = existing_id
            if msg_id is None:
                result = _tg_api(token, 'sendMessage', {
                    'chat_id': chat_id,
                    'text': text,
                    'disable_notification': True,
                })
                if result and result.get('ok'):
                    msg_id = result['result']['message_id']
                    state[state_key] = msg_id
                    changed = True
            if msg_id:
                _tg_api(token, 'pinChatMessage', {
                    'chat_id': chat_id,
                    'message_id': msg_id,
                    'disable_notification': True,
                })
        except Exception as exc:
            logger.error('[TgNotify/CLI] Ошибка для чата %s: %s', chat_id, exc)

    if changed:
        _save_state(state)


def load_notify_config() -> Tuple[str, List[str]]:
    """
    Читает TG_NOTIFY_TOKEN и TG_NOTIFY_CHATS из окружения.
    Если нет — спрашивает в консоли и сохраняет в .env.
    Возвращает (token, [chat_ids]).
    """
    token = os.environ.get('TG_NOTIFY_TOKEN', '').strip()
    chats_raw = os.environ.get('TG_NOTIFY_CHATS', '').strip()

    if not token:
        print('\n[TgNotify] Токен Telegram-бота не найден в .env.')
        try:
            token = input('  Введите токен бота (или Enter для пропуска): ').strip()
        except (EOFError, OSError):
            token = ''
        if token:
            _set_env_var('TG_NOTIFY_TOKEN', token)
            os.environ['TG_NOTIFY_TOKEN'] = token

    if token and not chats_raw:
        print('[TgNotify] Список чатов для уведомлений не задан (TG_NOTIFY_CHATS).')
        try:
            chats_raw = input('  Введите ID/юзернеймы чатов через запятую (или Enter для пропуска): ').strip()
        except (EOFError, OSError):
            chats_raw = ''
        if chats_raw:
            # T11.4: для каждого raw-id вызываем общий резолвер —
            # он сам пробует и личную, и канальную (-100<id>) форму
            # через getChat и кеширует рабочую. Юзер сразу видит,
            # какая именно форма уехала в TG.
            for raw_id in [c.strip() for c in chats_raw.split(',') if c.strip()]:
                resolved = _resolve_chat_id(token, raw_id)
                if resolved in (None, '') or str(resolved) in _RUNTIME_DEAD_CHATS:
                    print(
                        f'  [!] {raw_id}: бот НЕ может писать в этот чат. '
                        f'Проверьте, что бот добавлен в канал/группу '
                        f'и имеет право «Post Messages», а для личного '
                        f'диалога — что юзер открыл бота и нажал Start. '
                        f'Сохраняю значение в .env как есть.'
                    )
                else:
                    print(f'  [✓] {raw_id} → доступен (форма для API: {resolved})')
            _set_env_var('TG_NOTIFY_CHATS', chats_raw)
            os.environ['TG_NOTIFY_CHATS'] = chats_raw

    if not token:
        logger.info('[TgNotify] Уведомления отключены (токен не задан)')
        return '', []

    chat_ids = [c.strip() for c in chats_raw.split(',') if c.strip()]
    if not chat_ids:
        logger.info('[TgNotify] Уведомления отключены (нет чатов)')
        return token, []

    return token, chat_ids


def _set_env_var(key: str, value: str) -> bool:
    """Корректный upsert переменной в .env (рядом с api.py).

    - Если файла нет — создаёт.
    - Если ключ уже есть в любом виде (с пустым значением, в кавычках,
      с/без trailing-комментария) — заменяет ВСЮ строку на `KEY=value`.
    - Если ключа нет — добавляет в конец, отдельной строкой.
    - Сохраняет порядок и комментарии.
    - При успехе обновляет os.environ[key] = value.
    - Возвращает True/False.
    """
    env_path = Path(__file__).resolve().parent.parent / '.env'
    try:
        if env_path.exists():
            text = env_path.read_text('utf-8')
            # Сохраняем перевод строки в конце, если был.
            had_trailing_nl = text.endswith('\n')
            lines = text.split('\n')
            if had_trailing_nl and lines and lines[-1] == '':
                lines.pop()  # убираем пустой хвост, добавим обратно при записи
        else:
            lines = []
            had_trailing_nl = True

        new_line = f'{key}={value}'
        replaced = False
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            # Пропускаем пустые и комментарии.
            if not stripped or stripped.startswith('#'):
                continue
            if '=' not in stripped:
                continue
            cur_key = stripped.split('=', 1)[0].strip()
            if cur_key == key:
                lines[i] = new_line
                replaced = True
                break

        if not replaced:
            lines.append(new_line)

        out = '\n'.join(lines) + ('\n' if had_trailing_nl else '\n')
        env_path.write_text(out, encoding='utf-8')

        os.environ[key] = value
        logger.info(
            '[TgNotify] Сохранено в .env: %s (%s)',
            key, 'updated' if replaced else 'created',
        )
        return True
    except Exception as exc:
        logger.warning('[TgNotify] Не удалось сохранить .env (%s=...): %s', key, exc)
        return False


# Backward-compat alias: на случай, если старый код где-то ещё вызывает
# _append_env. Делегируем на корректный upsert.
def _append_env(key: str, value: str):
    _set_env_var(key, value)


# ─── M3: ПУШИ ПО @-УПОМИНАНИЯМ И DEEP-LINK ПРИВЯЗКА ─────────────────
# Используем тот же бот TG_NOTIFY_TOKEN, что и для уведомления о CF-ссылке.
# Привязка пользователя выполняется через /start <one_time_token>:
#   1. Фронт зовёт GET /api/community/tg_link → бэк отдаёт ссылку
#      t.me/<bot>?start=<token>.
#   2. Юзер кликает, в Telegram уже стоит первое сообщение «/start <token>».
#   3. scheduler периодически дёргает poll_link_updates(token, db_match_fn,
#      db_save_fn): через getUpdates ловит новые /start, через db_match_fn
#      ищет юзера по токену, через db_save_fn сохраняет chat_id.
# offset getUpdates хранится в .tg_state.json под ключом '_link_offset'
# (рядом с map chat_id→message_id для notify_new_url).

_BOT_INFO_CACHE = {}  # token → {'username': str}


def get_bot_username(token: str):
    """Получить @username бота для генерации t.me-ссылки. Кэшируется."""
    if not token:
        return None
    cached = _BOT_INFO_CACHE.get(token)
    if cached and cached.get('username'):
        return cached['username']
    result = _tg_api(token, 'getMe', {})
    if _is_ok(result):
        username = result['result'].get('username') or ''
        _BOT_INFO_CACHE[token] = {'username': username}
        return username or None
    return None


def send_html_to_user(token: str, chat_id, text: str) -> bool:
    """Отправить произвольный HTML-текст в личку привязанного юзера.

    Возвращает True при успехе, False при любой ошибке. Никогда не бросает.
    """
    if not token or not chat_id or not text:
        return False
    # T11.4: тот же резолвер, что в notify_new_url — поддержка
    # RAW-id канала (положительное число → авто -100<id>).
    cid = _resolve_chat_id(token, str(chat_id))
    if cid in (None, ''):
        return False
    if str(cid) in _RUNTIME_DEAD_CHATS:
        return False
    result = _tg_api(token, 'sendMessage', {
        'chat_id': cid,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })
    if _is_ok(result):
        logger.info('[TgNotify] mention/push delivered chat=%s', cid)
        return True
    if isinstance(result, dict) and _is_dead_chat_error(result.get('description', '')):
        _mark_dead_chat(cid, result.get('description', ''))
    else:
        logger.warning('[TgNotify] mention/push failed chat=%s', cid)
    return False


def send_mention_push(token: str, chat_id, author_name: str, snippet: str,
                      message_id: str) -> bool:
    """Готовый шаблон для пуша «вас упомянули в сообществе».

    snippet уже обрезанный preview сообщения (мы экранируем его HTML).
    """
    safe_author = _escape_html(author_name or '?')
    safe_snippet = _escape_html(snippet or '')
    if not safe_snippet:
        safe_snippet = '<i>(без текста)</i>'
    text = (
        f'🔔 <b>FavoriteAPI · Сообщество</b>\n\n'
        f'Вас упомянул(а) <b>@{safe_author}</b>:\n'
        f'<blockquote>{safe_snippet}</blockquote>\n'
        f'Откройте раздел «Чат / Посты» на сайте, чтобы ответить.\n\n'
        f'<i>Пуши приходят, потому что вы привязали Telegram в настройках.</i>'
    )
    return send_html_to_user(token, chat_id, text)


def _escape_html(s: str) -> str:
    if not s:
        return ''
    return (
        s.replace('&', '&amp;')
         .replace('<', '&lt;')
         .replace('>', '&gt;')
    )


# ─── DEEP-LINK ПРИВЯЗКА ─────────────────────────────────────────────


_LINK_OFFSET_KEY = '_link_offset'


def _load_link_offset() -> int:
    state = _load_state()
    try:
        return int(state.get(_LINK_OFFSET_KEY, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _save_link_offset(offset: int):
    state = _load_state()
    state[_LINK_OFFSET_KEY] = int(offset)
    _save_state(state)


def poll_link_updates(token: str, on_link) -> int:
    """Долгий поллинг getUpdates для обработки команды /start <link_token>.

    Параметры:
      token   — TG_NOTIFY_TOKEN (тот же бот, что шлёт уведомления).
      on_link — callable(link_token: str, chat_id: int, tg_username: str|None)
                → True, если привязка успешна; False — если токен не найден,
                и пользователю надо отправить ошибку.

    Возвращает кол-во обработанных /start-команд.

    Никогда не бросает. Сетевой timeout — 5 сек (короткий long-poll), чтобы
    не блокировать общий планировщик.
    """
    if not token or not callable(on_link):
        return 0

    offset = _load_link_offset()
    payload = {
        'offset': offset,
        'timeout': 5,
        'allowed_updates': ['message'],
    }
    result = _tg_api(token, 'getUpdates', payload)
    if not _is_ok(result):
        return 0

    updates = result.get('result') or []
    if not updates:
        return 0

    processed = 0
    max_id = offset
    for upd in updates:
        try:
            upd_id = int(upd.get('update_id') or 0)
            if upd_id >= max_id:
                max_id = upd_id + 1
            msg = upd.get('message') or {}
            text = (msg.get('text') or '').strip()
            chat = msg.get('chat') or {}
            chat_id = chat.get('id')
            if not chat_id or not text:
                continue
            # Принимаем только формат "/start <token>" (deep-link).
            if not text.startswith('/start'):
                continue
            parts = text.split(maxsplit=1)
            link_token = parts[1].strip() if len(parts) > 1 else ''
            tg_username = (msg.get('from') or {}).get('username')
            if not link_token:
                # /start без аргумента — приветственное сообщение.
                send_html_to_user(token, chat_id, _start_help_text())
                continue
            ok = on_link(link_token, chat_id, tg_username)
            if ok:
                send_html_to_user(token, chat_id, _link_success_text(tg_username))
                processed += 1
                logger.info('[TgNotify] /start: linked token=%s chat=%s user=%s',
                            link_token[:8], chat_id, tg_username)
            else:
                send_html_to_user(token, chat_id, _link_failure_text())
                logger.info('[TgNotify] /start: token not found token=%s chat=%s',
                            link_token[:8], chat_id)
        except Exception as exc:
            logger.warning('[TgNotify] poll_link_updates: ошибка обработки upd: %s', exc)
            continue

    if max_id != offset:
        _save_link_offset(max_id)

    return processed


def _start_help_text() -> str:
    return (
        '👋 <b>FavoriteAPI · уведомления</b>\n\n'
        'Чтобы получать пуши о @упоминаниях в сообществе, перейдите по '
        'ссылке-привязке с сайта (раздел «Чат / Посты» → «Уведомления в Telegram»).\n\n'
        'Если вы уже привязаны — ничего делать не надо.'
    )


def _link_success_text(tg_username) -> str:
    name = f'@{tg_username}' if tg_username else 'аккаунт'
    return (
        f'✅ <b>{_escape_html(name)} привязан!</b>\n\n'
        'Теперь вы будете получать пуши, если кто-то упомянёт вас '
        '@логином в общем чате FavoriteAPI.\n\n'
        '<i>Отключить можно в любой момент в разделе «Чат / Посты».</i>'
    )


def _link_failure_text() -> str:
    return (
        '⚠️ <b>Ссылка устарела или недействительна.</b>\n\n'
        'Откройте сайт FavoriteAPI → «Чат / Посты» → «Уведомления в Telegram» '
        'и нажмите «Сгенерировать ссылку заново».'
    )
