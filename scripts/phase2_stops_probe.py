"""Phase 2 항목 A 검증 — `get_stops` 소스 후보 실측 (일회성, app/ 코드와 무관).

**대상: 한국철도공사_열차운행정보 (data.go.kr 15125762)**
서비스 URL `https://apis.data.go.kr/B551457/run/v2`

닫아야 할 미검증 2가지:
  Q1. **열차번호가 요청 필터인가** — 아니면 역 기준 조회라 클라이언트 필터링이 필요한가
  Q2. **보유 기간** — '여객열차 운행정보'(정차역 상세)를 *오늘/내일* 열차에 대해 조회할 수 있는가
      (포털 설명상 "3개월 전 ~ 전일"로 읽힌다. 사실이면 train_stop 캐시 설계로 간다)

여기는 **코레일 안티봇 표면이 아니다** — data.go.kr 공개 API이고 코레일 자격증명을 쓰지 않는다.
그래도 호출은 최소로 유지한다 (개발계정 트래픽 10,000건/일).

실행:
    uv run python scripts/phase2_stops_probe.py

준비: data.go.kr에서 '한국철도공사_열차운행정보' 활용신청 후 발급된 **일반 인증키(Decoding)** 를
`.env`에 넣는다:
    DATA_GO_KR_SERVICE_KEY=...

원시 응답은 `scripts/phase2_results/`에 저장한다 (gitignore 대상).
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE = "https://apis.data.go.kr/B551457/run/v2"
ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "scripts" / "phase2_results"
TIMEOUT = 20

# 포털 문서가 JS 렌더링이라 웹에서 오퍼레이션·파라미터 이름을 확인하지 못했다.
# 확인된 것: `/codes2` (코드정보). 나머지는 코레일 샘플 팝업 경로
# (openapis.korail.com/samples/public/run/travelerTrainRunInfo)에서 유추한 후보다.
# 포털 '상세기능' 화면에서 실제 이름을 확인하면 이 목록만 고치면 된다.
OPERATION_CANDIDATES = [
    "codes2",
    "travelerTrainRunInfo",
    "travelerTrainRunPlan",
    "getTravelerTrainRunInfo",
    "getTravelerTrainRunPlan",
    "trainRunInfo",
    "trainRunPlan",
    "info",
    "plan",
]

# 날짜/열차번호 파라미터 이름도 미확인 — 후보를 순서대로 시도한다.
DATE_PARAM_CANDIDATES = ["runDt", "runDate", "operationDate", "opDt", "date"]
TRAIN_PARAM_CANDIDATES = ["trainNo", "trnNo", "trainNumber", "trnn"]

# 실측에 쓸 열차 — Phase 0에서 쓴 무궁화호 1472 (천안→수원→영등포)
SAMPLE_TRAIN_NO = "1472"


def load_service_key() -> str:
    key = _from_env("DATA_GO_KR_SERVICE_KEY")
    if not key:
        sys.exit(
            "DATA_GO_KR_SERVICE_KEY 가 없다.\n"
            "  data.go.kr → '한국철도공사_열차운행정보' 활용신청 → 일반 인증키(Decoding)를\n"
            "  .env 에 DATA_GO_KR_SERVICE_KEY=... 로 넣어라."
        )
    return key


def _from_env(name: str) -> str:
    import os

    if value := os.environ.get(name):
        return value.strip()
    env_file = ROOT / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def mask(text: str, key: str) -> str:
    """서비스 키가 로그·저장 파일에 남지 않게 가린다."""
    out = text
    raw = urllib.parse.unquote(key)  # Encoding/Decoding 두 형태 모두 가린다
    forms = {key, raw, urllib.parse.quote(raw, safe=""), urllib.parse.quote_plus(raw)}
    for form in forms:
        if form:
            out = out.replace(form, "***SERVICE_KEY***")
    return out


def normalize_key(key: str) -> str:
    """Encoding/Decoding 어느 형태로 붙여넣어도 동작하게 만든다.

    data.go.kr는 인증키를 두 형태로 준다. Encoding 키(`%2B`/`%2F`/`%3D` 포함)를
    그대로 `urlencode`에 넘기면 `%`가 다시 인코딩돼(`%252B`) 인증이 실패한다.
    한 번 풀어두면 `urlencode`가 정확히 한 번만 인코딩한다 — 두 형태가 같은 곳으로 수렴한다.
    """
    return urllib.parse.unquote(key)


def call(op: str, params: dict[str, str], key: str) -> tuple[int, str]:
    query = urllib.parse.urlencode(
        {"serviceKey": normalize_key(key), "_type": "json", **params}
    )
    url = f"{BASE}/{op}?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 — 진단 스크립트라 전부 삼키고 보고한다
        return 0, f"{type(e).__name__}: {e}"


def summarize(body: str, limit: int = 700) -> str:
    body = body.strip()
    try:
        parsed = json.loads(body)
        return json.dumps(parsed, ensure_ascii=False, indent=2)[:limit]
    except json.JSONDecodeError:
        return body[:limit]


def looks_alive(status: int, body: str) -> bool:
    """404/미등록 오퍼레이션이 아니라 '살아 있는' 응답인지."""
    if status == 0:
        return False
    dead_markers = (
        "NOT_FOUND",
        "SERVICE_KEY_IS_NOT_REGISTERED",
        "등록되지 않은",
        "HTTP Status 404",
        "no such",
    )
    upper = body.upper()
    return not any(m.upper() in upper for m in dead_markers)


def step(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> None:
    key = load_service_key()
    RESULTS.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []

    def record(name: str, op: str, params: dict[str, str], status: int, body: str) -> None:
        safe = mask(body, key)
        log.append(
            {"name": name, "op": op, "params": params, "status": status, "body": safe[:4000]}
        )
        print(f"  [{status}] {op} {params or '(no params)'}")
        print("  " + summarize(safe).replace("\n", "\n  "))

    # ── STEP 1. 살아 있는 오퍼레이션 찾기 ────────────────────────────────
    step("STEP 1 — 오퍼레이션 탐색 (파라미터 없이 호출해 에러 메시지로 판별)")
    print("  data.go.kr는 필수 파라미터 누락 시 그 이름을 알려주는 편이다. 그걸 노린다.")
    alive: list[str] = []
    for op in OPERATION_CANDIDATES:
        status, body = call(op, {}, key)
        record(f"probe:{op}", op, {}, status, body)
        if looks_alive(status, body):
            alive.append(op)

    if not alive:
        print(
            "\n  살아 있는 오퍼레이션이 없다. 키가 아직 승인 대기이거나(보통 즉시~1시간),\n"
            "  오퍼레이션 이름 후보가 전부 틀렸다.\n"
            "  → 포털 '상세기능' 화면에서 실제 이름을 확인하고 OPERATION_CANDIDATES를 고쳐라."
        )

    print(f"\n  살아 있는 후보: {alive or '없음'}")

    # ── STEP 2. Q1 — 열차번호가 요청 필터인가 ────────────────────────────
    step("STEP 2 — Q1: 열차번호로 필터되는가 (내일 날짜 기준)")
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y%m%d")
    q1_hits: list[tuple[str, str, str]] = []
    for op in alive:
        if op == "codes2":
            continue
        for dparam in DATE_PARAM_CANDIDATES:
            for tparam in TRAIN_PARAM_CANDIDATES:
                params = {dparam: tomorrow, tparam: SAMPLE_TRAIN_NO, "numOfRows": "50"}
                status, body = call(op, params, key)
                if looks_alive(status, body) and SAMPLE_TRAIN_NO in body:
                    record(f"q1:{op}:{dparam}:{tparam}", op, params, status, body)
                    q1_hits.append((op, dparam, tparam))
                    break
            if q1_hits and q1_hits[-1][0] == op:
                break

    print(f"\n  열차번호 필터가 먹힌 조합: {q1_hits or '없음'}")

    # ── STEP 3. Q2 — 보유 기간 (어제/오늘/내일) ──────────────────────────
    step("STEP 3 — Q2: 오늘·내일 열차의 정차역을 조회할 수 있는가")
    if not q1_hits:
        print("  STEP 2에서 유효 조합을 못 찾아 건너뛴다. STEP 1·2 출력을 보고 후보를 고쳐라.")
    for op, dparam, tparam in q1_hits:
        for label, d in [
            ("어제", date.today() - timedelta(days=1)),
            ("오늘", date.today()),
            ("내일", date.today() + timedelta(days=1)),
            ("+7일", date.today() + timedelta(days=7)),
        ]:
            params = {dparam: d.strftime("%Y%m%d"), tparam: SAMPLE_TRAIN_NO, "numOfRows": "50"}
            status, body = call(op, params, key)
            print(f"\n  ── {label} ({d}) ──")
            record(f"q2:{op}:{label}", op, params, status, body)

    # ── STEP 4. 코드정보 (역코드 ↔ 역명) ─────────────────────────────────
    step("STEP 4 — 코드정보 API: 역코드 ↔ 역명 매핑이 나오는가")
    if "codes2" in alive:
        for params in ({"numOfRows": "20"}, {"numOfRows": "20", "codeType": "station"}):
            status, body = call("codes2", params, key)
            record("codes2", "codes2", params, status, body)
    else:
        print("  codes2가 STEP 1에서 살아있지 않았다.")

    out = RESULTS / "stops_probe.json"
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    step("요약 — 이 두 줄을 나에게 알려주면 된다")
    print(f"  Q1 열차번호 필터: {'가능 ' + str(q1_hits) if q1_hits else '불가/미확인'}")
    print("  Q2 오늘·내일 조회: STEP 3 출력의 각 날짜별 건수를 확인")
    print(f"\n  원시 응답: {out} (서비스 키는 마스킹됨)")
    print(f"  총 호출 수: {len(log)}")


if __name__ == "__main__":
    main()
