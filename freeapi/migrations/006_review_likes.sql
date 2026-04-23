-- Лайки отзывов.
CREATE TABLE IF NOT EXISTS review_likes (
    review_id TEXT NOT NULL,
    user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    value     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(review_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_review_likes_review ON review_likes(review_id);
