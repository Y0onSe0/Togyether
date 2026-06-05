-- 공지 배너 테이블
CREATE TABLE IF NOT EXISTS notice_banners (
    id         SERIAL PRIMARY KEY,
    message    TEXT        NOT NULL,
    level      TEXT        NOT NULL DEFAULT 'info',  -- info | warning | danger
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
