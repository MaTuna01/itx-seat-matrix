-- 구간별 "마지막 성공 조회" 스냅샷 (→ D-57).
--
-- matrix_cache(60초 화면 캐시)와 별개다 — TTL 없음, 지난 운행일 단위로 청소한다.
-- 열차가 출발해 조회할 수 없게 된 갭 구간(지금 타고 있는 구간)을 화면에 "HH:MM 조회
-- 기준"으로 계속 보여주는 것이 유일한 목적이며 **표시 전용**이다 — 판정·알림·추천에는
-- 유입되지 않는다.
--
-- 알림 상태(last_verdict_hash/last_cells_snapshot)가 아니므로 절대규칙 5와 무관하다:
-- 스케줄러 폴과 화면 조회 **양쪽이** 기록한다. 기록 조건은 "조회 시점에 sellable했던
-- 구간의 성공한 조회" — 조회 범위가 이미 sellable 기준이고 실패는 예외로 빠지므로
-- 구조가 보장한다.

CREATE TABLE IF NOT EXISTS seat_snapshot (
    train_no   TEXT NOT NULL,
    date       TEXT NOT NULL,   -- 열차 운행일 (YYYY-MM-DD)
    frm        TEXT NOT NULL,
    to_station TEXT NOT NULL,   -- 'to'는 SQL 예약어라 컬럼명을 바꿨다 (matrix_cache와 동일)
    payload    TEXT NOT NULL,   -- SeatMap JSON
    fetched_at TEXT NOT NULL,   -- KST aware ISO8601. "HH:MM 조회" 표시의 근거
    PRIMARY KEY (train_no, date, frm, to_station)
);

-- 지난 운행일 청소용
CREATE INDEX IF NOT EXISTS idx_seat_snapshot_date ON seat_snapshot(date);
