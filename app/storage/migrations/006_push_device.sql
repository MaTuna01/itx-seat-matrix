-- Phase 3 — 웹푸시 기기 등록 (PLAN.md 5절 DB 스키마, 8절 채널, D-20).
--
-- 기기별 1행이다 — 폰/아이패드를 동시에 쓴다. `endpoint`가 사실상 기기 식별자이므로
-- UNIQUE를 걸어 같은 기기가 재등록될 때 행이 늘어나지 않게 한다
-- (iOS는 endpoint를 조용히 회전시키므로 회전 후에는 새 행이 맞다. 죽은 옛 행은
--  발송 시 410/404를 받아 삭제된다 — D-20).
--
-- p256dh/auth는 브라우저가 준 공개 재료다. 시크릿이 아니므로 평문으로 둔다
-- (디스코드 웹훅 URL과 달리 이것만으로는 아무 데도 발송할 수 없다).
-- 발송 권한을 쥔 VAPID **비밀키**는 DB가 아니라 env에만 있다 (D-34).

CREATE TABLE IF NOT EXISTS push_device (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    label      TEXT,             -- "아이폰" 등 사용자 메모. 없어도 동작한다
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_push_device_user ON push_device(user_id);
