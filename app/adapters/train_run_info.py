"""공공데이터 '한국철도공사_열차운행정보' 클라이언트 + 재적재 오케스트레이션.

**분리 이유** — 원래 `scripts/load_train_stops.py`에 뭉쳐 있던 로직인데, 스케줄러가
같은 로직을 자동으로 부르려면 앱 코드가 import할 수 있어야 한다 (D-58, 이슈 #76).
스크립트는 얇은 CLI로 남기고 여기서 위임한다. 아키텍처 경계상 **외부 연동 =
adapters/**이 맞다 (CLAUDE.md 아키텍처 다이어그램).

## 재적재 게이트

`reload_needed`는 순수 함수. 스케줄러가 06:05/12:05/기동 시 세 번 부르는데,
`train_stop` 최신 `source_run_ymd`가 어제(=오늘-1일) 이상이면 스킵한다. 첫 성공만
네트워크를 쓴다.

## 트랜잭션 · 퍼지 (이슈 #75 원인 재발 방지)

`app.storage.db.connect`는 `isolation_level=None`(autocommit)이라 `save_stops`의
per-train delete+insert 사이를 폴 틱이 읽을 수 있다. `apply_day`는 명시적
`BEGIN…COMMIT/ROLLBACK`으로 감싸 그 경합을 잘라낸다.

저장 후 `DELETE FROM train_stop WHERE source_run_ymd < 컷오프`로 **오래된 번호를
퍼지**한다. 이슈 #75는 정확히 이 번호 재사용 충돌이 원인이었다 — 개편 전 노선이
그대로 남아 있어 새 라이브 열차와 부딪혔다. 기본 7일(주말 공백 커버, D-58 참고).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from typing import Callable, Iterator
from contextlib import contextmanager
import sqlite3

from app.domain.models import KST
from app.storage import stations as station_repo
from app.storage import train_stops as stop_repo
from app.storage.db import get_conn
from app.storage.stations import normalize_name

log = logging.getLogger(__name__)


BASE = "https://apis.data.go.kr/B551457/run/v2"
OP_INFO = "travelerTrainRunInfo2"
PAGE_SIZE = 1000
MAX_PAGES = 15  # 하루치 8,500~9,200건 실측 여유. 넘으면 잘렸다고 보고한다


# ──────────────────────────────────────────────────────────────
# 공공데이터 API 호출 (원래 scripts/load_train_stops.py 소재)
# ──────────────────────────────────────────────────────────────


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
    return json.loads(raw)


def _parse_dt(text: str | None) -> datetime | None:
    """`'2026-08-04 05:13:00.0'` → KST aware datetime. `None`/빈 값은 그대로 None."""
    if not text or text in ("None", "null"):
        return None
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except ValueError:
        return None


def fetch_day(run_ymd: _date, key: str) -> list[dict]:
    """하루치 운행정보를 전부 받는다 (~9페이지 실측). D-1 실적이 표준.

    빈 리스트는 실제로 그 날 데이터가 아직 공개되지 않았다는 뜻일 수 있다 (호출자가 판단).
    """
    day = run_ymd.strftime("%Y%m%d")
    day_filter = {"cond[run_ymd::GTE]": day, "cond[run_ymd::LTE]": day}

    first = _call(OP_INFO, {**day_filter, "numOfRows": "1"}, key)
    total = ((first.get("response") or {}).get("body") or {}).get("totalCount") or 0
    if not total:
        return []

    pages = -(-total // PAGE_SIZE)
    if pages > MAX_PAGES:
        log.warning(
            "%s: %s건 = %s페이지인데 %s페이지까지만 받는다 (일부 누락)",
            run_ymd, total, pages, MAX_PAGES,
        )

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


def to_stop_rows(raw_rows: list[dict], run_ymd: _date) -> dict[str, list[stop_repo.StopRow]]:
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


# ──────────────────────────────────────────────────────────────
# 재적재 오케스트레이션 (D-58, 이슈 #76)
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReloadStats:
    """스케줄러 로그 한 줄로 요약할 결과."""

    trains: int
    stations: int
    purged: int
    run_ymd: _date


def reload_needed(latest: _date | None, now: datetime) -> bool:
    """캐시가 D-1보다 오래됐거나 비어 있으면 True.

    스케줄러가 06:05/12:05/기동 시 세 번 부르는데, 이 게이트 덕분에 첫 성공만
    네트워크를 쓴다 — 나머지 호출은 조용히 스킵.
    """
    if latest is None:
        return True
    return latest < now.date() - timedelta(days=1)


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """`connect()`가 autocommit이라 명시적 BEGIN이 필요하다.

    이 트랜잭션 없이 per-train delete+insert 사이를 폴 틱이 읽으면 매트릭스가 순간
    '정차역 없음'으로 뜬다. WAL 스냅샷 격리로 폴 틱은 트랜잭션 이전 상태를 본다.
    """
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def apply_day(
    conn: sqlite3.Connection,
    by_train: dict[str, list[stop_repo.StopRow]],
    *,
    run_ymd: _date,
    now: datetime,
    max_age_days: int,
) -> ReloadStats:
    """열차별 정차역을 저장하고 오래된 번호를 퍼지한다. 트랜잭션 한 방.

    - `save_stops`가 열차 단위 delete+insert (`train_stops.py:44`).
    - 퍼지 컷오프: `run_ymd - max_age_days`. **엄격 부등호(`<`)** — 정확히 컷오프
      날짜의 데이터는 유지한다(경계는 유지 방향, 실무 안전).
    - `station.usable`은 켜기만 한다 (D-29, `mark_usable`).
    """
    station_names: set[str] = set()
    station_codes: dict[str, str] = {}
    for rows in by_train.values():
        for row in rows:
            if row.station_name:
                station_names.add(row.station_name)
                if row.station_code:
                    station_codes[row.station_name] = row.station_code

    cutoff = (run_ymd - timedelta(days=max_age_days)).isoformat()

    with _transaction(conn):
        for train_no, rows in by_train.items():
            stop_repo.save_stops(conn, train_no, rows, now=now)
        touched_stations = station_repo.mark_usable(
            conn, list(station_names), now=now, codes=station_codes
        )
        purged = conn.execute(
            "DELETE FROM train_stop WHERE source_run_ymd < ?", (cutoff,)
        ).rowcount

    return ReloadStats(
        trains=len(by_train),
        stations=touched_stations,
        purged=purged,
        run_ymd=run_ymd,
    )


class NoDataForDay(RuntimeError):
    """공공데이터에 해당 운행일의 실적이 아직 없다.

    개편 첫날처럼 D-1 실적이 하루 늦게 공개되는 경우. 호출자(스케줄러)는 로그만
    남기고 다음 게이트 호출을 기다린다 — 알림은 만들지 않는다 (알림 5종 불변).
    """


def reload_train_stops(
    *,
    run_ymd: _date,
    key: str,
    now: datetime,
    max_age_days: int,
    conn_factory: Callable[[], Iterator[sqlite3.Connection]] = get_conn,
) -> ReloadStats:
    """네트워크 fetch → apply_day. 트랜잭션은 apply_day 안에서만.

    fetch가 도는 동안 DB 락을 잡지 않는다 (호출 예절이 아니라 락 시간 최소화).
    """
    raw_rows = fetch_day(run_ymd, key)
    if not raw_rows:
        raise NoDataForDay(f"{run_ymd} 실적이 공공데이터에 아직 없다")
    by_train = to_stop_rows(raw_rows, run_ymd)
    with conn_factory() as conn:
        return apply_day(
            conn, by_train, run_ymd=run_ymd, now=now, max_age_days=max_age_days
        )
