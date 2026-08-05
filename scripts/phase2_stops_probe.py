"""Phase 2 항목 A 검증 — `get_stops` 소스 실측 (일회성, app/ 코드와 무관).

**대상: 한국철도공사_열차운행정보 (data.go.kr 15125762)**
서비스 URL `https://apis.data.go.kr/B551457/run/v2`

## 1차 프로브에서 확정된 것

- 인증키 정상 동작 (`codes2` → resultCode 0)
- 오퍼레이션 이름은 **끝에 `2`가 붙는다**: `travelerTrainRunInfo2`, `travelerTrainRunPlan2`
  (더미 키로 열거해 확인 — 코드 12=경로 없음 / 코드 30=경로 있음+키 미등록)
- 파라미터는 **snake_case** (코레일 샘플 폼에서 확인):
  - 운행정보: `run_ymd`, `stn_cd`(7자리), `stn_nm`(완전일치), `mrnt_cd`(2자리), `mrnt_nm`
  - 운행계획: `run_ymd`, `dptre_stn_cd`/`dptre_stn_nm`, `arvl_stn_cd`/`arvl_stn_nm`
- **두 오퍼레이션 모두 열차번호 필터가 폼에 없다.** 질의 모델이
  "열차 → 정차역"이 아니라 "역/노선 → 열차들"이다.

## 이번 프로브가 답할 것

- Q1 문서에 없더라도 **열차번호 파라미터가 먹히는가** (`trn_no` 등 후보 시도)
- Q2 **오늘·내일** 운행정보가 조회되는가 (포털 설명상 '3개월 전~전일'로 읽혔다)
- Q3 역 기준 조회 응답에 **열차번호·정차구분·도착/출발시각**이 실제로 있는가
- Q4 ★ **주운행선(`mrnt_cd`) 단위로 하루치를 통째로** 받을 수 있는가 (totalCount 규모)
      → 되면 열차번호로 묶어 전체 정차역을 만들고 `train_stop`에 캐시한다
- Q5 `codes2`가 **역코드·노선코드 목록**을 주는가 (역 마스터의 코드 축)

실행:
    uv run python scripts/phase2_stops_probe.py

준비: `.env`에 `DATA_GO_KR_SERVICE_KEY=...` (Encoding/Decoding 어느 형태든 무방).
원시 응답은 `scripts/phase2_results/`에 저장한다 (gitignore 대상, 키는 마스킹).
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
TIMEOUT = 25

OP_INFO = "travelerTrainRunInfo2"  # 여객열차 운행정보 (역별 행)
OP_PLAN = "travelerTrainRunPlan2"  # 여객열차 운행계획 (열차별 시종착)
OP_CODES = "codes2"  # 코드정보

# 실측 대상 — Phase 0에서 쓴 무궁화호 1472 (천안→수원→영등포, 경부선)
SAMPLE_TRAIN_NO = "1472"
SAMPLE_STATION = "수원"

# 문서에 없는 열차번호 필터 후보. 먹히면 Q1이 해결돼 통째 다운로드가 불필요해진다.
TRAIN_PARAM_CANDIDATES = ["trn_no", "train_no", "trnNo", "trainNo", "trn_num"]


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


def load_service_key() -> str:
    key = _from_env("DATA_GO_KR_SERVICE_KEY")
    if not key:
        sys.exit(
            "DATA_GO_KR_SERVICE_KEY 가 없다.\n"
            "  data.go.kr → '한국철도공사_열차운행정보' 활용신청 → 인증키를\n"
            "  .env 에 DATA_GO_KR_SERVICE_KEY=... 로 넣어라."
        )
    return key


def normalize_key(key: str) -> str:
    """Encoding/Decoding 어느 형태로 붙여넣어도 동작하게 만든다.

    Encoding 키(`%2B`/`%2F`/`%3D` 포함)를 그대로 `urlencode`에 넘기면 `%`가 다시
    인코딩돼(`%252B`) 인증이 조용히 실패한다. 한 번 풀어두면 정확히 한 번만 인코딩된다.
    """
    return urllib.parse.unquote(key)


def mask(text: str, key: str) -> str:
    out = text
    raw = normalize_key(key)
    for form in {key, raw, urllib.parse.quote(raw, safe=""), urllib.parse.quote_plus(raw)}:
        if form:
            out = out.replace(form, "***SERVICE_KEY***")
    return out


def call(op: str, params: dict[str, str], key: str) -> tuple[int, str]:
    query = urllib.parse.urlencode(
        {"serviceKey": normalize_key(key), "_type": "json", **params}
    )
    req = urllib.request.Request(
        f"{BASE}/{op}?{query}", headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 — 진단 스크립트
        return 0, f"{type(e).__name__}: {e}"


def parse(body: str) -> dict:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def items_of(body: str) -> list[dict]:
    data = parse(body)
    node = (((data.get("response") or {}).get("body") or {}).get("items")) or {}
    if isinstance(node, dict):
        item = node.get("item") or []
        return item if isinstance(item, list) else [item]
    return node if isinstance(node, list) else []


def total_of(body: str) -> int | None:
    data = parse(body)
    return ((data.get("response") or {}).get("body") or {}).get("totalCount")


def err_of(body: str) -> str | None:
    data = parse(body)
    hdr = (data.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader")
    if hdr:
        return f"{hdr.get('errMsg')} ({hdr.get('returnReasonCode')})"
    resp_hdr = (data.get("response") or {}).get("header") or {}
    if resp_hdr and str(resp_hdr.get("resultCode")) not in ("0", "00"):
        return f"{resp_hdr.get('resultMsg')} ({resp_hdr.get('resultCode')})"
    return None


def step(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def main() -> None:
    key = load_service_key()
    RESULTS.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    today, tomorrow = date.today(), date.today() + timedelta(days=1)

    def run(label: str, op: str, params: dict[str, str], *, show: int = 2) -> tuple[list[dict], int | None]:
        status, body = call(op, params, key)
        safe = mask(body, key)
        err, total, items = err_of(body), total_of(body), items_of(body)
        log.append(
            {"label": label, "op": op, "params": params, "status": status, "body": safe[:6000]}
        )
        print(f"\n  ── {label}")
        print(f"     {op} {params}")
        if err:
            print(f"     ✗ {err}")
        else:
            print(f"     status={status} totalCount={total} items={len(items)}")
            for it in items[:show]:
                print(f"       {json.dumps(it, ensure_ascii=False)[:300]}")
        return items, total

    # ── Q3. 역 기준 조회의 응답 모양 ──────────────────────────────────
    step("Q3 — 역 기준 운행정보: 열차번호·정차구분·시각이 실제로 오는가")
    items, _ = run("역명으로 조회 (내일)", OP_INFO, {"run_ymd": ymd(tomorrow), "stn_nm": SAMPLE_STATION, "numOfRows": "5"})
    if items:
        print(f"\n     필드 목록: {sorted(items[0].keys())}")

    # ── Q2. 날짜 범위 ────────────────────────────────────────────────
    step("Q2 — 오늘·내일 운행정보가 조회되는가 (보유 기간 확인)")
    for label, d in [
        ("어제", today - timedelta(days=1)),
        ("오늘", today),
        ("내일", tomorrow),
        ("+7일", today + timedelta(days=7)),
        ("+30일", today + timedelta(days=30)),
    ]:
        run(f"{label} ({d})", OP_INFO, {"run_ymd": ymd(d), "stn_nm": SAMPLE_STATION, "numOfRows": "1"}, show=0)

    # ── Q1. 열차번호 필터가 먹히는가 (문서에 없음) ────────────────────
    step("Q1 — 열차번호 파라미터가 먹히는가 (먹히면 통째 다운로드 불필요)")
    baseline_items, baseline_total = run(
        "기준: 역명만 (내일)", OP_INFO, {"run_ymd": ymd(tomorrow), "stn_nm": SAMPLE_STATION, "numOfRows": "1"}, show=0
    )
    hits: list[str] = []
    for param in TRAIN_PARAM_CANDIDATES:
        _, total = run(
            f"+ {param}={SAMPLE_TRAIN_NO}",
            OP_INFO,
            {"run_ymd": ymd(tomorrow), "stn_nm": SAMPLE_STATION, param: SAMPLE_TRAIN_NO, "numOfRows": "1"},
            show=0,
        )
        # 총건수가 줄었으면 필터가 실제로 적용된 것 (무시됐다면 그대로다)
        if total is not None and baseline_total is not None and total < baseline_total:
            hits.append(param)
    print(f"\n  → 필터가 적용된 파라미터: {hits or '없음 (전부 무시됨)'}")

    # ── Q4. ★ 주운행선 단위 통째 다운로드 ─────────────────────────────
    step("Q4 — ★ 주운행선(mrnt_cd) 단위로 하루치를 통째로 받을 수 있는가")
    print("  되면 열차번호로 묶어 전체 정차역을 만들고 train_stop에 캐시한다.")
    print("  주운행선코드는 2자리다(예 01). 경부선을 찾기 위해 앞자리 몇 개를 훑는다.")
    for code in ["01", "02", "03", "05", "10"]:
        run(f"mrnt_cd={code} (내일)", OP_INFO, {"run_ymd": ymd(tomorrow), "mrnt_cd": code, "numOfRows": "3"}, show=1)

    print("\n  날짜만으로 (노선 필터 없이) 전체를 받을 수 있는지도 본다:")
    run("run_ymd만 (내일)", OP_INFO, {"run_ymd": ymd(tomorrow), "numOfRows": "3"}, show=1)

    # ── Q5. 코드정보 ─────────────────────────────────────────────────
    step("Q5 — codes2: 역코드·노선코드 목록이 나오는가")
    for params in (
        {"numOfRows": "10"},
        {"numOfRows": "10", "pageNo": "1"},
        {"numOfRows": "10", "code_type": "stn"},
        {"numOfRows": "10", "cd_grp": "stn"},
    ):
        run(f"codes2 {params}", OP_CODES, params, show=3)

    # ── 운행계획도 한 번 ──────────────────────────────────────────────
    step("참고 — 운행계획(travelerTrainRunPlan2)의 응답 모양")
    items, _ = run(
        "출발역명으로 조회 (내일)", OP_PLAN, {"run_ymd": ymd(tomorrow), "dptre_stn_nm": SAMPLE_STATION, "numOfRows": "3"}
    )
    if items:
        print(f"\n     필드 목록: {sorted(items[0].keys())}")

    out = RESULTS / "stops_probe.json"
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    step("요약")
    print(f"  Q1 열차번호 필터: {hits or '없음'}")
    print("  Q2/Q4는 위 출력의 totalCount를 봐라 (0이면 그 날짜/노선은 데이터 없음)")
    print(f"\n  원시 응답: {out} (키 마스킹됨)   총 호출 {len(log)}회")


if __name__ == "__main__":
    main()
