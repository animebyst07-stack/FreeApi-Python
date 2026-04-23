import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta

from freeapi.database import MSK

logger = logging.getLogger('freeapi.agent')

AGENT_NAME = 'Favorite AI Agent'

DEFAULT_MODERATOR_PROMPT = f"""Ты — {AGENT_NAME}, автономный модератор сервиса FreeApi/FavoriteAPI.
Твоя задача — честно анализировать отзывы пользователей о сайте и защищать качество публичной ленты.

Правила принятия решений:
- APPROVE: отзыв позитивный, нейтральный или нормально обоснованный (оценка >= 8 или оценка < 8, но с аргументами)
- DELETE: отзыв бессмысленный (набор символов вроде "asdfgh", "фываолд"), спамный, содержит грубую нецензурную лексику, или оценка < 8 без каких-либо аргументов/обоснований
- FEEDBACK: отзыв содержит конструктивную критику, баг-репорт, идею улучшения или совет

При APPROVE — сформируй короткий официальный ответ пользователю. Представься как "{AGENT_NAME}".
При DELETE — укажи краткую причину удаления.
При FEEDBACK — сформируй публичный ответ с фразой "Спасибо за идею, передал ваш фидбек администратору" и дай структурированный совет админу. Представься как "{AGENT_NAME}".

ВСЕГДА отвечай строго в формате JSON без дополнительного текста:
{{{{
  "action": "APPROVE" | "DELETE" | "FEEDBACK",
  "public_response": "Публичный ответ под отзывом (для APPROVE и FEEDBACK, иначе null)",
  "admin_advice": "Совет администратору (только для FEEDBACK, иначе null)",
  "reason": "Внутреннее обоснование решения"
}}}}"""


def _get_moderator_prompt():
    try:
        from freeapi import repositories as repo
        custom = repo.get_admin_setting('moderator_system_prompt', '')
        if custom and custom.strip():
            return custom.strip()
    except Exception:
        pass
    return DEFAULT_MODERATOR_PROMPT

_GARBAGE_PATTERN = re.compile(r'^[a-zA-Zа-яА-ЯёЁ\s]{1,}$')
_GIBBERISH_PATTERN = re.compile(r'([a-z])\1{3,}|[bcdfghjklmnpqrstvwxyz]{5,}|[бвгджзклмнпрстфхцчшщ]{5,}', re.IGNORECASE)


def _is_gibberish(text):
    cleaned = text.strip()
    if len(cleaned) < 5:
        return True
    if _GIBBERISH_PATTERN.search(cleaned):
        return True
    unique_chars = set(cleaned.lower().replace(' ', ''))
    if len(unique_chars) <= 3 and len(cleaned) > 5:
        return True
    return False


