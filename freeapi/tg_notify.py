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


def _tg_api(token: str, method: str, data: dict) -> Optional[dict]:
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
        logger.warning('[TgNotify] HTTP %s %s: %s', exc.code, method, body.get('description', exc))
        return None
    except Exception as exc:
        logger.warning('[TgNotify] Ошибка запроса %s: %s', method, exc)
        return None


def _normalize_chat_id(raw: str):
    raw = str(raw).strip()
    if not raw:
        return raw
    if raw.startswith('@'):
        return raw
    try:
        num = int(raw)
        if num > 0 and len(raw) >= 6:
            num = int(f'-100{num}')
            logger.info('[TgNotify] Нормализация chat_id: добавлен префикс -100 -> %s', num)
        return num
    except ValueError:
        return raw


def _send_new(token: str, chat_id, text: str) -> Optional[int]:
    result = _tg_api(token, 'sendMessage', {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })
    if result and result.get('ok'):
        msg_id = result['result']['message_id']
        logger.info('[TgNotify] Отправлено новое сообщение в %s (id=%s)', chat_id, msg_id)
        return msg_id
    return None


def _edit_message(token: str, chat_id, message_id: int, text: str) -> bool:
    result = _tg_api(token, 'editMessageText', {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })
    if result and result.get('ok'):
        logger.info('[TgNotify] Сообщение отредактировано в %s (id=%s)', chat_id, message_id)
        return True
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
        chat_id = _normalize_chat_id(raw_id)
        if not chat_id:
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
    if result and result.get('ok'):
        name = result['result'].get('username', '?')
        logger.info('[TgNotify] Токен бота валиден: @%s', name)
        return True
    logger.error('[TgNotify] Токен бота невалиден')
    return False


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
            _append_env('TG_NOTIFY_TOKEN', token)
            os.environ['TG_NOTIFY_TOKEN'] = token

    if token and not chats_raw:
        print('[TgNotify] Список чатов для уведомлений не задан (TG_NOTIFY_CHATS).')
        try:
            chats_raw = input('  Введите ID/юзернеймы чатов через запятую (или Enter для пропуска): ').strip()
        except (EOFError, OSError):
            chats_raw = ''
        if chats_raw:
            _append_env('TG_NOTIFY_CHATS', chats_raw)
            os.environ['TG_NOTIFY_CHATS'] = chats_raw

    if not token:
        logger.info('[TgNotify] Уведомления отключены (токен не задан)')
        return '', []

    chat_ids = [c.strip() for c in chats_raw.split(',') if c.strip()]
    if not chat_ids:
        logger.info('[TgNotify] Уведомления отключены (нет чатов)')
        return token, []

    return token, chat_ids


def _append_env(key: str, value: str):
    env_path = Path(__file__).resolve().parent.parent / '.env'
    try:
        existing = env_path.read_text('utf-8') if env_path.exists() else ''
        if key not in existing:
            with open(env_path, 'a', encoding='utf-8') as f:
                f.write(f'\n{key}={value}\n')
            logger.info('[TgNotify] Сохранено в .env: %s', key)
    except Exception as exc:
        logger.warning('[TgNotify] Не удалось сохранить .env: %s', exc)
