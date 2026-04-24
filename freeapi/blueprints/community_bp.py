"""Blueprint «Сообщество»: общий чат + посты администраторов.

См. plan.txt блок 2 — все эндпоинты помечены там же. Логирование сделано
максимально подробным (на каждое действие отдельный logger.info), потому что
SQLite-чат через WebView без логов отлаживать невозможно.
"""
import logging
import os

from flask import Blueprint, jsonify, request

from freeapi import repositories as repo
from freeapi.repos import community as cm
from freeapi.repos import users as users_repo
from freeapi.security import uuid4
from freeapi import tg_notify
from freeapi.blueprints._helpers import (
    error, current_user_id, require_user, is_admin,
)

logger = logging.getLogger('freeapi')

bp = Blueprint('community', __name__)


def _tg_notify_token():
    """TG_NOTIFY_TOKEN из окружения. Может отсутствовать — тогда пуши тихо
    выключены (на сайте всё равно живёт обычное in-app уведомление)."""
    return (os.environ.get('TG_NOTIFY_TOKEN') or '').strip()


# ─── ВСПОМОГАТЕЛЬНОЕ ─────────────────────────────────────────────────


def _require_chat_access():
    """Проверка авторизации + бана в чате."""
    if not current_user_id():
        return error('Требуется авторизация', 401)
    uid = current_user_id()
    ban = cm.get_chat_ban(uid)
    if ban:
        return error(
            f'Вы забанены в чате до {ban["banned_until"]}'
            + (f'. Причина: {ban["reason"]}' if ban.get('reason') else ''),
            403, log_code='COMMUNITY_BANNED',
        )
    return None


def _notify_mentions(message_id):
    """Создать уведомления типа 'community' для всех упомянутых юзеров.

    M3: дополнительно отправляем пуш в личку привязанного TG-бота
    (если у юзера есть tg_notify_chat_id и не включён mute_mentions).
    Любая ошибка TG никогда не валит запрос — внутреннее уведомление
    создаётся в любом случае.
    """
    try:
        mentions = cm.get_unnotified_mentions(message_id)
        if not mentions:
            return
        msg_obj = cm.get_message(message_id)
        if not msg_obj:
            return
        author_name = msg_obj.get('username') or '?'
        snippet = (msg_obj.get('text') or '').strip().replace('\n', ' ')
        if len(snippet) > 140:
            snippet = snippet[:140].rstrip() + '…'
        token = _tg_notify_token()
        for m in mentions:
            target = m['mentioned_user_id']
            try:
                if cm.get_mute_mentions(target):
                    cm.mark_mention_notified(m['id'])
                    logger.info('[COMMUNITY][MENTION] uid=%s muted, skip', target)
                    continue
                repo.create_user_notification(
                    target,
                    f'@{author_name} упомянул(а) вас: {snippet}',
                    kind='community',
                    ref_id=message_id,
                )
                cm.mark_mention_notified(m['id'])
                logger.info('[COMMUNITY][MENTION] notified uid=%s msg=%s',
                            target, message_id)
                # M3: TG-пуш
                if token:
                    try:
                        tg_chat = users_repo.get_tg_notify_chat_id(target)
                        if tg_chat:
                            ok = tg_notify.send_mention_push(
                                token, tg_chat, author_name, snippet, message_id,
                            )
                            logger.info(
                                '[COMMUNITY][MENTION-TG] uid=%s chat=%s ok=%s',
                                target, tg_chat, ok,
                            )
                    except Exception as tg_exc:
                        logger.warning(
                            '[COMMUNITY][MENTION-TG] uid=%s push failed: %s',
                            target, tg_exc,
                        )
            except Exception as exc:
                logger.warning('[COMMUNITY][MENTION] notify failed uid=%s: %s',
                               target, exc)
    except Exception as exc:
        logger.warning('[COMMUNITY][MENTION] _notify_mentions: %s', exc)


# ─── ЧТЕНИЕ ──────────────────────────────────────────────────────────


@bp.get('/api/community/state')
def community_state():
    """Состояние раздела для текущего юзера: бан/админ/мьют."""
    uid = current_user_id()
    payload = {
        'is_authenticated': bool(uid),
        'is_admin': is_admin(uid) if uid else False,
        'chat_ban': cm.get_chat_ban(uid) if uid else None,
        'mute_mentions': cm.get_mute_mentions(uid) if uid else False,
    }
    return jsonify(payload)


