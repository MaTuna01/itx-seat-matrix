"""열차별 정차역 캐시 수동 재적재 (Phase 2 항목 A, D-29 → D-58 자동화).

**로직은 `app.adapters.train_run_info`에 있고 여기는 얇은 CLI다** (D-58, 이슈 #76).
스케줄러가 매일 자동으로 부르지만, 아래 두 경우를 위해 수동 경로를 남긴다:

- 개편 첫날 오전 등 자동 실행 전에 급히 반영하고 싶을 때
- 재적재 실패 로그를 보고 손으로 다시 돌리고 싶을 때

## 알려진 한계 — 열차번호가 개정으로 바뀔 수 있다

같은 노선(익산→용산)에 대해 8/4는 `1472`, 8/6~8/10은 `1202~1210`대로 관측됐다
(정기 시각표 개정 추정). 캐시에 없는 열차번호는 `TrainStopsNotCached`로 명확히
드러난다(app/api/stops.py의 사용자 문구, 이슈 #75). D-58 자동 재적재가 붙은
지금은 개편 다음 날 새벽에 자동으로 회복된다.

## 쓰는 법

    uv run python scripts/load_train_stops.py                # 어제 하루치
    uv run python scripts/load_train_stops.py --date 20260804
    uv run python scripts/load_train_stops.py --dry-run       # 무엇이 저장될지만

준비: `.env`에 `DATA_GO_KR_SERVICE_KEY=...` (역 마스터 로더와 동일 키).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.train_run_info import fetch_day, reload_train_stops, to_stop_rows  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.domain.models import KST  # noqa: E402
from app.storage.db import init_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _from_env(name: str) -> str:
    """`.env` 파일 우선 읽기 — 배포 컨테이너에도 마운트돼 있어 그대로 동작한다."""
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="열차별 정차역 캐시를 최근 운행일 실적으로 적재한다 (D-58 자동화의 수동 경로)"
    )
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

    if args.dry_run:
        raw_rows = fetch_day(run_ymd, key)
        if not raw_rows:
            sys.exit(f"  {run_ymd}에 데이터가 없다. 최신 가용일은 대개 D-1이다.")
        print(f"   받은 행 {len(raw_rows)}개")
        by_train = to_stop_rows(raw_rows, run_ymd)
        print(f"   열차 {len(by_train)}편")
        sample = sorted(by_train)[:5]
        for tno in sample:
            names = [r.station_name for r in by_train[tno]]
            print(f"   {tno}: {' → '.join(names[:8])}{' …' if len(names) > 8 else ''}")
        print("\n[dry-run] 저장하지 않았다.")
        return

    init_db()
    now = datetime.now(KST)
    settings = get_settings()
    from app.adapters.train_run_info import NoDataForDay

    try:
        stats = reload_train_stops(
            run_ymd=run_ymd,
            key=key,
            now=now,
            max_age_days=settings.train_stop_max_age_days,
        )
    except NoDataForDay as exc:
        sys.exit(f"  {exc}. --date 로 다른 날짜를 지정하라.")

    print(
        f"\n✅ 적재 완료: 열차 {stats.trains}편 · 역 {stats.stations}개 확정 · 퍼지 {stats.purged}행"
    )
    print(f"   신선도: {run_ymd} 실적 기준 (오늘 - {(date.today() - run_ymd).days}일)")


if __name__ == "__main__":
    main()
