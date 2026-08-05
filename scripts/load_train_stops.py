"""열차별 정차역 캐시 적재 — get_stops() 소스 (Phase 2 항목 A, D-29).

Phase 0 항목 5(NO) 문제를 실제로 푸는 스크립트다. 코레일에는 "열차번호 → 전체
정차역"을 주는 엔드포인트가 없지만, 공공데이터 '한국철도공사_열차운행정보'
(`travelerTrainRunInfo2`)가 **실적(과거)** 데이터로 정차역+순번+시각을 준다.

## 설계 (D-29, 4차 프로브 실측 근거)

- 운행정보는 실적이라 **과거만** 있다(대개 D-1까지). 오늘 탈 열차의 정차역이
  오늘 자로는 안 나온다.
- 그러나 정차 **순서**는 시각표 사실이라 요일에 걸쳐 안정적이다 — 화·월·일·토
  4일 연속 동일 패턴임을 실측했다(무궁화호 1472, `scripts/phase2_stops_probe.py`).
- 그래서 **가장 최근 운행일 1개를 열차번호 단위 템플릿으로 캐시**하고, 조회
  시점의 실제 날짜에 재적용한다 (`app.storage.train_stops.get_stops`가 시각을
  재조합한다). 코레일 자체 API가 아니라 정적 참조가 아닌 "최근 실적"이라는 점이
  역 마스터 CSV와 다르다 — **주기적으로 재적재해야 신선도가 유지된다.**

## 알려진 한계 — 열차번호가 개정으로 바뀔 수 있다

같은 노선(익산→용산)에 대해 8/4는 `1472`였는데 8/6~8/10은 `1202~1210` 대역으로
관측됐다(정기 시각표 개정으로 추정). 캐시에 없는 열차번호는 **에러로 명확히
드러난다**(`get_stops`가 None을 반환 → 어댑터가 `StopsSourceUnavailable`류 예외).
조용히 틀린 답을 주지 않는다 — 재적재로 대응한다.

## 부수 효과 — 역 usable 확정 (G와 연결)

이 파일이 반환하는 각 행에는 `stn_cd`+`stn_nm`이 있다. 열차가 실제로 서는 역이므로
**여객역인 것이 확실**하다 — 좌표 유무로 추론하지 않고(D-28 개정, 그 방식은
지하철역까지 usable로 만들어버린다) 시각표 등장 자체를 근거로 삼는다.
같은 역명에 역코드가 여러 개인 경우(D-28의 25건)도 여기서 **권위 있는 값으로
확정**된다 — 열차가 실제로 쓰는 코드가 정답이다.

## 쓰는 법

    uv run python scripts/load_train_stops.py                # 어제 하루치
    uv run python scripts/load_train_stops.py --date 20260804
    uv run python scripts/load_train_stops.py --dry-run       # 무엇이 저장될지만

준비: `.env`에 `DATA_GO_KR_SERVICE_KEY=...` (역 마스터 로더와 동일 키).
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.models import KST  # noqa: E402
from app.storage import stations as station_repo  # noqa: E402
from app.storage import train_stops as stop_repo  # noqa: E402
from app.storage.db import get_conn, init_db  # noqa: E402
from app.storage.stations import normalize_name  # noqa: E402

BASE = "https://apis.data.go.kr/B551457/run/v2"
OP_INFO = "travelerTrainRunInfo2"
ROOT = Path(__file__).resolve().parent.parent
PAGE_SIZE = 1000
MAX_PAGES = 15  # 하루치 8,500~9,200건 실측 기준 여유있게. 넘으면 잘렸다고 보고한다


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
    if key := _from_env("DATA_GO_KR_SERVICE_KEY"):
        return key
    sys.exit("DATA_GO_KR_SERVICE_KEY 가 .env 에 없다.")


def _call(op: str, params: dict[str, str], key: str) -> dict:
    query = urllib.parse.urlencode(
        {"serviceKey": urllib.parse.unquote(key), "returnType": "JSON", **params}
    )
    req = urllib.request.Request(f"{BASE}/{op}?{query}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
    import json

    return json.loads(raw)


def _parse_dt(text: str | None) -> datetime | None:
    """`'2026-08-04 05:13:00.0'` → KST aware datetime. `None`/빈 값은 그대로 None."""
    if not text or text in ("None", "null"):
        return None
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except ValueError:
        return None


def fetch_day(run_ymd: date, key: str) -> list[dict]:
    """하루치 운행정보를 전부 받는다 (~9페이지 실측)."""
    day = run_ymd.strftime("%Y%m%d")
    day_filter = {"cond[run_ymd::GTE]": day, "cond[run_ymd::LTE]": day}

    first = _call(OP_INFO, {**day_filter, "numOfRows": "1"}, key)
    total = ((first.get("response") or {}).get("body") or {}).get("totalCount") or 0
    if not total:
        return []

    pages = -(-total // PAGE_SIZE)
    if pages > MAX_PAGES:
        print(f"  ⚠ {total}건 = {pages}페이지인데 {MAX_PAGES}페이지까지만 받는다 (일부 누락)")

    rows: list[dict] = []
    for page in range(1, min(pages, MAX_PAGES) + 1):
        data = _call(
            OP_INFO, {**day_filter, "numOfRows": str(PAGE_SIZE), "pageNo": str(page)}, key
        )
        body = (data.get("response") or {}).get("body") or {}
        node = (body.get("items") or {}).get("item") or []
        items = node if isinstance(node, list) else [node]
        if not items:
            break
        rows.extend(items)
    return rows


def to_stop_rows(raw_rows: list[dict], run_ymd: date) -> dict[str, list[stop_repo.StopRow]]:
    """열차번호별로 묶어 순번 순으로 정렬한 `StopRow` 목록을 만든다."""
    by_train: dict[str, list[dict]] = defaultdict(list)
    for r in raw_rows:
        by_train[str(r.get("trn_no") or "")].append(r)

    out: dict[str, list[stop_repo.StopRow]] = {}
    for train_no, rows in by_train.items():
        rows.sort(key=lambda r: int(r.get("trn_run_sn") or 0))
        out[train_no] = [
            stop_repo.StopRow(
                seq=int(r.get("trn_run_sn") or 0),
                station_name=normalize_name(r.get("stn_nm") or ""),
                station_code=str(r.get("stn_cd") or "").strip() or None,
                stop_type=str(r.get("stop_se_nm") or "").strip(),
                arrival=_parse_dt(r.get("trn_arvl_dt")),
                departure=_parse_dt(r.get("trn_dptre_dt")),
                run_ymd=run_ymd,
            )
            for r in rows
        ]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="열차별 정차역 캐시를 최근 운행일 실적으로 적재한다")
    parser.add_argument("--date", type=str, help="YYYYMMDD. 기본: 어제")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_ymd = (
        datetime.strptime(args.date, "%Y%m%d").date()
        if args.date
        else date.today() - timedelta(days=1)
    )
    key = load_service_key()

    print(f"── {run_ymd} 하루치 운행정보 조회")
    raw_rows = fetch_day(run_ymd, key)
    if not raw_rows:
        sys.exit(f"  {run_ymd}에 데이터가 없다. 최신 가용일은 대개 D-1이다 — --date로 지정하라.")
    print(f"   받은 행 {len(raw_rows)}개")

    by_train = to_stop_rows(raw_rows, run_ymd)
    print(f"   열차 {len(by_train)}편")

    now = datetime.now(KST)
    station_names: set[str] = set()
    station_codes: dict[str, str] = {}
    for rows in by_train.values():
        for row in rows:
            if row.station_name:
                station_names.add(row.station_name)
                if row.station_code:
                    station_codes[row.station_name] = row.station_code

    print(f"   역 {len(station_names)}개 (코드 확보 {len(station_codes)}개)")

    if args.dry_run:
        sample = sorted(by_train)[:5]
        for tno in sample:
            names = [r.station_name for r in by_train[tno]]
            print(f"   {tno}: {' → '.join(names[:8])}{' …' if len(names) > 8 else ''}")
        print(f"\n[dry-run] 저장하지 않았다.")
        return

    with get_conn() as conn:
        init_db()
        for train_no, rows in by_train.items():
            stop_repo.save_stops(conn, train_no, rows, now=now)
        touched = station_repo.mark_usable(
            conn, list(station_names), now=now, codes=station_codes
        )

    print(f"\n✅ 적재 완료: 열차 {len(by_train)}편 / 역 {touched}개를 여객역으로 확정")
    print(f"   신선도: {run_ymd} 실적 기준 (오늘 - {(date.today() - run_ymd).days}일)")


if __name__ == "__main__":
    main()
