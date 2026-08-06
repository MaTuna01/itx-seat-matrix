-- 열차별 정차역 캐시 (Phase 2 항목 A, D-29).
--
-- Phase 0 항목 5(NO) 해결: 열차번호로 전체 정차역을 주는 코레일 엔드포인트는 없지만,
-- 공공데이터 '여객열차 운행정보'가 실적(과거) 데이터로 정차역+시각+순번을 준다.
-- 최근 운행일(대개 D-1) 데이터를 열차번호 단위로 캐시해 **템플릿**으로 재사용한다 —
-- 정차 "순서"는 시각표 사실이라 요일에 걸쳐 안정적임을 실측 확인했다(같은 열차가
-- 화·월·일·토 4일 동일 패턴, D-29 실측 로그).
--
-- 절대 시각이 아니라 **시각(time-of-day) + 날짜 오프셋**으로 저장한다 — 조회 시점의
-- 실제 운행일과 캐시 소스 운행일이 다르므로, 저장된 절대 날짜를 그대로 쓰면 안 된다.
-- day_offset은 자정을 넘는 운행(예: 심야 열차)에서 시발일 대비 며칠째인지를 남긴다.

CREATE TABLE IF NOT EXISTS train_stop (
    train_no          TEXT NOT NULL,   -- 정규화됨 (선행 0 제거)
    seq               INTEGER NOT NULL,  -- 운행순번 (trn_run_sn). 정차 순서
    station_name      TEXT NOT NULL,   -- 정규화된 역명 (station.name과 조인 가능)
    station_code      TEXT,            -- 공공데이터 역코드
    stop_type         TEXT NOT NULL,   -- '시발' | '여객승하차' | '종착' 등 원문 그대로
    -- 도착시각. 시발역은 도착 기록이 없어 NULL → get_stops()가 출발시각으로 대신한다
    -- (열차가 그 시각에 그 역에 '있다'는 사실은 동일하다).
    arrival_day_offset  INTEGER,
    arrival_time        TEXT,          -- 'HH:MM:SS'
    -- 출발시각. 종착역은 출발이 없어 NULL.
    departure_day_offset INTEGER,
    departure_time       TEXT,
    source_run_ymd    TEXT NOT NULL,   -- 이 정차 정보를 관측한 실제 운행일 (신선도 표시용)
    refreshed_at      TEXT NOT NULL,   -- KST aware ISO8601
    PRIMARY KEY (train_no, seq)
);

CREATE INDEX IF NOT EXISTS idx_train_stop_refreshed ON train_stop(refreshed_at);
