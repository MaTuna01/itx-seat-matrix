"""정차역 캐시 관련 에러 매핑 — `/matrix`와 `POST /subscriptions`가 공유한다.

두 엔드포인트가 각자 다른 문구·상태로 실패하지 않도록 한곳에 모은다 (D-50 문구 단일화
정신 + 이슈 #75). 특히 `TrainStopsNotCached`는 `RuntimeError` 상속이라 `ValueError`만
잡던 `_compute_next_poll_at`에서 500으로 새고 있었다 — `resolve_route`가 그 구멍을 막는다.

문구 규칙 (D-29 정신):
- 캐시 미스는 재적재로 회복된다 — 다음 자동 갱신 시점을 안내한다.
- 노선 불일치는 개편/오입력을 나이만으로 구분할 수 없다(개편 당일엔 1일치 데이터도
  '틀림'이다). 그래서 정보 기준일(`source_run_ymd`)을 노출하고 두 가능성을 함께 적는다.
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import datetime

from fastapi import HTTPException

from app.adapters.korail2_adapter import TrainStopsNotCached
from app.adapters.korail_port import KorailPort
from app.domain.matrix import route_indexes
from app.domain.models import KorailCred, StopInfo
from app.storage.train_stops import freshness, latest_source_run_ymd


def stops_error_detail(
    *,
    train_no: str,
    missing_station: str | None,
    source_run_ymd: _date | None,
    now: datetime,  # noqa: ARG001 — 시그니처에 미리 둔다 (D-21: 시간 의존 코드는 now 주입)
) -> str:
    """캐시 미스/노선 불일치용 사용자 대상 한국어 문구.

    `now`는 지금은 쓰지 않지만 미리 받는다. 이후 "새벽 갱신까지 X시간" 같은 안내로
    확장할 여지를 남기되, 함수 내부에서 `datetime.now()`를 호출하지 않는 규약(CLAUDE.md 2)
    을 지키기 위함이다.
    """
    if missing_station is None:
        # 캐시 미스 — source_run_ymd는 이 열차에 대한 것이 없으니 전체 최신값을 참고 문구로
        base = f"열차 {train_no}의 정차역 정보가 아직 준비되지 않았습니다."
        if source_run_ymd is not None:
            base += f" (전체 캐시 기준일: {source_run_ymd.isoformat()})"
        base += " 시각표 개편 직후에는 다음 날 새벽 자동 갱신 후 등록할 수 있습니다."
        return base

    # 노선 불일치 — 이 열차의 캐시 기준일을 명시해 개편 가능성을 알린다
    base = f"'{missing_station}' 역이 열차 {train_no}의 정차역 목록에 없습니다."
    if source_run_ymd is not None:
        base += f" (정보 기준: {source_run_ymd.isoformat()} 운행 실적)"
    base += " 시각표 개편으로 정보가 낡았을 수 있습니다 — 다음 자동 갱신 후 다시 시도하세요."
    return base


async def resolve_route(
    port: KorailPort,
    cred: KorailCred | None,
    conn: sqlite3.Connection,
    *,
    train_no: str,
    date: _date,
    board_at: str,
    alight_at: str,
    now: datetime,
) -> tuple[list[StopInfo], int, int]:
    """정차역 조회 + board/alight 인덱싱을 한번에. 실패는 사용자용 문구로 HTTPException.

    반환: (stops, board_idx, alight_idx). 매트릭스/구독 등록이 공용으로 쓴다.
    """
    try:
        stops = await port.get_stops(cred, train_no, date)
    except TrainStopsNotCached as exc:
        latest = latest_source_run_ymd(conn)
        raise HTTPException(
            status_code=404,
            detail=stops_error_detail(
                train_no=train_no,
                missing_station=None,
                source_run_ymd=latest,
                now=now,
            ),
        ) from exc
    except ValueError as exc:
        # 목업 어댑터 등 — "목업에 없는 열차번호다" 같은 개발자 문구는 그대로 두고 404만 통일
        raise HTTPException(status_code=404, detail="열차를 찾을 수 없습니다") from exc

    names = [s.name for s in stops]
    try:
        board_idx, alight_idx = route_indexes(names, board_at, alight_at)
    except LookupError as exc:
        # 어느 역이 빠졌는지 판정 — 둘 다 빠지면 board를 먼저 보여준다 (사용자 흐름 순서)
        missing = board_at if board_at not in names else alight_at
        src = freshness(conn, train_no)
        raise HTTPException(
            status_code=404,
            detail=stops_error_detail(
                train_no=train_no,
                missing_station=missing,
                source_run_ymd=src,
                now=now,
            ),
        ) from exc
    except ValueError as exc:
        # 순서 역전은 사용자 입력 오류 — 422 유지 (starlette 상수명이 갈려 숫자로 고정)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return stops, board_idx, alight_idx
