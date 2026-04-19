import asyncio
import logging
import os
import re
import tempfile
import threading
import time
import urllib.request

logger = logging.getLogger('freeapi')

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError, UserAlreadyParticipantError, UserBlockedError, YouBlockedUserError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest, UnblockRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest, StartBotRequest
from telethon.tl.types import MessageEntityCode, MessageEntityTextUrl

from freeapi import repositories as repo
from freeapi.config import BOT_QUIET_SECONDS, REQUEST_TIMEOUT_SECONDS, SAM_BOT_USERNAME
from freeapi.memory import detect_limit_error, contains_cyrillic, CONTEXT_WARN_KB
from freeapi.models import DEFAULT_MODEL_ID, find_model
from freeapi.progress import update_progress
from freeapi.security import decrypt_text, encrypt_text, generate_api_key

TRANSLATE_TIMEOUT = 90


class RateLimiter:
    def __init__(self):
        self.last = 0.0
        self.lock = asyncio.Lock()

    async def wait(self, seconds):
        async with self.lock:
            delay = max(0.0, seconds - (time.monotonic() - self.last))
            if delay:
                await asyncio.sleep(delay)
            self.last = time.monotonic()

    async def message(self):
        await self.wait(1.5)

    async def button(self):
        await self.wait(1.0)

    async def sponsor(self):
        await self.wait(3.0)

    async def flood(self, seconds):
        await asyncio.sleep(float(seconds) + 2.0)


async def resolve_bot(client, username):
    try:
        return await client.get_entity(username)
    except (ValueError, TypeError, KeyError):
        pass
    result = await client(ResolveUsernameRequest(username))
    if result.users:
        return result.users[0]
    raise ValueError(f'Бот @{username} не найден через resolve')


class TgSession:
    def __init__(self, account):
        self.account = account
        self.api_id = int(account['api_id'])
        self.api_hash = decrypt_text(account['api_hash'])
        session_value = decrypt_text(account.get('session_string')) if account.get('session_string') else ''
        self.client = TelegramClient(StringSession(session_value), self.api_id, self.api_hash)
        self.rate = RateLimiter()

    async def __aenter__(self):
        await self.client.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        repo.update_tg_account(self.account['id'], session_string=encrypt_text(self.client.session.save()))
        await self.client.disconnect()

    async def ensure_authorized(self):
        if not await self.client.is_user_authorized():
            raise RuntimeError('Telegram-сессия не авторизована')

    async def bot(self):
        return await resolve_bot(self.client, SAM_BOT_USERNAME)

    async def unblock(self, entity):
        try:
            await self.client(UnblockRequest(entity))
        except Exception:
            pass

    async def send_message(self, entity, text):
        _unblocked = False
        while True:
            try:
                await self.rate.message()
                return await self.client.send_message(entity, text)
            except (UserBlockedError, YouBlockedUserError):
                if _unblocked:
                    raise RuntimeError('Бот заблокирован в вашем Telegram. Разблокируйте @' + SAM_BOT_USERNAME + ' вручную и повторите настройку.')
                await self.unblock(entity)
                _unblocked = True
            except FloodWaitError as error:
                await self.rate.flood(error.seconds)

    async def send_file(self, entity, path, caption=None):
        while True:
            try:
                await self.rate.message()
                return await self.client.send_file(entity, path, caption=caption)
            except FloodWaitError as error:
                await self.rate.flood(error.seconds)

    async def click(self, message, data=None, text=None):
        while True:
            try:
                await self.rate.button()
                if data is not None:
                    return await message.click(data=data)
                if text is not None:
                    return await message.click(text=text)
                return await message.click()
            except FloodWaitError as error:
                await self.rate.flood(error.seconds)