class FavoriteAIAgent:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name='FavoriteAIAgent', daemon=True)
        self._thread.start()
        logger.info('[Agent] %s запущен', AGENT_NAME)

    def stop(self):
        self._stop_event.set()
        self._wake_event.set()
        self._running = False
        logger.info('[Agent] %s остановлен', AGENT_NAME)

    def kick(self):
        self._wake_event.set()

    def _loop(self):
        while not self._stop_event.is_set():
            self._wake_event.clear()
            try:
                self._process_pending()
            except Exception as exc:
                logger.error('[Agent] Ошибка в основном цикле: %s', exc)
            self._wake_event.wait(5)

    def _process_pending(self):
        try:
            from freeapi import repositories as repo
        except Exception:
            return

        enabled = repo.get_admin_setting('moderator_enabled', repo.get_admin_setting('agent_enabled', '0'))
        if enabled != '1':
            logger.debug('[Agent] tick: moderator_enabled=%r — пропускаю', enabled)
            return

        key_id = repo.get_admin_setting('moderator_key_id', repo.get_admin_setting('agent_key_id', ''))
        if not key_id:
            logger.warning('[Agent] tick: moderator включён, но key_id пустой — модерация невозможна')
            return

        key = self._get_key(key_id)
        if not key:
            logger.warning('[Agent] Ключ агента не найден: %s', key_id)
            return

        pending = repo.get_pending_reviews()
        if not pending:
            logger.debug('[Agent] tick: pending очередь пуста')
            return
        logger.info('[Agent] tick: найдено pending отзывов=%s, начинаю модерацию', len(pending))

        for review in pending:
            if self._stop_event.is_set():
                break
            try:
                self._moderate(review, key, repo)
            except Exception as exc:
                logger.error('[Agent] Ошибка модерации отзыва %s: %s', review.get('id'), exc)
            time.sleep(2)

    def _get_key(self, key_id):
        try:
            from freeapi.database import db, row
            with db() as conn:
                return row(conn.execute('SELECT * FROM api_keys WHERE id=? AND is_active=1', (key_id,)).fetchone())
        except Exception:
            return None

    def _moderate(self, review, key, repo):
        from freeapi.tg import run_chat
        from freeapi.models import DEFAULT_MODEL_ID

        review_id = review.get('id')
        review_text = review.get('text', '')
        review_score = review.get('score', 0)
        review_author = review.get('username', 'аноним')
        user_id = review.get('user_id')

        raw_images = review.get('images')
        review_images = []
        if isinstance(raw_images, list):
            review_images = raw_images
        elif isinstance(raw_images, str) and raw_images.strip():
            try:
                import json as _json
                parsed = _json.loads(raw_images)
                if isinstance(parsed, list):
                    review_images = [str(x) for x in parsed if isinstance(x, str) and x]
            except Exception:
                review_images = []
        review_images = review_images[:10]

        logger.info('[Agent] Отзыв %s (score=%s, len=%s, images=%s) → отправляю в AI на модерацию', review_id, review_score, len(review_text), len(review_images))

        system_prompt = _get_moderator_prompt()
        prompt_text = (
            f'{system_prompt}\n\n'
            f'Проанализируй следующий отзыв о платформе FavoriteAPI:\n\n'
            f'Оценка: {review_score}/10\n'
            f'Автор: {review_author}\n'
            f'Текст: {review_text}\n'
        )
        if review_images:
            prompt_text += (
                f'\nК отзыву прикреплено {len(review_images)} '
                f'фото — обязательно посмотри их и учти содержимое в решении '
                f'(подтверждают ли они слова автора, есть ли там оскорбления, '
                f'NSFW, утечки приватных данных и т.п.).\n'
            )
            content_parts = [{'type': 'text', 'text': prompt_text}]
            for img_url in review_images:
                content_parts.append({'type': 'image_url', 'image_url': {'url': img_url}})
            messages = [{'role': 'user', 'content': content_parts}]
        else:
            messages = [{'role': 'user', 'content': prompt_text}]

        try:
            model = key.get('default_model') or DEFAULT_MODEL_ID
            answer = run_chat(key, model, messages)
            decision = self._parse_decision(answer)
        except Exception as exc:
            logger.error('[Agent] Ошибка run_chat для отзыва %s: %s', review_id, exc)
            return

        action = str(decision.get('action', 'FEEDBACK')).upper()
        public_response = decision.get('public_response')
        admin_advice = decision.get('admin_advice')
        reason = decision.get('reason', '')

        logger.info('[Agent] Отзыв %s: action=%s reason=%s', review_id, action, reason)

        if action == 'APPROVE':
            if public_response and AGENT_NAME not in public_response:
                public_response = f'— {AGENT_NAME}\n{public_response}'
            repo.update_review_status(review_id, 'approved', ai_response=public_response)
            if public_response and user_id:
                repo.create_user_notification(
                    user_id,
                    f'Ваш отзыв опубликован. Ответ платформы: {public_response}'
                )
        elif action == 'DELETE':
            self._do_delete(review_id, user_id, reason or 'Необоснованная критика / мусорный контент', repo)
        elif action == 'FEEDBACK':
            if not public_response:
                public_response = f'— {AGENT_NAME}\nСпасибо за идею, передал ваш фидбек администратору.'
            elif 'передал' not in public_response.lower():
                public_response = public_response.rstrip() + ' Спасибо за идею, передал ваш фидбек администратору.'
            if AGENT_NAME not in public_response:
                public_response = f'— {AGENT_NAME}\n{public_response}'
            repo.update_review_status(review_id, 'flagged', ai_response=public_response)
            repo.create_admin_notification(
                review_id=review_id,
                review_text=review_text,
                review_score=review_score,
                review_author=review_author,
                ai_response=public_response or '',
                ai_advice=admin_advice or reason
            )
            if user_id:
                repo.create_user_notification(
                    user_id,
                    f'Ваш отзыв опубликован, а полезный фидбек передан администратору. — {AGENT_NAME}'
                )

    def _do_delete(self, review_id, user_id, reason, repo):
        from freeapi.database import msk_now, MSK
        banned_until = (datetime.now(MSK) + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        repo.delete_review(review_id)
        if user_id:
            repo.restrict_review_access(user_id, banned_until, reason)
            repo.create_user_notification(
                user_id,
                f'Ваш отзыв удалён модератором ({AGENT_NAME}). '
                f'Причина: {reason}. '
                f'Доступ к отзывам ограничен на 1 неделю (до {banned_until} МСК).'
            )

    def _parse_decision(self, answer):
        try:
            text = answer.strip()
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                text = text[start:end + 1]
            return json.loads(text)
        except Exception:
            return {'action': 'FEEDBACK', 'reason': 'Не удалось разобрать ответ агента', 'public_response': None, 'admin_advice': answer[:200]}


_agent_instance = None
_agent_lock = threading.Lock()


def get_agent():
    global _agent_instance
    with _agent_lock:
        if _agent_instance is None:
            _agent_instance = FavoriteAIAgent()
        return _agent_instance


def start_agent():
    get_agent().start()


def stop_agent():
    if _agent_instance:
        _agent_instance.stop()


def trigger_agent():
    get_agent().kick()
