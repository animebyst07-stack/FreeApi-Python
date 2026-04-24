import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from freeapi.config import DATABASE_PATH
from freeapi.log_codes import LOG_CODES
from freeapi.models import AI_MODELS

logger = logging.getLogger('freeapi')

_lock = threading.RLock()

MSK = timezone(timedelta(hours=3))

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), 'migrations')


def msk_now():
    return datetime.now(MSK).strftime('%Y-%m-%d %H:%M:%S')


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def db():
    with _lock:
        conn = get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _list_migration_files():
    if not os.path.isdir(MIGRATIONS_DIR):
        return []
    files = [f for f in os.listdir(MIGRATIONS_DIR) if f.endswith('.sql')]
    files.sort()
    return files


def _column_exists(conn, table, column):
    """Проверить наличие колонки в таблице через PRAGMA table_info."""
    rows = conn.execute(f'PRAGMA table_info({table})').fetchall()
    return any(r['name'] == column for r in rows)


def _table_exists(conn, table):
    """Проверить наличие таблицы."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


_ALTER_RE = re.compile(
    r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)',
    re.IGNORECASE,
)


def _apply_migration(conn, sql_text):
    """Применить SQL одной миграции.

    Стратегия:
    - Выполняем `executescript` целиком (быстро, транзакционно для DDL).
    - Единственный нюанс SQLite: ALTER TABLE ADD COLUMN не поддерживает
      IF NOT EXISTS. Поэтому перед executescript проверяем каждый
      ALTER TABLE ADD COLUMN через PRAGMA table_info. Если колонка
      уже есть — удаляем statement из текста, не спамим логами.
    - Все остальные конструкции (CREATE TABLE IF NOT EXISTS,
      CREATE INDEX IF NOT EXISTS, INSERT OR IGNORE, DELETE, CREATE TABLE
      review_likes и т.п.) уже идемпотентны сами по себе.
    """
    statements = _split_sql(sql_text)
    filtered = []
    for stmt in statements:
        m = _ALTER_RE.match(stmt.lstrip())
        if m:
            table, column = m.group(1), m.group(2)
            if _column_exists(conn, table, column):
                logger.debug('[MIGRATIONS] колонка %s.%s уже существует, пропускаем', table, column)
                continue
        filtered.append(stmt)

    if not filtered:
        return

    combined = ';\n'.join(filtered) + ';'
    conn.executescript(combined)


def _split_sql(sql_text):
    """Разбить SQL-текст на отдельные statement'ы (разделитель ';')."""
    statements = []
    buf = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('--'):
            continue
        buf.append(line)
        if stripped.endswith(';'):
            stmt = '\n'.join(buf).strip().rstrip(';').strip()
            if stmt:
                statements.append(stmt)
            buf = []
    if buf:
        tail = '\n'.join(buf).strip().rstrip(';').strip()
        if tail:
            statements.append(tail)
    return statements


def _run_migrations(conn):
    """Применить только новые миграции из MIGRATIONS_DIR.

    Логика:
    1. Создать таблицу schema_migrations, если её нет.
    2. Загрузить список уже применённых версий.
    3. Для каждого .sql файла (отсортированного по имени):
       - Если версия уже в schema_migrations → пропустить целиком (без
         единой строки в логах).
       - Иначе → применить через _apply_migration, записать версию.

    Таким образом:
    - Свежая БД: все миграции применяются последовательно, по одной.
    - Существующая БД: только новые файлы (которых ещё нет в таблице).
    - Повторный запуск: ни одна уже применённая миграция не трогается,
      логи чистые.
    """
    conn.execute(
        'CREATE TABLE IF NOT EXISTS schema_migrations('
        'version TEXT PRIMARY KEY, applied_at TEXT)'
    )
    applied = {
        r[0] for r in conn.execute('SELECT version FROM schema_migrations').fetchall()
    }

    files = _list_migration_files()
    for fname in files:
        version = os.path.splitext(fname)[0]
        if version in applied:
            continue

        path = os.path.join(MIGRATIONS_DIR, fname)
        with open(path, 'r', encoding='utf-8') as fp:
            sql_text = fp.read()

        try:
            _apply_migration(conn, sql_text)
            conn.execute(
                'INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)',
                (version, msk_now()),
            )
            logger.info('[MIGRATIONS] применена: %s', version)
        except Exception as exc:
            logger.error('[MIGRATIONS] ошибка в %s: %s', fname, exc)
            raise


