"""Пакет repos: реэкспорт всех функций для обратной совместимости.

Бизнес-логика не менялась — это чистая реорганизация (шаг 0.3 плана).
Старый импорт `from freeapi import repositories as repo` продолжает работать
через шим freeapi/repositories.py.
"""
from .users import *  # noqa: F401,F403
from .tg_accounts import *  # noqa: F401,F403
from .keys import *  # noqa: F401,F403
from .stats import *  # noqa: F401,F403
from .reviews import *  # noqa: F401,F403
from .notifications import *  # noqa: F401,F403
from .admin import *  # noqa: F401,F403
from .support import *  # noqa: F401,F403
