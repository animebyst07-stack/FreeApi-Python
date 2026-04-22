"""Blueprints для FreeApi-Python (рефакторинг шага 0.2).

Регистрирует все blueprint'ы в Flask-приложении. URL и тела ответов
не меняются — это чистая реорганизация.
"""
from . import (
    admin_bp,
    auth_bp,
    chat_bp,
    keys_bp,
    misc_bp,
    notifications_bp,
    reviews_bp,
    support_bp,
    tg_bp,
)

ALL_BLUEPRINTS = (
    misc_bp.bp,
    auth_bp.bp,
    tg_bp.bp,
    keys_bp.bp,
    chat_bp.bp,
    reviews_bp.bp,
    notifications_bp.bp,
    admin_bp.bp,
    support_bp.bp,
)


def register_all_blueprints(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
