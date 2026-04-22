"""Тонкий шим — оставлен для обратной совместимости.

Бизнес-логика endpoint'ов перенесена в freeapi/blueprints/* (шаг 0.2).
register_routes(app) теперь только регистрирует все blueprint'ы.
"""
from freeapi.blueprints import register_all_blueprints


def register_routes(app):
    register_all_blueprints(app)
