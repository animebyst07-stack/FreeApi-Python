"""Репозиторий админ-роли (блок 1.10 плана).

Заменяет хардкод `username == 'ReZero'`. ReZero остаётся суперадмином
(is_super=1), которого нельзя разжаловать.
"""
import logging

from freeapi.database import db, row, rows, msk_now

logger = logging.getLogger('freeapi')

SUPER_ADMIN_USERNAME = 'ReZero'


def is_admin_user(user_id):
    """Является ли пользователь админом.

    True если EXISTS в admins ИЛИ username == ReZero (двойная защита
    на случай рассинхрона сидинга).
    """
    if not user_id:
        return False
    with db() as conn:
        r = conn.execute('SELECT 1 FROM admins WHERE user_id=?', (user_id,)).fetchone()
        if r:
            return True
        r2 = conn.execute(
            'SELECT 1 FROM users WHERE id=? AND username=?',
            (user_id, SUPER_ADMIN_USERNAME),
        ).fetchone()
        return bool(r2)


def is_super_admin_user(user_id):
    """Является ли суперадмином (может назначать/снимать других)."""
    if not user_id:
        return False
    with db() as conn:
        r = conn.execute(
            'SELECT is_super FROM admins WHERE user_id=?', (user_id,)
        ).fetchone()
        if r and int(r['is_super'] or 0) == 1:
            return True
        r2 = conn.execute(
            'SELECT 1 FROM users WHERE id=? AND username=?',
            (user_id, SUPER_ADMIN_USERNAME),
        ).fetchone()
        return bool(r2)


def list_admins():
    """Список всех админов с username/granted_by_username для UI."""
    with db() as conn:
        return rows(conn.execute(
            'SELECT a.user_id, a.is_super, a.granted_at, a.granted_by, '
            '       u.username AS username, '
            '       gb.username AS granted_by_username '
            'FROM admins a '
            'JOIN users u  ON u.id = a.user_id '
            'LEFT JOIN users gb ON gb.id = a.granted_by '
            'ORDER BY a.is_super DESC, a.granted_at ASC'
        ).fetchall())


def add_admin_by_username(username, granted_by_user_id):
    """Назначить админа по логину. Возвращает (ok, message)."""
    username = (username or '').strip()
    if not username:
        return False, 'Логин пуст'
    with db() as conn:
        u = conn.execute('SELECT id, username FROM users WHERE username=?', (username,)).fetchone()
        if not u:
            return False, f'Пользователь @{username} не найден'
        existing = conn.execute('SELECT user_id FROM admins WHERE user_id=?', (u['id'],)).fetchone()
        if existing:
            return False, f'@{username} уже админ'
        conn.execute(
            'INSERT INTO admins(user_id, granted_by, granted_at, is_super) '
            'VALUES (?, ?, ?, 0)',
            (u['id'], granted_by_user_id, msk_now()),
        )
        logger.info('[ADMINS] add: granted_by=%s → %s (%s)',
                    granted_by_user_id, u['id'], username)
        return True, 'OK'


def remove_admin(user_id, removed_by_user_id):
    """Снять админа. Суперадмина снять нельзя. Возвращает (ok, message)."""
    if not user_id:
        return False, 'user_id пуст'
    with db() as conn:
        r = conn.execute(
            'SELECT a.is_super, u.username FROM admins a '
            'JOIN users u ON u.id = a.user_id WHERE a.user_id=?',
            (user_id,),
        ).fetchone()
        if not r:
            return False, 'Этот пользователь не админ'
        if int(r['is_super'] or 0) == 1:
            return False, 'Нельзя снять суперадмина'
        if r['username'] == SUPER_ADMIN_USERNAME:
            return False, 'Нельзя снять суперадмина'
        conn.execute('DELETE FROM admins WHERE user_id=?', (user_id,))
        logger.info('[ADMINS] remove: removed_by=%s → %s (%s)',
                    removed_by_user_id, user_id, r['username'])
        return True, 'OK'


def ensure_super_admin_seeded():
    """Гарантирует, что ReZero (если зарегистрирован) — суперадмин.

    Вызывается из _seed_reference_data на каждом старте, чтобы починить
    рассинхрон, если ReZero зарегистрировался ПОСЛЕ применения миграции 010.
    """
    with db() as conn:
        u = conn.execute(
            'SELECT id FROM users WHERE username=?', (SUPER_ADMIN_USERNAME,)
        ).fetchone()
        if not u:
            return
        existing = conn.execute(
            'SELECT user_id, is_super FROM admins WHERE user_id=?', (u['id'],)
        ).fetchone()
        if existing:
            if int(existing['is_super'] or 0) != 1:
                conn.execute('UPDATE admins SET is_super=1 WHERE user_id=?', (u['id'],))
                logger.info('[ADMINS] auto-promoted ReZero to super')
        else:
            conn.execute(
                'INSERT INTO admins(user_id, granted_by, granted_at, is_super) '
                'VALUES (?, NULL, ?, 1)',
                (u['id'], msk_now()),
            )
            logger.info('[ADMINS] auto-seeded ReZero as super admin')

        # M3.4: автоматически выдать ReZero дефолтный display_prefix='Admin',
        # если он ещё не задан вручную. На фронте такой же fallback есть
        # для всех админов, но в БД полезно держать значение для
        # консистентности при ручных запросах/админ-инструментах.
        cur = conn.execute(
            'SELECT display_prefix FROM users WHERE id=?', (u['id'],)
        ).fetchone()
        if cur is not None and not (cur['display_prefix'] or '').strip():
            conn.execute(
                'UPDATE users SET display_prefix=? WHERE id=?',
                ('Admin', u['id']),
            )
            logger.info('[ADMINS] auto-set display_prefix=Admin for ReZero')
