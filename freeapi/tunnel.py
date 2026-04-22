"""
CloudflareManager — полностью автономный менеджер cloudflared-тоннеля.

Возможности:
 - Запуск/остановка/перезапуск cloudflared процесса
 - Фоновый чекер интернета (пинг TCP до 8.8.8.8:53)
 - Авто-переподключение при обрыве: ждёт возврата интернета,
   убивает старый процесс, запускает новый, извлекает URL
 - Вызывает callback on_url(url) при получении новой ссылки
 - Graceful shutdown (stop() безопасно завершает всё)
"""
import re
import socket
import subprocess
import threading
import time
import logging
from typing import Callable, Optional, Any

logger = logging.getLogger('freeapi')

_CF_URL_RE = re.compile(r'https://[a-z0-9\-]+\.trycloudflare\.com')

_INTERNET_CHECK_HOST = '8.8.8.8'
_INTERNET_CHECK_PORT = 53
_INTERNET_CHECK_TIMEOUT = 3.0
_INTERNET_POLL_INTERVAL = 10
_RECONNECT_POLL_INTERVAL = 5


def _has_internet() -> bool:
    try:
        socket.setdefaulttimeout(_INTERNET_CHECK_TIMEOUT)
        with socket.create_connection((_INTERNET_CHECK_HOST, _INTERNET_CHECK_PORT), timeout=_INTERNET_CHECK_TIMEOUT):
            return True
    except OSError:
        return False


def _print_tunnel_url(url: str):
    logger.info('[Tunnel] Cloudflare Tunnel активен: %s', url)


class CloudflareManager:
    def __init__(self, port: int, on_url: Optional[Callable[[str], None]] = None):
        self._port = port
        self._on_url = on_url
        self._proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._current_url: Optional[str] = None

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self):
        """Запустить тоннель и мониторинг. Не блокирует вызывающий поток."""
        t = threading.Thread(target=self._monitor_loop, daemon=True, name='cf-monitor')
        t.start()
        logger.info('[Cloudflare] Менеджер запущен (порт %s)', self._port)

    def stop(self):
        """Graceful shutdown: завершить мониторинг и процесс cloudflared."""
        logger.info('[Cloudflare] Получен сигнал остановки...')
        self._stop_event.set()
        self._kill_proc()
        logger.info('[Cloudflare] Менеджер остановлен')

    @property
    def current_url(self) -> Optional[str]:
        return self._current_url

    # ------------------------------------------------------------------ #
    #  Internal                                                             #
    # ------------------------------------------------------------------ #

    def _start_proc(self) -> Optional[str]:
        """Запустить cloudflared, вернуть найденный URL или None."""
        try:
            proc = subprocess.Popen(
                ['cloudflared', 'tunnel', '--url', f'http://localhost:{self._port}'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            with self._proc_lock:
                self._proc = proc

            url = None
            for line in proc.stdout:
                if self._stop_event.is_set():
                    break
                m = _CF_URL_RE.search(line)
                if m:
                    url = m.group(0)
                    break

            if url:
                self._current_url = url
                _print_tunnel_url(url)
                if self._on_url:
                    try:
                        self._on_url(url)
                    except Exception as exc:
                        logger.error('[Cloudflare] on_url callback ошибка: %s', exc)

            threading.Thread(target=self._drain_stdout, args=(proc,), daemon=True).start()
            return url

        except FileNotFoundError:
            logger.warning('[Cloudflare] cloudflared не найден — тоннель не запущен')
            return None
        except Exception as exc:
            logger.error('[Cloudflare] Ошибка запуска: %s', exc)
            return None

    def _drain_stdout(self, proc: subprocess.Popen):
        """Дочитываем stdout, чтобы процесс не завис на полном буфере."""
        try:
            for _ in proc.stdout:
                pass
        except Exception:
            pass

    def _kill_proc(self):
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            logger.info('[Cloudflare] Процесс завершён')
        except Exception as exc:
            logger.warning('[Cloudflare] Ошибка при завершении процесса: %s', exc)

    def _proc_alive(self) -> bool:
        with self._proc_lock:
            return self._proc is not None and self._proc.poll() is None

    def _monitor_loop(self):
        """
        Основной цикл:
        1. Ждёт интернета при старте.
        2. Запускает тоннель.
        3. Следит за соединением; при потере — ждёт восстановления
           и перезапускает тоннель.
        """
        while not self._stop_event.is_set():
            if not _has_internet():
                logger.warning('[Cloudflare] Нет интернета, ожидаю...')
                self._wait_internet()
                if self._stop_event.is_set():
                    break

            self._start_proc()
            if self._stop_event.is_set():
                break

            while not self._stop_event.is_set():
                time.sleep(_INTERNET_POLL_INTERVAL)
                if not _has_internet():
                    logger.warning('[Cloudflare] Интернет пропал, останавливаю тоннель...')
                    self._kill_proc()
                    self._wait_internet()
                    if self._stop_event.is_set():
                        break
                    logger.info('[Cloudflare] Интернет восстановлен, перезапускаю тоннель...')
                    break
                if not self._proc_alive():
                    logger.warning('[Cloudflare] Процесс упал, перезапускаю...')
                    break

        self._kill_proc()

    def _wait_internet(self):
        """Блокирует пока нет интернета (или до stop_event)."""
        while not self._stop_event.is_set():
            time.sleep(_RECONNECT_POLL_INTERVAL)
            if _has_internet():
                return
