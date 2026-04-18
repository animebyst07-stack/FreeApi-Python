import json
import queue
import threading
from queue import Empty

_progress = {}
_queues = {}
_pending_auth = {}
_lock = threading.RLock()


def update_progress(setup_id, **data):
    with _lock:
        current = _progress.get(setup_id, {'setupId': setup_id, 'step': 0, 'stepLabel': '', 'done': False, 'error': None})
        current.update(data)
        _progress[setup_id] = current
        for stream in _queues.get(setup_id, set()):
            stream.put(current.copy())


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
