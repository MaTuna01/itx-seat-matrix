-- Phase 1 스키마 (PLAN.md 5절 DB 스키마, D-10/D-15/D-16/D-19).
-- 원칙 3: 사용자 귀속 데이터는 코드가 아니라 DB에. 모든 도메인 테이블에 user_id FK를
-- **처음부터** 심는다 — 나중에 끼우면 엔드포인트·스키마·쿼리를 전부 고쳐야 한다.
--
-- station / push_device / matrix_cache는 각각 Phase 2·3에서 추가한다.
-- 모든 datetime은 KST aware ISO8601 문자열로 저장한다 (예: 2026-08-05T08:14:02+09:00).

CREATE TABLE IF NOT EXISTS user (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    display_name        TEXT NOT NULL,
    korail_id           TEXT,             -- Phase 0 결과: 로그인 필수 + 본계정 확정 (D-22)
    korail_pw_enc       TEXT,             -- Fernet 암호화. API 응답에 절대 노출 금지
    discord_webhook_enc TEXT,             -- NULL이면 미연동 (Phase 3)
    discord_enabled     INTEGER NOT NULL DEFAULT 0,  -- 연동해도 켜야만 발송 (opt-in 2단계)
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);

CREATE TABLE IF NOT EXISTS preset (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    from_station     TEXT NOT NULL,
    to_station       TEXT NOT NULL,
    usual_train_nos  TEXT NOT NULL DEFAULT '[]',        -- JSON
    poll_offsets_min TEXT NOT NULL DEFAULT '[10, 4]',   -- JSON, 정차역 도착 n분 전 (D-12)
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_preset_user ON preset(user_id);

CREATE TABLE IF NOT EXISTS subscription (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    train_no            TEXT NOT NULL,
    date                TEXT NOT NULL,      -- 열차 운행일 (YYYY-MM-DD)
    board_at            TEXT NOT NULL,
    alight_at           TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('STANDING', 'SEATED')),  -- D-15
    my_car              INTEGER,            -- SEATED일 때만 NOT NULL (앱 레벨 422 검증)
    my_seat_no          TEXT,
    active              INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    last_verdict_hash   TEXT,               -- 원칙 6 변화 감지. ★스케줄러만 기록 (D-13/D-17)
    last_cells_snapshot TEXT,               -- JSON. 내 좌석 셀 스냅샷, SEAT_EXTENDED 전이용 (D-16)
    next_poll_at        TEXT,               -- 다음 폴 포인트. 재시작 내구성의 핵심 (D-19)
    last_notified_at    TEXT,
    fail_count          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_subscription_user ON subscription(user_id);
CREATE INDEX IF NOT EXISTS idx_subscription_poll ON subscription(active, next_poll_at);