@bp.get('/api/community/messages')
def community_get_messages():
    """Лента чата (kind='message'). before_id — для пагинации вглубь."""
    uid = current_user_id()
    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 100))
    except Exception:
        limit = 50
    before_id = request.args.get('before_id')
    items = cm.list_messages(
        kind='message', limit=limit, before_id=before_id,
        viewer_uid=uid, include_deleted=False,
    )
    pinned = cm.list_pinned(viewer_uid=uid)
    logger.info('[COMMUNITY][LIST] kind=message uid=%s limit=%s before=%s → %s items, %s pins',
                uid, limit, before_id, len(items), len(pinned))
    return jsonify({'messages': items, 'pinned': pinned})


@bp.get('/api/community/posts')
def community_get_posts():
    """Лента постов (kind='admin_post')."""
    uid = current_user_id()
    try:
        limit = max(1, min(int(request.args.get('limit', 30)), 100))
    except Exception:
        limit = 30
    before_id = request.args.get('before_id')
    items = cm.list_messages(
        kind='admin_post', limit=limit, before_id=before_id,
        viewer_uid=uid, include_deleted=False,
    )
    logger.info('[COMMUNITY][LIST] kind=admin_post uid=%s → %s items',
                uid, len(items))
    return jsonify({'posts': items})


@bp.get('/api/community/message/<message_id>')
def community_get_message(message_id):
    uid = current_user_id()
    msg = cm.get_message(message_id, viewer_uid=uid, include_deleted=False)
    if not msg:
        return error('Сообщение не найдено', 404)
    return jsonify({'message': msg})


@bp.get('/api/community/message/<message_id>/versions')
def community_get_versions(message_id):
    """Только админ видит историю чужих сообщений; владелец видит свою."""
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    msg = cm.get_message(message_id, viewer_uid=uid, include_deleted=True)
    if not msg:
        return error('Сообщение не найдено', 404)
    if msg['user_id'] != uid and not is_admin(uid):
        return error('Нет доступа', 403)
    versions = cm.get_message_versions(message_id)
    logger.info('[COMMUNITY][VERSIONS] msg=%s by uid=%s → %s versions',
                message_id, uid, len(versions))
    return jsonify({'message_id': message_id, 'versions': versions})


@bp.get('/api/community/users/lookup')
def community_user_lookup():
    """Автокомплит для @-упоминаний."""
    err = require_user()
    if err:
        return err
    prefix = (request.args.get('q') or '').strip()
    items = cm.lookup_users_by_prefix(prefix, limit=8)
    return jsonify({'users': items})


# ─── ЗАПИСЬ ──────────────────────────────────────────────────────────


@bp.post('/api/community/messages')
def community_send_message():
    err = _require_chat_access()
    if err:
        return err
    uid = current_user_id()
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    images = data.get('images') or []
    mentions = data.get('mentions') or []
    if not text and not images:
        return error('Сообщение пустое', 400)
    try:
        msg, mention_ids = cm.create_message(
            uid, text, kind='message', images=images, mentions=mentions,
        )
    except ValueError as ve:
        return error(str(ve), 400)
    if msg:
        _notify_mentions(msg['id'])
    return jsonify({'message': msg})


@bp.post('/api/community/posts')
def community_create_post():
    """Только админ. Пост идёт в отдельный фид admin_post."""
    err = require_user()
    if err:
        return err
    if not is_admin(current_user_id()):
        return error('Нет доступа', 403)
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    images = data.get('images') or []
    if not text and not images:
        return error('Пост пустой', 400)
    try:
        msg, _ = cm.create_message(
            current_user_id(), text, kind='admin_post',
            images=images, mentions=[],
        )
    except ValueError as ve:
        return error(str(ve), 400)
    return jsonify({'post': msg})


@bp.patch('/api/community/messages/<message_id>')
def community_edit_message(message_id):
    err = _require_chat_access()
    if err:
        return err
    uid = current_user_id()
    msg = cm.get_message(message_id, viewer_uid=uid, include_deleted=True)
    if not msg:
        return error('Сообщение не найдено', 404)
    if msg.get('is_deleted'):
        return error('Сообщение удалено, редактирование невозможно', 400)
    if msg['user_id'] != uid:
        return error('Можно редактировать только свои сообщения', 403)
    data = request.get_json(silent=True) or {}
    new_text = (data.get('text') or '').strip()
    new_images = data.get('images') or []
    if not new_text and not new_images:
        return error('Сообщение пустое', 400)
    try:
        updated = cm.edit_message(message_id, new_text, new_images, edited_by=uid)
    except ValueError as ve:
        return error(str(ve), 400)
    return jsonify({'message': updated})


@bp.delete('/api/community/messages/<message_id>')
def community_delete_own(message_id):
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    msg = cm.get_message(message_id, viewer_uid=uid, include_deleted=True)
    if not msg:
        return error('Сообщение не найдено', 404)
    if msg.get('is_deleted'):
        return jsonify({'deleted': True})
    if msg['user_id'] != uid:
        return error('Можно удалять только свои сообщения', 403)
    ok, _ = cm.soft_delete(message_id, deleted_by=uid)
    return jsonify({'deleted': bool(ok)})


