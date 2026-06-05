-- 질병관리청 보도자료 테이블
CREATE TABLE IF NOT EXISTS kdca_notices (
    id           SERIAL PRIMARY KEY,
    title        TEXT        NOT NULL,
    link         TEXT        NOT NULL UNIQUE,   -- 중복 방지
    published_at TIMESTAMPTZ,
    author       TEXT,
    description  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kdca_notices_published_at ON kdca_notices (published_at DESC);