class SponsorHandler:
    def __init__(self, tg):
        self.tg = tg

    def detected(self, message):
        text = (getattr(message, 'raw_text', '') or '').lower()
        return bool(getattr(message, 'buttons', None)) and any(x in text for x in ['спонсор', 'подпис', 'mandatory', 'канал'])

    async def handle(self, message):
        if not message or not self.detected(message):
            return False
        for row in message.buttons or []:
            for button in row:
                url = getattr(button, 'url', None)
                data = getattr(button, 'data', None)
                title = (getattr(button, 'text', '') or '').lower()
                if data == b'check_mandatory_channels_subscription' or 'провер' in title:
                    continue
                if url:
                    await self.join_url(url)
                    await self.tg.rate.sponsor()
        for row in message.buttons or []:
            for button in row:
                data = getattr(button, 'data', None)
                title = getattr(button, 'text', '') or ''
                if data == b'check_mandatory_channels_subscription' or 'провер' in title.lower():
                    await self.tg.click(message, data=data if data else None, text=title if not data else None)
                    return True
        return True

    async def join_url(self, url):
        try:
            private = re.search(r't\.me/\+([A-Za-z0-9_-]+)', url)
            if private:
                await self.tg.client(ImportChatInviteRequest(private.group(1)))
                return
            public = re.search(r't\.me/([A-Za-z0-9_]+)', url)
            if not public:
                return
            username = public.group(1)
            entity = await resolve_bot(self.tg.client, username)
            if getattr(entity, 'bot', False):
                await self.tg.client(StartBotRequest(entity, entity, start_param='start'))
            else:
                await self.tg.client(JoinChannelRequest(entity))
        except Exception:
            pass


class PromoActivator:
    def __init__(self, tg):
        self.tg = tg

    def channel_url(self, message):
        text = getattr(message, 'raw_text', '') or ''
        for entity in getattr(message, 'entities', None) or []:
            if isinstance(entity, MessageEntityTextUrl):
                return entity.url
        match = re.search(r'https?://t\.me/[A-Za-z0-9_+/-]+', text)
        return match.group(0) if match else None

    async def parse_codes(self, url):
        if not url:
            return []
        try:
            private = re.search(r't\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)', url)
            if private:
                invite_hash = private.group(1)
                try:
                    result = await self.tg.client(ImportChatInviteRequest(invite_hash))
                    entity = result.chats[0] if result.chats else None
                except UserAlreadyParticipantError:
                    try:
                        check = await self.tg.client(CheckChatInviteRequest(invite_hash))
                        entity = getattr(check, 'chat', None)
                    except Exception:
                        entity = None
                except Exception:
                    entity = None
                if not entity:
                    return []
            else:
                username = url.rstrip('/').split('/')[-1]
                try:
                    entity = await resolve_bot(self.tg.client, username)
                except Exception:
                    return []
            codes = []
            async for msg in self.tg.client.iter_messages(entity, limit=5):
                text = msg.raw_text or ''
                for item in getattr(msg, 'entities', None) or []:
                    if isinstance(item, MessageEntityCode):
                        codes.append(text[item.offset:item.offset + item.length].strip())
                codes.extend(re.findall(r'Промокод на .+? токенов:\s*([a-zA-Z0-9]{4,10})', text))
            return codes
        except Exception:
            return []

    async def activate(self, bot, message):
        codes = await self.parse_codes(self.channel_url(message))
        codes.append('PROMO32')
        for code in dict.fromkeys(codes):
            try:
                last = await last_message(self.tg, bot)
                try:
                    await self.tg.click(last, data=b'activate_promo_code')
                except Exception:
                    try:
                        await self.tg.click(last, text='Активировать')
                    except Exception:
                        pass
                await self.tg.send_message(bot, code)
                await asyncio.sleep(1.5)
            except Exception:
                pass


class ModelSwitcher:
    def __init__(self, tg, sponsors):
        self.tg = tg
        self.sponsors = sponsors

    async def switch(self, key, model_id):
        model = find_model(model_id)
        if not model:
            raise ValueError('Модель не существует')
        bot = await self.tg.bot()
        await self.tg.send_message(bot, '🧰 Дополнительно')
        msg = await last_message(self.tg, bot)
        await self.sponsors.handle(msg)
        for data in [b'open_gpt_settings_section', b'open_change_gpt_model_section', model['tgCallback'].encode()]:
            msg = await last_message(self.tg, bot)
            await self.tg.click(msg, data=data)
        await asyncio.sleep(5)
        await self.tg.send_message(bot, '🔄 Сбросить историю')
        repo.update_api_key(key['id'], current_model=model_id)


