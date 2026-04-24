-- Блок 1.10: таблица админов вместо хардкода username == 'ReZero'.
-- ReZero сидится с is_super=1 — его нельзя разжаловать через API.
CREATE TABLE IF NOT EXISTS admins (
    user_id TEXT PRIMARY KEY,
    granted_by TEXT,
    granted_at TEXT NOT NULL,
    is_super INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_admins_super ON admins(is_super);

-- Сидинг суперадмина: если ReZero уже зарегистрирован, делаем его супером.
-- Если он зарегистрируется позже — добавится в _seed_reference_data.
INSERT OR IGNORE INTO admins(user_id, granted_by, granted_at, is_super)
SELECT id, NULL, datetime('now', 'localtime', '+3 hours'), 1
  FROM users WHERE username = 'ReZero';