@bp.delete('/api/community/messages/<message_id>/admin')
def community_delete_admin(message_id):
    """Админское удаление чужого сообщения (soft-delete + плашка)."""
    err = require_user()
    if err:
        return err
    if not is_admin(current_user_id()):
        return error('Нет доступа', 403)
    msg = cm.get_message(message_id, viewer_uid=current_user_id(), include_deleted=True)
    if not msg:
        return error('Сообщение не найдено', 404)
    if msg.get('is_deleted'):
        return jsonify({'deleted': True})
    ok, author_uid = cm.soft_delete(message_id, deleted_by=current_user_id())
    # Уведомляем автора
    if ok and author_uid and author_uid != current_user_id():
        try:
            repo.create_user_notification(
                author_uid,
                'Ваше сообщение в Сообществе удалено администратором.',
                kind='community',
                ref_id=message_id,
            )
        except Exception as exc:
            logger.warning('[COMMUNITY][DEL-NOTIFY] failed: %s', exc)
    return jsonify({'deleted': bool(ok)})


@bp.post('/api/community/messages/<message_id>/react')
def community_react(message_id):
    err = _require_chat_access()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    emoji = (data.get('emoji') or '').strip()
    if not emoji:
        return error('Не указан emoji', 400)
    try:
        cm.toggle_reaction(message_id, current_user_id(), emoji)
    except ValueError as ve:
        return error(str(ve), 400)
    msg = cm.get_message(message_id, viewer_uid=current_user_id())
    if not msg:
        return error('Сообщение не найдено', 404)
    return jsonify({'message': msg})


# ─── ЗАКРЕПЫ ─────────────────────────────────────────────────────────


@bp.post('/api/community/messages/<message_id>/pin')
def community_pin(message_id):
    err = require_user()
    if err:
        return err
    if not is_admin(current_user_id()):
        return error('Нет доступа', 403)
    ok = cm.pin_message(message_id, pinned_by=current_user_id())
    if not ok:
        return error('Сообщение не найдено или удалено', 404)
    return jsonify({'pinned': True})


@bp.delete('/api/community/messages/<message_id>/pin')
def community_unpin(message_id):
    err = require_user()
    if err:
        return err
    if not is_admin(current_user_id()):
        return error('Нет доступа', 403)
    cm.unpin_message(message_id)
    return jsonify({'pinned': False})


# ─── БАН В ЧАТЕ ──────────────────────────────────────────────────────


@bp.get('/api/community/bans')
def community_list_bans():
    err = require_user()
    if err:
        return err
    if not is_admin(current_user_id()):
        return error('Нет доступа', 403)
    return jsonify({'bans': cm.list_chat_bans()})


@bp.post('/api/community/bans')
def community_add_ban():
    err = require_user()
    if err:
        return err
    if not is_admin(current_user_id()):
        return error('Нет доступа', 403)
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    days = int(data.get('days') or 7)
    reason = (data.get('reason') or '').strip() or None
    if not username:
        return error('Не указан логин', 400)
    if days < 1 or days > 365:
        return error('days должен быть 1..365', 400)
    target = repo.get_user_by_username(username)
    if not target:
        return error(f'Пользователь @{username} не найден', 404)
    until = cm.ban_in_chat(target['id'], days, reason, banned_by=current_user_id())
    try:
        repo.create_user_notification(
            target['id'],
            f'Вы забанены в Сообществе на {days} дн. до {until}'
            + (f'. Причина: {reason}' if reason else ''),
            kind='community',
        )
    except Exception:
        pass
    return jsonify({'ok': True, 'banned_until': until})


@bp.delete('/api/community/bans/<user_id>')
def community_remove_ban(user_id):
    err = require_user()
    if err:
        return err
    if not is_admin(current_user_id()):
        return error('Нет доступа', 403)
    cm.unban_in_chat(user_id)
    return jsonify({'ok': True})


# ─── НАСТРОЙКИ MENTION-MUTE ─────────────────────────────────────────


@bp.post('/api/community/mute_mentions')
def community_mute_mentions():
    err = require_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    cm.set_mute_mentions(current_user_id(), bool(data.get('mute')))
    return jsonify({'mute': cm.get_mute_mentions(current_user_id())})


# ─── M3: TG-ПРИВЯЗКА ДЛЯ ПУШЕЙ ──────────────────────────────────────