def _ensure_legacy_migrations_recorded(conn):
    """Одноразовая процедура для баз данных, обновившихся с pre-0.6 версии.

    До шага 0.6 миграции прогонялись idempotent при каждом старте,
    НО в schema_migrations ничего не писалось (или писалось непоследовательно).
    Чтобы не пытаться применить уже существующие столбцы/таблицы
    как «новые», здесь проверяем: если таблица users (из 001) уже
    существует, а schema_migrations пуста → значит это старая БД,
    все известные файлы помечаем как применённые без повторного выполнения.
    """
    applied_count = conn.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]
    if applied_count > 0:
        return

    if not _table_exists(conn, 'users'):
        return

    files = _list_migration_files()
    for fname in files:
        version = os.path.splitext(fname)[0]
        conn.execute(
            'INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)',
            (version, msk_now()),
        )
    if files:
        logger.info(
            '[MIGRATIONS] старая БД обнаружена — помечено %d миграций как уже применённых '
            '(без повторного выполнения)', len(files)
        )


def _seed_reference_data(conn):
    conn.execute(
        "UPDATE setup_sessions SET status='error', error_msg='SERVER_RESTART' WHERE status='running'"
    )
    for item in LOG_CODES:
        conn.execute(
            'INSERT OR IGNORE INTO log_codes(code, category, description, solution) VALUES (?, ?, ?, ?)',
            (item['code'], item['category'], item['description'], item.get('solution')),
        )
    for model in AI_MODELS:
        conn.execute(
            "INSERT OR IGNORE INTO model_stats(model_id, stat_month, avg_response_ms, total_requests, successful_reqs) VALUES (?, date('now', 'start of month'), NULL, 0, 0)",
            (model['id'],),
        )
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('agent_enabled', '0')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('agent_key_id', '')")

    row_me = conn.execute("SELECT value FROM admin_settings WHERE key='moderator_enabled'").fetchone()
    if not row_me:
        old_enabled = conn.execute("SELECT value FROM admin_settings WHERE key='agent_enabled'").fetchone()
        old_key = conn.execute("SELECT value FROM admin_settings WHERE key='agent_key_id'").fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_enabled', ?)",
            (old_enabled[0] if old_enabled else '0',),
        )
        conn.execute(
            "INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_key_id', ?)",
            (old_key[0] if old_key else '',),
        )
    else:
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_enabled', '0')")
        conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_key_id', '')")

    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_system_prompt', '')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('moderator_model', '')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_enabled', '0')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_key_id', '')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_model', '')")
    conn.execute("INSERT OR IGNORE INTO admin_settings(key, value) VALUES ('support_system_prompt', '')")


def init_database():
    with db() as conn:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS schema_migrations('
            'version TEXT PRIMARY KEY, applied_at TEXT)'
        )
        _ensure_legacy_migrations_recorded(conn)
        _run_migrations(conn)
        _seed_reference_data(conn)
    # Чиним рассинхрон админ-роли (если ReZero зарегистрировался ПОСЛЕ
    # применения миграции 010_admins.sql).
    try:
        from freeapi.repos.admins import ensure_super_admin_seeded
        ensure_super_admin_seeded()
    except Exception as exc:
        logger.warning('[ADMINS] ensure_super_admin_seeded failed: %s', exc)


def row(row_obj):
    return None if row_obj is None else {key: row_obj[key] for key in row_obj.keys()}


def rows(row_list):
    return [row(item) for item in row_list]
