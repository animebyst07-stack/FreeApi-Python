import logging
import os
import signal
import sys
import threading
from typing import Optional

from freeapi.app import create_app
from freeapi.database import init_database
from freeapi.scheduler import start_background_tasks
from freeapi.tunnel import CloudflareManager
from freeapi.tg_notify import load_notify_config, notify_new_url, validate_token

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
logger = logging.getLogger(__name__)


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
