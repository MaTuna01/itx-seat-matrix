-- 인증 설계 갱신 (PLAN.md 6절, D-23/D-24).
-- - 로그인 유지 여부를 세션에 기록 (슬라이딩 연장 수명이 갈린다)
-- - 가입 허용을 env가 아니라 DB에 두고 관리자가 토글한다

ALTER TABLE user ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;

-- 0 = 브라우저 세션 쿠키 + 짧은 만료, 1 = 지속 쿠키 + 30일
ALTER TABLE session ADD COLUMN persistent INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS app_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT,
    updated_by INTEGER REFERENCES user(id) ON DELETE SET NULL
);

-- 기본값은 잠김. 첫 계정만 부트스트랩으로 예외 허용한다 (D-24)
INSERT OR IGNORE INTO app_setting (key, value) VALUES ('signup_enabled', 'false');

-- 기존 DB에 이미 계정이 있다면 가장 먼저 만든 계정을 관리자로 승격한다
UPDATE user SET is_admin = 1
 WHERE id = (SELECT id FROM user ORDER BY id LIMIT 1)
   AND NOT EXISTS (SELECT 1 FROM user WHERE is_admin = 1);
