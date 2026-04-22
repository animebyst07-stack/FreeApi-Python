"""Auto-generated repos module (см. план рефакторинга, шаг 0.3).
Бизнес-логика не менялась — функции перенесены из freeapi/repositories.py как есть.
"""
from freeapi.database import db, row, rows, msk_now
from freeapi.security import uuid4


def get_global_stats():
    with db() as conn:
        users = conn.execute('SELECT COUNT(*) AS c FROM users').fetchone()['c']
        total = conn.execute('SELECT COUNT(*) AS c FROM requests').fetchone()['c']
        today = conn.execute("SELECT COUNT(*) AS c FROM requests WHERE request_at >= date('now')").fetchone()['c']
        return {'users': int(users), 'totalRequests': int(total), 'todayRequests': int(today)}


def get_model_stats():
    with db() as conn:
        return rows(conn.execute("SELECT * FROM model_stats WHERE stat_month = date('now', 'start of month')").fetchall())


def update_model_stats(model_id, response_ms, ok=True):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO model_stats(model_id, stat_month, avg_response_ms, total_requests, successful_reqs) VALUES (?, date('now', 'start of month'), NULL, 0, 0)", (model_id,))
        if ok:
            conn.execute("UPDATE model_stats SET total_requests = total_requests + 1, successful_reqs = successful_reqs + 1, avg_response_ms = CASE WHEN avg_response_ms IS NULL THEN ? ELSE CAST(((avg_response_ms * successful_reqs) + ?) / (successful_reqs + 1) AS INTEGER) END WHERE model_id = ? AND stat_month = date('now', 'start of month')", (response_ms, response_ms, model_id))
        else:
            conn.execute("UPDATE model_stats SET total_requests = total_requests + 1 WHERE model_id = ? AND stat_month = date('now', 'start of month')", (model_id,))


def get_log_codes():
    with db() as conn:
        return rows(conn.execute('SELECT * FROM log_codes ORDER BY category, code').fetchall())


# ─────────── REVIEWS ───────────
