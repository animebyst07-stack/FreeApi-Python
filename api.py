import atexit
import logging
import os
import signal
import sys
import threading
from collections import deque
from typing import Optional

from freeapi.app import create_app
from freeapi.database import init_database
from freeapi.scheduler import start_background_tasks
from freeapi.tunnel import CloudflareManager
from freeapi.tg_notify import load_notify_config, notify_new_url, validate_token

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 0.5.13: in-memory ring-buffer для всех логов + сохранение в файл при остановке
# Целевой путь — Android-хранилище (Termux). Если каталога нет / нет прав —
# fallback в `./logi.txt` рядом с api.py.
# ─────────────────────────────────────────────────────────────────────────────
LOG_DUMP_PATH = '/storage/emulated/0/Цхранилище/Мусор/logi.txt'
_LOG_BUFFER_MAX = 50000  # храним последние 50k записей в памяти


class _RingMemoryHandler(logging.Handler):
    """Хранит отформатированные строки логов в кольцевом буфере."""

    def __init__(self, capacity: int):
        super().__init__(level=logging.DEBUG)
        self._buf: deque = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.setFormatter(
            logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
        )

    def emit(self, record: logging.LogRecord):
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()
        with self._lock:
            self._buf.append(line)

    def snapshot(self):
        with self._lock:
            return list(self._buf)


_log_ring = _RingMemoryHandler(_LOG_BUFFER_MAX)
# Подвешиваем на root, чтобы захватывать всё (freeapi, werkzeug, __main__, ...)
logging.getLogger().addHandler(_log_ring)
logging.getLogger().setLevel(logging.INFO)


def _dump_logs_to_file() -> Optional[str]:
    """
    При остановке — пишет накопленные логи в LOG_DUMP_PATH.
    Если файл существует, перезаписывается. Возвращает фактический путь
    или None при ошибке.
    """
    lines = _log_ring.snapshot()
    if not lines:
        return None
    payload = '\n'.join(lines) + '\n'

    candidates = [LOG_DUMP_PATH, os.path.join(os.getcwd(), 'logi.txt')]
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            # Удаляем старый, если существует — гарантируем "новый файл".
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            with open(path, 'w', encoding='utf-8') as f:
                f.write(payload)
            logger.info('[Logs] Сохранено %d строк в %s', len(lines), path)
            return path
        except Exception as e:
            logger.warning('[Logs] Не удалось писать в %s: %s', path, e)
    return None


# Подстраховка на случай нештатного выхода без срабатывания GracefulShutdown.
_atexit_done = threading.Event()


def _atexit_dump():
    if _atexit_done.is_set():
        return
    _atexit_done.set()
    _dump_logs_to_file()


atexit.register(_atexit_dump)


def load_env(path='.env'):
    if not os.path.exists(path):
        return
    with open(path, 'r', encoding='utf-8') as file:
        for raw in file:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _warn_if_default_secret():
    secret = os.environ.get('SESSION_SECRET', '')
    if not secret or secret == 'change-me-in-production':
        logger.warning(
            '[Security] SESSION_SECRET не задан или используется значение по умолчанию! '
            'Зашифрованные данные в БД могут быть небезопасны. '
            'Задайте SESSION_SECRET в .env!'
        )


class GracefulShutdown:
    """
    Перехватывает SIGINT/SIGTERM, завершает cloudflared и сигнализирует
    главному потоку об остановке.
    """
    def __init__(self):
        self._event = threading.Event()
        self._cf_manager: Optional[CloudflareManager] = None
        signal.signal(signal.SIGINT, self._handler)
        signal.signal(signal.SIGTERM, self._handler)

    def set_cf_manager(self, manager: CloudflareManager):
        self._cf_manager = manager

    def _handler(self, sig, frame):
        logger.info('[Shutdown] Получен сигнал %s, начинаю завершение...', sig)
        if self._cf_manager:
            self._cf_manager.stop()
        # 0.5.13: дамп логов в файл (даёт юзеру полный текстовый журнал сессии)
        try:
            _dump_logs_to_file()
        except Exception as e:
            logger.warning('[Logs] dump fail: %s', e)
        self._event.set()

    def wait(self):
        self._event.wait()


if __name__ == '__main__':
    load_env()
    _warn_if_default_secret()

    shutdown = GracefulShutdown()

    init_database()
    start_background_tasks()

    # Запуск AI-агента если включён в настройках
    try:
        from freeapi import repositories as _repo
        from freeapi.agent import start_agent
        if _repo.get_admin_setting('agent_enabled', '0') == '1':
            start_agent()
            logger.info('[API] Favorite AI Agent активирован')
    except Exception as _e:
        logger.warning('[API] Не удалось запустить AI Agent: %s', _e)

    tg_token, tg_chats = load_notify_config()
    if tg_token:
        if not validate_token(tg_token):
            logger.warning('[TgNotify] Уведомления Telegram отключены из-за невалидного токена')
            tg_token = ''
            tg_chats = []

    port = int(os.environ.get('PORT', '5000'))

    def on_tunnel_url(url: str):
        if tg_token and tg_chats:
            t = threading.Thread(
                target=notify_new_url,
                args=(tg_token, tg_chats, url),
                daemon=True,
                name='tg-notify',
            )
            t.start()

    cf_manager = CloudflareManager(port=port, on_url=on_tunnel_url)
    shutdown.set_cf_manager(cf_manager)
    cf_manager.start()

    app = create_app()

    flask_thread = threading.Thread(
        target=lambda: app.run(
            host=os.environ.get('HOST', '0.0.0.0'),
            port=port,
            threaded=True,
            use_reloader=False,
        ),
        daemon=True,
        name='flask',
    )
    flask_thread.start()

    logger.info('[API] Сервер запущен на порту %s', port)

    try:
        shutdown.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info('[API] Завершение работы...')
        cf_manager.stop()
        sys.exit(0)
