#!/usr/bin/env python3
import asyncio
import importlib
import os
import socket
import sqlite3
import sys
import time
import urllib.request
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / '.env'
ENV_EXAMPLE_PATH = ROOT / '.env.example'
REQUIRED_PACKAGES = {
    'Flask': 'Flask',
    'Telethon': 'Telethon',
}
REQUIRED_ENV = {
    'SESSION_SECRET': 'секрет Flask-сессий',
    'DATABASE_PATH': 'путь к SQLite базе',
    'HOST': 'host Flask-сервера',
    'PORT': 'порт Flask-сервера',
}


class CheckReport:
    def __init__(self):
        self.items = []

    def ok(self, title, detail=''):
        self.items.append(('ok', title, detail))

    def warn(self, title, detail=''):
        self.items.append(('warn', title, detail))

    def fail(self, title, detail=''):
        self.items.append(('fail', title, detail))

    def print(self):
        print('\nFreeAI / FreeApi-Python — самопроверка окружения\n')
        for status, title, detail in self.items:
            mark = '[✓]' if status == 'ok' else '[!]' if status == 'warn' else '[X]'
            print(f'{mark} {title}')
            if detail:
                print(f'    {detail}')
        failed = sum(1 for status, _, _ in self.items if status == 'fail')
        warned = sum(1 for status, _, _ in self.items if status == 'warn')
        print('\nИтог:')
        if failed:
            print(f'[X] Найдены критические ошибки: {failed}. Исправьте их и запустите проверку снова.')
        elif warned:
            print(f'[✓] Критических ошибок нет. Предупреждения: {warned}.')
        else:
            print('[✓] Всё готово к запуску.')
        print('')
        return failed == 0


def load_env(path=ENV_PATH):
    loaded = {}
    if not path.exists():
        return loaded
    with path.open('r', encoding='utf-8') as file:
        for raw in file:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
            loaded[key] = value
    return loaded


def check_python(report):
    version = sys.version_info
    if version >= (3, 8):
        report.ok('Python', f'{sys.version.split()[0]}')
    else:
        report.fail('Python', f'Нужен Python 3.8+, сейчас {sys.version.split()[0]}')


def check_packages(report):
    for package_name, import_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(import_name.lower() if import_name == 'Flask' else import_name.lower())
            version = metadata.version(package_name)
            report.ok(f'Python-библиотека {package_name}', f'установлена версия {version}')
        except Exception as error:
            report.fail(f'Python-библиотека {package_name}', f'не найдена или не импортируется: {error}')


def check_env(report):
    loaded = load_env()
    if ENV_PATH.exists():
        report.ok('.env', f'файл найден, загружено переменных: {len(loaded)}')
    else:
        detail = 'Создайте файл командой: cp .env.example .env'
        if not ENV_EXAMPLE_PATH.exists():
            detail += ' (.env.example тоже не найден)'
        report.fail('.env', detail)

    for key, description in REQUIRED_ENV.items():
        value = os.environ.get(key)
        if not value:
            report.fail(f'.env: {key}', f'не задано ({description})')
            continue
        if key == 'SESSION_SECRET' and (value == 'change-me-in-production' or 'change-me' in value or len(value) < 24):
            report.warn(f'.env: {key}', 'значение загружено, но лучше заменить на случайную строку 32+ символа')
        elif key == 'PORT':
            try:
                port = int(value)
                if port == 5005:
                    report.ok(f'.env: {key}', '5005')
                else:
                    report.warn(f'.env: {key}', f'сейчас {port}; для Termux рекомендуется 5005')
            except ValueError:
                report.fail(f'.env: {key}', f'должен быть числом, сейчас: {value}')
        else:
            shown = value if key != 'SESSION_SECRET' else f'{len(value)} символов'
            report.ok(f'.env: {key}', shown)


def database_path():
    return Path(os.environ.get('DATABASE_PATH', 'database.db')).expanduser()


def check_sqlite(report):
    try:
        os.chdir(ROOT)
        from freeapi.database import SCHEMA_SQL
        path = database_path()
        if not path.is_absolute():
            path = ROOT / path
        with sqlite3.connect(path) as conn:
            conn.executescript(SCHEMA_SQL)
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if path.exists() and tables:
            report.ok('SQLite database.db', f'доступна: {path.name}, таблиц: {len(tables)}')
        else:
            report.fail('SQLite database.db', 'файл или таблицы не найдены после инициализации')
    except Exception as error:
        report.fail('SQLite database.db', f'ошибка доступа или инициализации: {error}')


def check_flask(report):
    try:
        from freeapi.app import create_app
        app = create_app()
        client = app.test_client()
        response = client.get('/api/healthz')
        if response.status_code == 200:
            report.ok('Flask health-check', '/api/healthz отвечает 200')
        else:
            report.fail('Flask health-check', f'/api/healthz вернул HTTP {response.status_code}')
    except Exception as error:
        report.fail('Flask health-check', f'приложение не стартует: {error}')


def check_port(report):
    port_raw = os.environ.get('PORT', '5005')
    try:
        port = int(port_raw)
    except ValueError:
        report.fail('Порт Flask', f'PORT должен быть числом, сейчас: {port_raw}')
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    try:
        result = sock.connect_ex(('127.0.0.1', port))
    finally:
        sock.close()

    if result == 0:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/healthz', timeout=3) as response:
                if response.status == 200:
                    report.ok(f'Порт {port}', 'сервер уже запущен и /api/healthz доступен')
                else:
                    report.warn(f'Порт {port}', f'порт занят, HTTP статус {response.status}')
        except Exception as error:
            report.warn(f'Порт {port}', f'порт занят, но Flask health-check недоступен: {error}')
    else:
        report.ok(f'Порт {port}', 'свободен, Flask сможет запуститься')


async def telegram_ping():
    import telethon
    start = time.monotonic()
    reader, writer = await asyncio.wait_for(asyncio.open_connection('149.154.167.50', 443), timeout=6)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return telethon.__version__, int((time.monotonic() - start) * 1000)


def check_telegram(report):
    try:
        version, ms = asyncio.run(telegram_ping())
        report.ok('Telegram / Telethon ping', f'Telethon {version}, Telegram DC доступен за {ms} мс')
    except Exception as error:
        report.fail('Telegram / Telethon ping', f'нет соединения с Telegram DC или Telethon не работает: {error}')


def main():
    report = CheckReport()
    check_python(report)
    check_packages(report)
    check_env(report)
    check_sqlite(report)
    check_flask(report)
    check_port(report)
    check_telegram(report)
    ok = report.print()
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())