def _tg_link_status_payload(user_id):
    """Собрать актуальное состояние привязки + deep-link для UI.

    Если бот недоступен (нет TG_NOTIFY_TOKEN или getMe не отвечает) —
    отдаём available=False и UI скроет блок. Это не ошибка.
    """
    state = users_repo.get_user_tg_notify(user_id) or {}
    chat_id = state.get('chat_id')
    link_token = state.get('link_token')
    linked_at = state.get('linked_at')
    mute = cm.get_mute_mentions(user_id)
    token = _tg_notify_token()
    bot_username = tg_notify.get_bot_username(token) if token else None

    # Если нет постоянной привязки и нет токена — выдадим новый, чтобы
    # фронт сразу мог показать кнопку «Привязать».
    if token and bot_username and not chat_id and not link_token:
        link_token = uuid4().replace('-', '')
        users_repo.set_tg_notify_link_token(user_id, link_token)
        logger.info('[COMMUNITY][TG_LINK] uid=%s issued new link token', user_id)

    link_url = None
    if bot_username and link_token and not chat_id:
        link_url = f'https://t.me/{bot_username}?start={link_token}'

    return {
        'available': bool(token and bot_username),
        'bot_username': bot_username,
        'linked': bool(chat_id),
        'chat_id': chat_id,
        'linked_at': linked_at,
        'link_url': link_url,
        'link_token': link_token if not chat_id else None,
        'mute_mentions': bool(mute),
    }


@bp.get('/api/community/tg_link')
def community_tg_link_status():
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    payload = _tg_link_status_payload(uid)
    logger.info('[COMMUNITY][TG_LINK] uid=%s status linked=%s available=%s',
                uid, payload['linked'], payload['available'])
    return jsonify(payload)


@bp.post('/api/community/tg_link/regenerate')
def community_tg_link_regenerate():
    """Сбросить старый одноразовый токен и выдать новый. Только если ещё
    нет постоянной привязки — иначе ничего не делаем (пусть юзер сначала
    отвяжет)."""
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    state = users_repo.get_user_tg_notify(uid) or {}
    if state.get('chat_id'):
        return error('TG уже привязан, сначала отвяжите.', status=400,
                     log_code='CM_TG_LINK_ALREADY')
    new_token = uuid4().replace('-', '')
    users_repo.set_tg_notify_link_token(uid, new_token)
    logger.info('[COMMUNITY][TG_LINK] uid=%s regenerated token', uid)
    return jsonify(_tg_link_status_payload(uid))


@bp.post('/api/community/tg_link/manual')
def community_tg_link_manual():
    """Ручная привязка по chat_id (для тех, кто уже знает свой ID,
    например, из @userinfobot)."""
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    data = request.get_json(silent=True) or {}
    raw = str(data.get('chat_id') or '').strip()
    if not raw:
        return error('Не указан chat_id.', status=400, log_code='CM_TG_LINK_BAD_INPUT')
    # Базовая валидация: целое число (Telegram chat_id всегда integer).
    try:
        chat_id_int = int(raw)
    except ValueError:
        return error('chat_id должен быть числом.', status=400,
                     log_code='CM_TG_LINK_BAD_INPUT')
    token = _tg_notify_token()
    if not token:
        return error('Бот уведомлений не настроен на сервере.', status=503,
                     log_code='CM_TG_LINK_NO_BOT')
    # Проверочное сообщение: если бот не может писать юзеру — привязку отклоняем.
    ok = tg_notify.send_html_to_user(
        token, chat_id_int,
        '✅ <b>Telegram привязан</b> к FavoriteAPI вручную. Теперь сюда будут '
        'приходить уведомления о @упоминаниях в общем чате.',
    )
    if not ok:
        return error(
            'Бот не смог написать вам в личку. Сначала откройте чат с ботом '
            'и отправьте ему /start, потом повторите.',
            status=400, log_code='CM_TG_LINK_BOT_BLOCKED',
        )
    users_repo.set_tg_notify_chat_id(uid, chat_id_int)
    logger.info('[COMMUNITY][TG_LINK] uid=%s manual link chat=%s', uid, chat_id_int)
    return jsonify(_tg_link_status_payload(uid))


@bp.delete('/api/community/tg_link')
def community_tg_link_unlink():
    err = require_user()
    if err:
        return err
    uid = current_user_id()
    state = users_repo.get_user_tg_notify(uid) or {}
    old_chat = state.get('chat_id')
    users_repo.clear_tg_notify(uid)
    # Прощальное сообщение (best-effort, ошибки игнорируем).
    token = _tg_notify_token()
    if token and old_chat:
        try:
            tg_notify.send_html_to_user(
                token, old_chat,
                '👋 Привязка с FavoriteAPI отключена. Уведомления о '
                'упоминаниях больше приходить не будут.',
            )
        except Exception:
            pass
    logger.info('[COMMUNITY][TG_LINK] uid=%s unlinked old_chat=%s', uid, old_chat)
    return jsonify(_tg_link_status_payload(uid))
