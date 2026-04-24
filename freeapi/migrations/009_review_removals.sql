-- M1: Лог удалений отзывов модератором (для скользящего окна 5/5 за 7 дней).
-- Вместо одноразового бана на 7 дней при первом же удалении (старое поведение
-- agent.py _do_delete) теперь храним КАЖДОЕ удаление отдельной записью и
-- считаем счётчик за последние 7 дней. Бан накладывается только когда
-- пороговое значение (5) достигнуто.
CREATE TABLE IF NOT EXISTS review_removals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    review_id TEXT,
    reason TEXT,
    removed_by TEXT,
    removed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rr_user_time ON review_removals(user_id, removed_at);
