import json
import queue
import threading
from queue import Empty

_progress = {}
_queues = {}
_pending_auth = {}
_cancel_flags = set()
_lock = threading.RLock()


def update_progress(setup_id, **data):
    with _lock:
        current = _progress.get(setup_id, {'setupId': setup_id, 'step': 0, 'stepLabel': '', 'done': False, 'error': None})
        # Защита: если setup уже финализирован (done=True) — игнорируем
        # последующие апдейты, чтобы фоновый поток не затирал результат
        # отмены (skip-to-key) повторными step=N/done=False сообщениями.
        if current.get('done') and not data.get('done'):
            return
        current.update(data)
        _progress[setup_id] = current
        for stream in _queues.get(setup_id, set()):
            stream.put(current.copy())


# ─── Cancel-механизм (см. plan.txt сессии 6, шаг S2) ─────────────────
# Frontend жмёт «Отмена настройки» → /api/tg/setup/<id>/cancel
# вызывает request_cancel(setup_id). Фоновый SetupFlow проверяет
# is_cancelled() между шагами и в долгих ожиданиях (training/wait)
# и при выставленном флаге сразу прыгает на шаг 6 (выдача ключа).
def request_cancel(setup_id):
    with _lock:
        _cancel_flags.add(setup_id)


def is_cancelled(setup_id):
    with _lock:
        return setup_id in _cancel_flags


def clear_cancel(setup_id):
    with _lock:
        _cancel_flags.discard(setup_id)


def get_progress(setup_id):
    with _lock:
        return _progress.get(setup_id)


def set_pending_auth(setup_id, data):
    with _lock:
        _pending_auth[setup_id] = data


def get_pending_auth(setup_id):
    with _lock:
        return _pending_auth.get(setup_id)


def clear_pending_auth(setup_id):
    with _lock:
        _pending_auth.pop(setup_id, None)


def event_stream(setup_id):
    stream = queue.Queue()
    with _lock:
        _queues.setdefault(setup_id, set()).add(stream)
        if setup_id in _progress:
            stream.put(_progress[setup_id].copy())
    try:
        while True:
            try:
                data = stream.get(timeout=15)
                yield 'data: ' + json.dumps(data, ensure_ascii=False) + '\n\n'
                if data.get('done'):
                    break
            except Empty:
                yield ':heartbeat\n\n'
    finally:
        with _lock:
            _queues.get(setup_id, set()).discard(stream)
