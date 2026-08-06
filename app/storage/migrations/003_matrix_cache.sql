-- 구간 좌석맵 캐시 (PLAN.md 5절 '매트릭스 병합' 5, D-17).
--
-- **화면 트래픽 전용이다.** 새로고침 연타가 코레일 재호출로 이어지지 않게 하는 것이
-- 유일한 목적이며, **스케줄러는 이 캐시를 우회하고 항상 실조회한다** — 알림은 상태
-- 변화에만 발송되므로(원칙 6) 캐시된 값으로 판정하면 변화를 통째로 놓친다.
--
-- 캐시 키는 (train_no, date, frm, to) — PLAN이 못박은 그대로다. 조회 범위가 다르면
-- 다른 항목이 되도록 **인접 구간 단위**로 캐싱한다 (매트릭스 통째로가 아니라).
-- 범위가 겹치는 두 조회가 서로의 캐시를 재사용할 수 있는 것이 이 키의 이점이다.

CREATE TABLE IF NOT EXISTS matrix_cache (
    train_no   TEXT NOT NULL,
    date       TEXT NOT NULL,   -- 열차 운행일 (YYYY-MM-DD)
    frm        TEXT NOT NULL,
    to_station TEXT NOT NULL,   -- 'to'는 SQL 예약어라 컬럼명을 바꿨다
    payload    TEXT NOT NULL,   -- SeatMap JSON
    fetched_at TEXT NOT NULL,   -- KST aware ISO8601. TTL 판정 기준
    PRIMARY KEY (train_no, date, frm, to_station)
);

-- 만료 항목 청소용 (하루치 데이터라 규모는 작지만 스캔 키를 하나 준다)
CREATE INDEX IF NOT EXISTS idx_matrix_cache_fetched ON matrix_cache(fetched_at);
