"""Backwards-compat shim — содержимое перенесено в пакет freeapi/repos/ (шаг 0.3).

Все существующие импорты вида `from freeapi import repositories as repo`
продолжают работать без изменений.
"""
from freeapi.repos import *  # noqa: F401,F403
