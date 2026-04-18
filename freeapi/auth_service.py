import re

from werkzeug.security import check_password_hash, generate_password_hash

from freeapi import repositories as repo


def register_user(username, password):
    if not isinstance(username, str) or len(username) < 3 or len(username) > 50:
        return None, 'Логин должен быть от 3 до 50 символов', 400
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return None, 'Только латиница, цифры и _', 400
    if not isinstance(password, str) or len(password) < 6 or len(password) > 100:
        return None, 'Пароль должен быть от 6 до 100 символов', 400
    if repo.get_user_by_username(username):
        return None, 'Логин уже занят', 409
    return repo.create_user(username, generate_password_hash(password)), None, 201


def login_user(username, password):
    user = repo.get_user_by_username(username)
    if not user or not check_password_hash(user['password_hash'], password):
        return None, 'Неверный логин или пароль', 401
    repo.touch_login(user['id'])
    return repo.get_user_by_id(user['id']), None, 200
