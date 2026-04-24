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

        model = key.get('default_model') or DEFAULT_MODEL_ID
        has_images = bool(review_images)
        images_count = len(review_images)
        req_record = None
        try:
            req_record = repo.create_request(key['id'], model, 'REQ_START_002', has_images, images_count)
        except Exception as exc:
            logger.warning('[Agent] не удалось создать request-лог для отзыва %s: %s', review_id, exc)

        import time as _time
        _t0 = _time.time()
        try:
            answer = run_chat(key, model, messages)
            decision = self._parse_decision(answer)
            elapsed_ms = int((_time.time() - _t0) * 1000)
            if req_record is not None:
                try:
                    repo.finish_request(req_record['id'], 'ok', 'REQ_OK_001', response_ms=elapsed_ms)
                except Exception:
                    pass
            try:
                from freeapi.repos.stats import update_model_stats
                update_model_stats(model, elapsed_ms, ok=True)
            except Exception:
                pass
        except Exception as exc:
            elapsed_ms = int((_time.time() - _t0) * 1000)
            logger.error('[Agent] Ошибка run_chat для отзыва %s: %s', review_id, exc)
            if req_record is not None:
                try:
                    repo.finish_request(req_record['id'], 'error', 'REQ_ERR_500', response_ms=elapsed_ms, error_msg=str(exc)[:500])
                except Exception:
                    pass
            try:
                from freeapi.repos.stats import update_model_stats
                update_model_stats(model, elapsed_ms, ok=False)
            except Exception:
                pass
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
                    f'Ваш отзыв опубликован. Ответ платформы: {public_response}',
                    kind='review',
                    ref_id=review_id,
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
                    f'Ваш отзыв опубликован, а полезный фидбек передан администратору. — {AGENT_NAME}',
                    kind='review',
                    ref_id=review_id,
                )

    def _do_delete(self, review_id, user_id, reason, repo):
        """M1: новое поведение — скользящее окно 5 удалений за 7 дней.

        Старое поведение (до апр. 2026): любое удаление = моментальный
        бан на 7 дней. Это бесило пользователей: один спорный отзыв
        блокировал на неделю. Теперь:
          • Каждое удаление логируется в review_removals.
          • Если в окне 7 дней набрано >= REMOVAL_THRESHOLD (=5)
            удалений — накладывается бан до (первое_удаление_в_окне + 7д).
          • Иначе — бана нет, юзер просто получает уведомление.
        """
        from freeapi.database import msk_now, MSK
        from freeapi.repos.review_removals import (
            log_removal, count_recent_removals, first_removal_at_in_window,
            REMOVAL_THRESHOLD, REMOVAL_WINDOW_DAYS,
        )

        repo.delete_review(review_id)
        if not user_id:
            return

        # 1) залогировать факт удаления
        log_removal(user_id, review_id, reason, removed_by=AGENT_NAME)

        # 2) сколько уже за окно?
        cnt = count_recent_removals(user_id)
        logger.info('[REV-BAN] uid=%s removals_in_%sd=%s threshold=%s',
                    user_id, REMOVAL_WINDOW_DAYS, cnt, REMOVAL_THRESHOLD)

        if cnt >= REMOVAL_THRESHOLD:
            # 3) бан: 7 дней с момента первого удаления в окне
            first_at = first_removal_at_in_window(user_id) or msk_now()
            try:
                start_dt = datetime.strptime(first_at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=MSK)
            except Exception:
                start_dt = datetime.now(MSK)
            banned_until = (start_dt + timedelta(days=REMOVAL_WINDOW_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
            repo.restrict_review_access(user_id, banned_until,
                                        f'{REMOVAL_THRESHOLD} удалений за {REMOVAL_WINDOW_DAYS} дн.')
            repo.create_user_notification(
                user_id,
                f'Ваш отзыв удалён модератором ({AGENT_NAME}). Причина: {reason}. '
                f'Это {cnt}-е удаление за {REMOVAL_WINDOW_DAYS} дн. — '
                f'доступ к отзывам ограничен до {banned_until} МСК.',
                kind='review',
                ref_id=review_id,
            )
            logger.warning('[REV-BAN] uid=%s BANNED until %s (first_at=%s)',
                           user_id, banned_until, first_at)
        else:
            left = REMOVAL_THRESHOLD - cnt
            repo.create_user_notification(
                user_id,
                f'Ваш отзыв удалён модератором ({AGENT_NAME}). Причина: {reason}. '
                f'Удалений за {REMOVAL_WINDOW_DAYS} дн.: {cnt}/{REMOVAL_THRESHOLD}. '
                f'Ещё {left} удаление(й) — и доступ ограничат на 7 дней.',
                kind='review',
                ref_id=review_id,
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
