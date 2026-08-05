-- 역 마스터 (PLAN.md 11절 Phase 2, D-25).
--
-- 용도 2개:
--   ① 역 선택 드롭다운 소스 (`GET /api/stations`) — 역 이름을 타이핑시키면 오타가 곧 404다
--   ② GPS 보정 좌표 (domain/geo.py 선분 투영, D-13)
--
-- **소스는 공공데이터 CSV다** (scripts/load_stations.py로 적재). 정적 참조 데이터를
-- 런타임에 API로 긁을 이유가 없다 — 쿼터·네트워크 의존이 사라지고, 열차 안에서
-- 네트워크가 나빠도 역 목록은 항상 뜬다.
--
-- 원칙 1(역 하드코딩 금지)과의 관계: 목록이 **데이터에서 온다**는 점은 그대로다.
-- 코드에는 역 이름이 없고 도메인 로직은 여전히 "수원"이라는 단어를 모른다.
--
-- ★ PK가 `code`가 아니라 `name`인 이유:
-- 세 소스(공공데이터 운행정보 / 좌표 CSV / korail2)의 역코드 체계가 서로 다르다.
-- 좌표 CSV에는 역코드 컬럼이 아예 없고, korail2는 자체 코드를 쓴다.
-- **세 소스를 잇는 유일하게 확실한 축이 역명**이므로 그것을 키로 삼는다.
-- code는 있으면 담아두는 부가 정보다 (공공데이터 7자리, 예: 3900023).

CREATE TABLE IF NOT EXISTS station (
    name       TEXT PRIMARY KEY,   -- 조인 키. 정규화 후 저장 (앞뒤 공백 제거, '~역' 접미 통일)
    code       TEXT,               -- 공공데이터 역코드 (없을 수 있다)
    lat        REAL,               -- 위도. 없으면 NULL → GPS 보정 대상에서 제외
    lng        REAL,               -- 경도
    line       TEXT,               -- 주운행선명 등 참고용
    -- 여객역으로 **확인된** 행만 1. 드롭다운(D-25)은 이것만 보여준다.
    -- 역코드 CSV(철도운영정보_역코드)는 1,255행인데 그중 상당수가 '본청'·'서지청'·
    -- '구로열차소'·'송도교' 같은 **운영 지점**이다. 그 파일만으로는 여객역과 구분할
    -- 방법이 없으므로 코드 사전으로만 쓰고 usable=0으로 둔다.
    -- 1이 되는 경로는 두 가지, 둘 다 데이터 근거가 있다 (원칙 1):
    --   ① 좌표를 얻었다 — '역 위치 정보'(15127532)는 정의상 간선 여객역 202개다
    --   ② 시각표에 정차역으로 등장했다 — 열차가 서는 곳이면 여객역이다
    usable     INTEGER NOT NULL DEFAULT 0,
    source     TEXT NOT NULL,      -- 어느 파일에서 왔는지 (재적재·감사용)
    updated_at TEXT NOT NULL       -- KST aware ISO8601
);

-- 좌표가 있는 역만 GPS 투영 대상이다 (D-13)
CREATE INDEX IF NOT EXISTS idx_station_coords ON station(lat, lng);
CREATE INDEX IF NOT EXISTS idx_station_code ON station(code);
CREATE INDEX IF NOT EXISTS idx_station_usable ON station(usable);
