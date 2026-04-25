"""
CloudflareManager — простой менеджер cloudflared-тоннеля.

Возможности:
 - Запуск/остановка cloudflared процесса
 - Извлечение URL тоннеля из stdout
 - Вызов callback on_url(url) при получении новой ссылки
 - Graceful shutdown (stop() безопасно завершает процесс)

ВАЖНО: проверка интернета и авто-перезапуск при «обрыве» намеренно
удалены. На слабом мобильном интернете пинг 8.8.8.8 регулярно
ложно срабатывал и убивал рабочий тоннель. cloudflared сам умеет
держать соединение и переподключаться при кратковременных потерях.
"""
import re
import subprocess
import threading
import logging
from typing import Callable, Optional

logger = logging.getLogger('freeapi')

_CF_URL_RE = re.compile(r'https://[a-z0-9\-]+\.trycloudflare\.com')


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
    #  Public API                                                        #
    # ------------------------------------------------------------------ #

    def start(self):
        """Запустить тоннель в фоне. Не блокирует вызывающий поток."""
        t = threading.Thread(target=self._run_once, daemon=True, name='cf-runner')
        t.start()
        logger.info('[Cloudflare] Менеджер запущен (порт %s)', self._port)

    def stop(self):
        """Graceful shutdown: завершить процесс cloudflared."""
        logger.info('[Cloudflare] Получен сигнал остановки...')
        self._stop_event.set()
        self._kill_proc()
        logger.info('[Cloudflare] Менеджер остановлен')

    @property
    def current_url(self) -> Optional[str]:
        return self._current_url

    # ------------------------------------------------------------------ #
    #  Internal                                                          #
    # ------------------------------------------------------------------ #

    def _run_once(self):
        """Однократный запуск тоннеля. Без авто-рестарта по сети."""
        if self._stop_event.is_set():
            return
        self._start_proc()

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