class ChatHandler:
    def __init__(self, tg, sponsors):
        self.tg = tg
        self.sponsors = sponsors
        self.switcher = ModelSwitcher(tg, sponsors)

    async def _wait_and_handle_sponsors(self, bot, sent_id, retry_coro, max_rounds=5):
        sent = None
        last_sent_id = sent_id
        for attempt in range(max_rounds):
            try:
                response = await wait_any(self.tg, bot, last_sent_id)
            except TimeoutError:
                break
            sponsor_handled = await self.sponsors.handle(response)
            if not sponsor_handled:
                return last_sent_id
            await asyncio.sleep(3)
            new_sent = await retry_coro()
            last_sent_id = new_sent.id
        return last_sent_id

    async def process(self, key, model, messages):
        await self.tg.ensure_authorized()
        bot = await self.tg.bot()
        if model != key.get('current_model'):
            await self.switcher.switch(key, model)
        text, images = extract_payload(messages)
        if images:
            logger.info('[INFO] Получено изображений: %d. Начинаю обработку...', len(images))
        for index, image_url in enumerate(images):
            logger.info('[INFO] Анализ фото %d/%d...', index + 1, len(images))
            path = download_temp(image_url)
            try:
                caption = 'Проанализируй это фото сам для себя.'
                if index == len(images) - 1 and not text.strip():
                    caption = text or caption

                async def send_img():
                    return await self.tg.send_file(bot, path, caption=caption)

                sent = await send_img()
                final_id = await self._wait_and_handle_sponsors(bot, sent.id, send_img)
                try:
                    await wait_any(self.tg, bot, final_id)
                except TimeoutError:
                    pass
                await asyncio.sleep(1.5)
            finally:
                safe_unlink(path)
        if images:
            logger.info('[INFO] Все изображения отправлены. Ожидаю ответ от ИИ...')

        if text.strip():
            async def send_txt():
                return await send_text(self.tg, bot, text)

            sent = await send_txt()
            final_id = await self._wait_and_handle_sponsors(bot, sent.id, send_txt)
            return await collect_answer(self.tg, bot, final_id, bool(key.get('skip_hints', 1)))

        return await collect_answer(self.tg, bot, 0, bool(key.get('skip_hints', 1)))


class SetupFlow:
    def __init__(self, setup_id, user_id, account_id, start_step=1):
        self.setup_id = setup_id
        self.user_id = user_id
        self.account_id = account_id
        self.start_step = max(1, min(int(start_step or 1), 6))

    async def run(self):
        try:
            account = repo.get_tg_account(self.account_id)
            async with TgSession(account) as tg:
                sponsors = SponsorHandler(tg)
                await tg.ensure_authorized()
                bot = await tg.bot()
                if self.start_step <= 1:
                    await self.step(1, 'Проверяем аккаунт...')
                    await check_spambot(tg)
                if self.start_step <= 2:
                    await self.step(2, 'Запускаем ИИ...')
                    await tg.send_message(bot, '/start')
                    await self.wait_with_progress(2, 'Запуск ИИ-бота', 20, interval=5)
                if self.start_step <= 3:
                    await self.step(3, 'Обучаем ИИ...')
                    await training_with_progress(tg, sponsors, bot, self.setup_id)
                if self.start_step <= 4:
                    await self.step(4, 'Настраиваем параметры...')
                    await configure_gpt(tg, bot)
                if self.start_step <= 5:
                    await self.step(5, 'Настраиваем бесплатный доступ...')
                    promo_message = await open_promos(tg, bot)
                    await PromoActivator(tg).activate(bot, promo_message)
                if self.start_step <= 6:
                    await self.step(6, 'Финальная настройка...')
                    await tg.send_message(bot, '🔄 Сбросить историю')
                    repo.update_tg_account(self.account_id, is_valid=1, setup_done=1, session_string=encrypt_text(tg.client.session.save()))
                    key = repo.get_account_key(self.user_id, self.account_id)
                    if not key:
                        key = repo.create_api_key(self.user_id, self.account_id, generate_api_key(), 'Мой ключ', DEFAULT_MODEL_ID)
                    repo.update_setup_session(self.setup_id, status='done', current_step=6, step_label='Готово!', error_msg=None)
                    update_progress(self.setup_id, step=6, stepLabel='Готово!', done=True, error=None, canRetry=False, apiKey=key['key_value'])
        except (UserBlockedError, YouBlockedUserError):
            msg = 'Бот заблокирован в вашем Telegram. Зайдите в Telegram, разблокируйте @' + SAM_BOT_USERNAME + ' и нажмите "Повторить".'
            repo.update_setup_session(self.setup_id, status='error', error_msg=msg)
            update_progress(self.setup_id, done=True, error=msg, canRetry=True)
        except Exception as error:
            repo.update_setup_session(self.setup_id, status='error', error_msg=str(error))
            update_progress(self.setup_id, done=True, error='SETUP_FAIL_604: ' + str(error), canRetry=True)

    async def step(self, number, label):
        repo.update_setup_session(self.setup_id, current_step=number, step_label=label)
        update_progress(self.setup_id, step=number, stepLabel=label, done=False, error=None)

    async def wait_with_progress(self, step, title, seconds, interval=10):
        remaining = seconds
        while remaining > 0:
            label = f'{title}: осталось {remaining} сек'
            repo.update_setup_session(self.setup_id, current_step=step, step_label=label)
            update_progress(self.setup_id, step=step, stepLabel=label, done=False, error=None)
            delay = min(interval, remaining)
            await asyncio.sleep(delay)
            remaining -= delay


async def send_code_request(api_id, api_hash, phone):
    client = TelegramClient(StringSession(''), int(api_id), api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        return {'phone_code_hash': sent.phone_code_hash, 'session_string': client.session.save()}
    finally:
        await client.disconnect()


async def sign_in_with_code(api_id, api_hash, phone, code, phone_code_hash, session_string, password=None):
    client = TelegramClient(StringSession(session_string or ''), int(api_id), api_hash)
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                return {'need_password': True, 'session_string': client.session.save()}
            await client.sign_in(password=password)
        return {'authorized': await client.is_user_authorized(), 'session_string': client.session.save()}
    finally:
        await client.disconnect()


async def check_spambot(tg):
    bot = await resolve_bot(tg.client, 'SpamBot')
    await tg.send_message(bot, '/start')
    await asyncio.sleep(3)
    msg = await last_message(tg, bot)
    text = (msg.raw_text or '').lower() if msg else ''
    is_free = 'свободен' in text or 'no limits' in text or 'not limited' in text or 'no restrictions' in text
    is_spam = not is_free and ('ограничен' in text or 'restricted' in text)
    if is_spam:
        raise RuntimeError('TG_SPAM_503')


async def training(tg, sponsors, bot):
    await training_with_progress(tg, sponsors, bot, None)


async def training_with_progress(tg, sponsors, bot, setup_id=None, total_seconds=180, interval=10):
    await tg.send_message(bot, '🧰 Дополнительно')
    await asyncio.sleep(2)
    msg = await last_message(tg, bot)
    await sponsors.handle(msg)
    try:
        await tg.click(msg, data=b'confirm_training_start')
    except Exception as error:
        raise RuntimeError('TRAINING_START_FAILED') from error
    remaining = total_seconds
    while remaining > 0:
        label = f'Обучение: осталось {remaining} сек'
        if setup_id is not None:
            repo.update_setup_session(setup_id, current_step=3, step_label=label)
            update_progress(setup_id, step=3, stepLabel=label, done=False, error=None)
        delay = min(interval, remaining)
        await asyncio.sleep(delay)
        remaining -= delay


async def configure_gpt(tg, bot):
    sequence = [
        b'open_gpt_settings_section', b'open_text_formatting_settings', b'select_text_formatting:false', b'open_gpt_settings_section',
        b'open_latex_response_format_settings', b'select_latex_response_format:none', b'open_gpt_settings_section',
        b'open_chat_reset_settings', b'select_chat_reset:false', b'open_gpt_settings_section',
        b'open_interaction_mode_settings', b'select_interaction_mode:True', b'open_gpt_settings_section',
        b'open_change_gpt_model_section', b'select_gpt_model:gemini-3-flash-preview-200k', b'open_gpt_settings_section', b'back_to_additional',
    ]
    for data in sequence:
        msg = await last_message(tg, bot)
        try:
            await tg.click(msg, data=data)
            if data.startswith(b'select_gpt_model'):
                await asyncio.sleep(5)
        except Exception as error:
            raise RuntimeError('GPT_CONFIG_FAILED') from error


async def open_promos(tg, bot):
    msg = await last_message(tg, bot)
    try:
        await tg.click(msg, data=b'open_profile')
    except Exception:
        try:
            await tg.click(msg, text='Профиль')
        except Exception as error:
            raise RuntimeError('PROMO_PROFILE_OPEN_FAILED') from error
    await asyncio.sleep(1)
    msg = await last_message(tg, bot)
    try:
        await tg.click(msg, data=b'open_activate_promo_code_section')
    except Exception:
        try:
            await tg.click(msg, text='Промокоды')
        except Exception as error:
            raise RuntimeError('PROMO_SECTION_OPEN_FAILED') from error
    await asyncio.sleep(1)
    return await last_message(tg, bot)


async def last_message(tg, entity):
    async for msg in tg.client.iter_messages(entity, limit=1):
        return msg
    return None


def extract_payload(messages):
    system_msgs = [m for m in messages if isinstance(m, dict) and m.get('role') == 'system']
    users = [m for m in messages if isinstance(m, dict) and m.get('role') == 'user']
    if not users:
        return '', []
    content = users[-1].get('content')
    text, images = '', []
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text_parts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'text':
                text_parts.append(part.get('text', ''))
            if part.get('type') == 'image_url':
                image = part.get('image_url') or {}
                if image.get('url'):
                    images.append(image['url'])
        text = '\n'.join(text_parts)
    if system_msgs and len(users) == 1:
        sys_text = system_msgs[0].get('content', '') if isinstance(system_msgs[0].get('content'), str) else ''
        if sys_text:
            text = f"{sys_text}\n\n---\n\nСообщение пользователя: {text}"
    return text, images


def download_temp(url):
    import base64 as _b64
    if url.startswith('data:'):
        header, encoded = url.split(',', 1)
        mime = header.split(';')[0].split(':')[1] if ':' in header else 'image/jpeg'
        ext_map = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif', 'image/webp': '.webp'}
        suffix = ext_map.get(mime, '.jpg')
        fd, path = tempfile.mkstemp(prefix='freeapi_', suffix=suffix)
        os.close(fd)
        with open(path, 'wb') as f:
            f.write(_b64.b64decode(encoded))
        return path
    suffix = os.path.splitext(url.split('?', 1)[0])[1] or '.jpg'
    fd, path = tempfile.mkstemp(prefix='freeapi_', suffix=suffix)
    os.close(fd)
    urllib.request.urlretrieve(url, path)
    return path


def safe_unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


async def send_text(tg, bot, text):
    if len(text) <= 4096:
        return await tg.send_message(bot, text)
    fd, path = tempfile.mkstemp(prefix='query_', suffix='.txt')
    os.close(fd)
    with open(path, 'w', encoding='utf-8') as file:
        file.write(text)
    try:
        return await tg.send_file(bot, path, caption='Запрос в файле query.txt')
    finally:
        safe_unlink(path)


async def wait_any(tg, bot, after_id):
    deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        msg = await last_message(tg, bot)
        if msg and msg.id > after_id:
            return msg
        await asyncio.sleep(1)
    raise TimeoutError('timeout waiting for Telegram bot')


def _smart_join(parts):
    if not parts:
        return ''
    result = parts[0]
    for part in parts[1:]:
        if not part:
            continue
        normalized_result = result.strip()
        normalized_part = part.strip()
        if normalized_part and normalized_result:
            if normalized_part.startswith(normalized_result):
                result = normalized_part
                continue
            if normalized_result.startswith(normalized_part):
                continue
        prev_stripped = result.rstrip()
        last_char = prev_stripped[-1] if prev_stripped else ''
        first_char = part.lstrip()[0] if part.lstrip() else ''
        if last_char in '.!?\n' or not first_char:
            result += '\n\n' + part
        else:
            result += part
    return result.strip()


async def collect_answer(tg, bot, after_id, skip_hints, timeout=None):
    deadline = time.monotonic() + (timeout or REQUEST_TIMEOUT_SECONDS)
    seen, parts, last_seen = set(), [], None
    while time.monotonic() < deadline:
        batch = []
        async for msg in tg.client.iter_messages(bot, limit=20):
            if msg.id > after_id and msg.id not in seen:
                batch.append(msg)
        for msg in reversed(batch):
            seen.add(msg.id)
            text = (msg.raw_text or '').strip()
            if not text:
                continue
            if skip_hints and text.startswith('💡'):
                continue
            if 'Сэм отправил вам промокод' in text or 'activate_promo_code' in text:
                continue
            parts.append(text)
            last_seen = time.monotonic()
        if parts and last_seen and time.monotonic() - last_seen >= BOT_QUIET_SECONDS:
            result = _smart_join(parts)
            if detect_limit_error(result):
                raise RuntimeError('CTX_LIMIT_180')
            return result
        await asyncio.sleep(0.5)
    raise TimeoutError('timeout waiting for Telegram bot')


_key_locks = {}
_global_lock = threading.RLock()


def key_lock(key_id):
    with _global_lock:
        _key_locks.setdefault(key_id, threading.Lock())
        return _key_locks[key_id]


def run_chat(key, model, messages, trace=None):
    lock = key_lock(key['id'])
    if not lock.acquire(blocking=False):
        raise RuntimeError('KEY_BUSY_301')
    repo.update_api_key(key['id'], is_busy=1)
    logger.info('[INFO] run_chat: ключ=%s, модель=%s', key.get('name', key['id']), model)
    try:
        account = repo.get_tg_account(key['tg_account_id'])
        if not account or not account.get('setup_done'):
            raise RuntimeError('KEY_NO_TG_303')
        if trace is not None:
            trace['main_account_id'] = account.get('id', '')
            trace['main_account_username'] = account.get('tg_username') or account.get('tg_first_name') or 'N/A'
        async def job():
            async with TgSession(account) as tg:
                sponsors = SponsorHandler(tg)
                return await ChatHandler(tg, sponsors).process(key, model, messages)
        result = asyncio.run(job())
        logger.info('[INFO] run_chat: ответ получен успешно')
        if trace is not None:
            trace['main_answer_raw'] = result
        return result
    finally:
        repo.update_api_key(key['id'], is_busy=0)
        lock.release()


def run_translate(key, text, direction='en', trace=None, trace_key=None):
    translator_account_id = key.get('translator_account_id') or key['tg_account_id']
    account = repo.get_tg_account(translator_account_id)
    if not account or not account.get('setup_done'):
        logger.warning('[DUAL] Аккаунт-переводчик не найден или не настроен')
        if trace is not None and trace_key:
            trace[trace_key] = text
            trace['translator_error'] = 'Аккаунт-переводчик не найден или не настроен'
        return text
    if trace is not None:
        trace['translator_account_id'] = account.get('id', '')
        trace['translator_account_username'] = account.get('tg_username') or account.get('tg_first_name') or 'N/A'
    if direction == 'en':
        prompt = (
            'Translate the following text to English. '
            'Reply ONLY with the translation, no explanations, no extra text:\n\n' + text
        )
    else:
        prompt = (
            'Переведи следующий текст на русский язык. '
            'Ответь ТОЛЬКО переводом, без пояснений и лишнего текста:\n\n' + text
        )
    lock = key_lock(translator_account_id)
    if not lock.acquire(blocking=True, timeout=60):
        logger.warning('[DUAL] Таймаут ожидания lock для аккаунта-переводчика')
        if trace is not None and trace_key:
            trace[trace_key] = text
            trace['translator_error'] = 'Таймаут ожидания lock переводчика'
        return text
    try:
        async def job():
            async with TgSession(account) as tg:
                sponsors = SponsorHandler(tg)
                await tg.ensure_authorized()
                bot = await tg.bot()
                sent = await send_text(tg, bot, prompt)
                final_id = sent.id
                try:
                    first = await wait_any(tg, bot, sent.id)
                    if sponsors.detected(first):
                        await sponsors.handle(first)
                        sent2 = await send_text(tg, bot, prompt)
                        final_id = sent2.id
                except TimeoutError:
                    pass
                return await collect_answer(tg, bot, final_id, True, timeout=TRANSLATE_TIMEOUT)
        result = asyncio.run(job())
        logger.info('[DUAL] Перевод (%s→%s): %d символов', 'ru' if direction == 'en' else 'en', direction, len(result))
        if trace is not None and trace_key:
            trace[trace_key] = result
        return result
    except RuntimeError as exc:
        if 'CTX_LIMIT_180' in str(exc):
            logger.warning('[DUAL] Переводчик упёрся в лимит — сбрасываем его контекст')
            try:
                fake_key = dict(key)
                fake_key['tg_account_id'] = translator_account_id
                run_control(fake_key, '/reset')
            except Exception:
                pass
        if trace is not None and trace_key:
            trace[trace_key] = text
            trace['translator_error'] = str(exc)
        return text
    except Exception as exc:
        logger.warning('[DUAL] Ошибка перевода: %s — возвращаю оригинал', exc)
        if trace is not None and trace_key:
            trace[trace_key] = text
            trace['translator_error'] = str(exc)
        return text
    finally:
        lock.release()


def run_dual_chat(key, model, messages, trace=None):
    from freeapi.memory import contains_cyrillic
    has_translator = (
        bool(key.get('translator_account_id')) and
        key['translator_account_id'] != key['tg_account_id']
    )

    text, _ = extract_payload(messages)
    is_ru = contains_cyrillic(text) and has_translator
    logger.info('[DUAL] key_id=%s main_account=%s translator_account=%s has_translator=%s cyrillic=%s model=%s', key.get('id'), key.get('tg_account_id'), key.get('translator_account_id'), has_translator, contains_cyrillic(text), model)

    if trace is not None:
        trace['dual_mode'] = True
        trace['has_translator'] = has_translator
        trace['is_ru'] = is_ru
        trace['original_text'] = text

    if is_ru:
        logger.info('[DUAL] Запрос на русском — переводим EN для основного аккаунта')
        text_en = run_translate(key, text, direction='en', trace=trace, trace_key='text_translated_to_en')
        if trace is not None:
            trace['sent_to_main'] = text_en
        modified = [dict(m) for m in messages]
        for i in range(len(modified) - 1, -1, -1):
            if modified[i].get('role') == 'user':
                modified[i] = dict(modified[i])
                content = modified[i]['content']
                if isinstance(content, str):
                    modified[i]['content'] = text_en
                elif isinstance(content, list):
                    modified[i]['content'] = [
                        {'type': 'text', 'text': text_en} if (isinstance(p, dict) and p.get('type') == 'text') else p
                        for p in content
                    ]
                break
        messages_to_send = modified
    else:
        if trace is not None:
            trace['sent_to_main'] = text
        messages_to_send = messages

    answer = run_chat(key, model, messages_to_send, trace=trace)

    if is_ru and has_translator:
        logger.info('[DUAL] Переводим ответ обратно на RU')
        result = run_translate(key, answer, direction='ru', trace=trace, trace_key='answer_translated_to_ru')
        return result

    return answer


def run_setup_background(setup_id, user_id, account_id, start_step=1):
    threading.Thread(target=lambda: asyncio.run(SetupFlow(setup_id, user_id, account_id, start_step=start_step).run()), daemon=True).start()


def run_control(key, command):
    account = repo.get_tg_account(key['tg_account_id'])
    async def job():
        async with TgSession(account) as tg:
            bot = await tg.bot()
            await tg.send_message(bot, command)
    asyncio.run(job())


def switch_model_background(key_id, model):
    def target():
        key = repo.get_key_by_id(key_id)
        if not key:
            return
        account = repo.get_tg_account(key['tg_account_id'])
        async def job():
            async with TgSession(account) as tg:
                sponsors = SponsorHandler(tg)
                await ModelSwitcher(tg, sponsors).switch(key, model)
        try:
            asyncio.run(job())
        except Exception:
            pass
    threading.Thread(target=target, daemon=True).start()
