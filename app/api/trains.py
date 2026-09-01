"""열차 조회 + 매트릭스 (PLAN.md 7절).

`GET /api/trains/{train_no}/matrix`가 **프론트의 유일한 핵심 호출**이다.
응답 스키마는 PLAN 7절 예시와 1:1 (프로토타입 `seat-matrix.jsx`가 그대로 렌더한다).

`lat/lng`(+ `gps_accuracy_m`/`gps_fixed_at_ms`)는 선택 파라미터다. 있으면
`domain/geo.py`의 선분 투영으로 `current_seg_idx`를 GPS 실측으로 보정한다 (D-13).
위치 권한을 거부해도(파라미터 없음) 전 기능이 정상 동작한다.
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import datetime, time as _time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.adapters.delay_zero import ZeroDelayAdapter
from app.adapters.korail2_adapter import CredentialsRequired
from app.adapters.korail_port import KorailPort
from app.adapters.seatmap_fetcher import SCREEN_RETRY, fetch_matrix
from app.api.deps import get_delay_port, get_korail_cred, get_korail_port, now_kst
from app.api.stops import resolve_route
from app.auth.session import current_user
from app.domain.geo import GeoFix, is_fix_usable, project_onto_route
from app.domain.matrix import query_range, snapshot_gap_range
from app.domain.models import KST, KorailCred, SubscriptionStatus, TrainSummary, User, Verdict
from app.domain.timeline import estimate_seg, next_poll_hint, sellable_seg_idx
from app.domain.verdict import build_verdict
from app.storage import stations as station_repo
from app.storage.db import db_session
from app.storage import seat_snapshot
from app.storage.matrix_cache import SqliteSeatMapCache
from app.storage.seat_snapshot import SqliteSeatSnapshotStore

router = APIRouter(prefix="/api/trains", tags=["trains"])


class SeatRowOut(BaseModel):
    car: int
    seat_no: str
    cells: list[bool]


class NextPollOut(BaseModel):
    station: str
    offset_min: int
    # offset의 기준: "arrival"(도착 -N분) | "departure"(출발 -N분, D-57).
    # 기본값은 하위호환 — 구형 캐시본(`readCachedMatrix`)에 없어도 안전해야 한다
    basis: str = "arrival"


class SnapshotSeatOut(BaseModel):
    car: int
    seat_no: str
    sold: bool


class SnapshotSegOut(BaseModel):
    """갭 구간(지금 타고 있는 구간)의 마지막 성공 조회 (→ D-57). 표시 전용."""

    seg_idx: int  # 전체 노선 stops 기준 (D-18)
    as_of: datetime  # 조회 시각 (KST aware) — "HH:MM 조회" 배지의 근거
    seats: list[SnapshotSeatOut]


class MatrixOut(BaseModel):
    train_no: str
    train_name: str | None = None
    date: _date
    stops: list[str]
    current_seg_idx: int
    position_source: str  # "schedule" | "gps" (gps는 Phase 2)
    delay_minutes: int | None
    board_at: str
    alight_at: str
    sub_status: SubscriptionStatus
    my_car: int | None
    my_seat_no: str | None
    seats: list[SeatRowOut]
    # 조회에 실패한 구간 (→ D-48). 셀은 채움값(판매됨)으로 들어가므로 이 값이 없으면
    # **화면이 조회 실패와 매진을 구분할 수 없다** — 사용자에게 전혀 다른 정보다
    failed_seg_idxs: list[int]
    # 갭 구간의 마지막 성공 조회 (→ D-57). verdict 계산 **이후** 채워진다 —
    # 판정·알림·추천에는 절대 유입되지 않는다 (#35 재발 방지)
    snapshots: list[SnapshotSegOut] = []
    verdict: Verdict
    next_poll: NextPollOut | None
    fetched_at: datetime


def parse_my_seat(my_seat: str | None) -> tuple[int | None, str | None]:
    """`"3-7A"` → `(3, "7A")`. 형식이 틀리면 422."""
    if not my_seat:
        return None, None
    car, _, seat_no = my_seat.partition("-")
    if not seat_no or not car.isdigit():
        raise HTTPException(
            status_code=422,  # starlette 버전에 따라 상수명이 갈려 숫자로 고정
            detail="my_seat 형식은 '호차-좌석번호'다 (예: 3-7A)",
        )
    return int(car), seat_no


@router.get("/search", response_model=list[TrainSummary])
async def search_trains(
    date: _date,
    from_station: str = Query(alias="from"),
    to_station: str = Query(alias="to"),
    time: str | None = Query(default=None, description='출발 시각 하한 "HH:MM" (D-25)'),
    user: User = Depends(current_user),
    port: KorailPort = Depends(get_korail_port),
    cred: KorailCred | None = Depends(get_korail_cred),
) -> list[TrainSummary]:
    """`time`은 정확한 시각이 아니라 **하한**이다 — "5시 이후 열차"를 전부 준다 (D-25)."""
    at = None
    if time:
        try:
            at = datetime.combine(date, _time.fromisoformat(time), tzinfo=KST)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail='time 형식은 "HH:MM"이다') from exc
    try:
        return await port.search_trains(cred, date, from_station, to_station, at)
    except CredentialsRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{train_no}/matrix", response_model=MatrixOut)
async def get_matrix(
    train_no: str,
    date: _date,
    board_at: str,
    alight_at: str,
    my_seat: str | None = None,
    lat: float | None = Query(default=None, description="GPS 위도 (선택, D-13)"),
    lng: float | None = Query(default=None, description="GPS 경도 (선택, D-13)"),
    gps_accuracy_m: float | None = Query(default=None, description="GPS 정확도 반경(m)"),
    gps_fixed_at_ms: float | None = Query(
        default=None, description="GPS 측정 시각 (epoch ms — Geolocation.timestamp 그대로)"
    ),
    user: User = Depends(current_user),
    port: KorailPort = Depends(get_korail_port),
    delay_port: ZeroDelayAdapter = Depends(get_delay_port),
    cred: KorailCred | None = Depends(get_korail_cred),
    conn: sqlite3.Connection = Depends(db_session),
) -> MatrixOut:
    now = now_kst()
    my_car, my_seat_no = parse_my_seat(my_seat)

    # 정차역 캐시 미스/노선 불일치는 여기서 사용자용 404로 매핑된다 (이슈 #75, app/api/stops.py)
    stops, board_idx, alight_idx = await resolve_route(
        port, cred, conn,
        train_no=train_no, date=date,
        board_at=board_at, alight_at=alight_at,
        now=now,
    )
    names = [s.name for s in stops]

    train_name = await port.get_train_name(train_no, date)
    delay_minutes = await delay_port.get_delay_minutes(train_no, date)
    current_seg_idx = estimate_seg(stops, delay_minutes or 0, now)
    position_source = "schedule"

    # GPS 포그라운드 보정 (D-13). 넷 다 있어야 시도한다 — 일부만 오면 신선도를
    # 판단할 수 없으므로 시각표 추정을 그대로 둔다(안전한 방향, D-21).
    if None not in (lat, lng, gps_accuracy_m, gps_fixed_at_ms):
        fix = GeoFix(
            lat=lat,
            lng=lng,
            accuracy_m=gps_accuracy_m,
            fixed_at=datetime.fromtimestamp(gps_fixed_at_ms / 1000, tz=KST),
        )
        if is_fix_usable(fix, now=now):
            coords = station_repo.coords_for(conn, names)
            gps_idx = project_onto_route(names, coords, lat, lng)
            if gps_idx is not None:
                current_seg_idx = gps_idx
                position_source = "gps"

    # 조회 범위 = 실효 시작 ~ 하차역 (D-17/D-18). 지나온 구간은 호출하지 않는다.
    # 시작은 **위치가 아니라 팔 수 있는 첫 구간**이다 (이슈 #35 → D-47). GPS 보정값도
    # 반드시 이 함수를 거친다 — GPS는 주행 중인 구간을 정확히 짚어주므로 그대로 쓰면
    # 오히려 "이미 출발해 팔 수 없는 구간"을 확실히 조회하게 된다
    sellable_idx = sellable_seg_idx(
        stops,
        delay_minutes or 0,
        now,
        position_idx=current_seg_idx if position_source == "gps" else None,
    )
    start_idx, end_idx = query_range(sellable_idx, board_idx, alight_idx)
    # 60초 TTL 캐시는 **화면 전용**이다 — 새로고침 연타를 흡수한다.
    # 스케줄러는 이 경로를 쓰지 않고 cache=None + SCHEDULER_RETRY로 항상 실조회한다 (D-17).
    # 재시도도 화면용으로 짧게 간다 — 30초×3이면 최악 60초간 응답이 멈춘다 (D-27).
    try:
        matrix = await fetch_matrix(
            port,
            cred,
            train_no,
            date,
            names,
            start_idx,
            end_idx,
            now=now,
            cache=SqliteSeatMapCache(conn),
            # 화면 실조회도 스냅샷을 남긴다 — 표시 전용 데이터라 알림 상태와 무관 (D-57)
            recorder=SqliteSeatSnapshotStore(conn),
            retry=SCREEN_RETRY,
        )
    except CredentialsRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sub_status = SubscriptionStatus.SEATED if my_car is not None else SubscriptionStatus.STANDING
    verdict = build_verdict(
        matrix=matrix,
        status=sub_status,
        board_idx=board_idx,
        alight_idx=alight_idx,
        sellable_seg_idx=sellable_idx,
        my_car=my_car,
        my_seat_no=my_seat_no,
    )
    hint = next_poll_hint(stops, board_idx, alight_idx, delay_minutes or 0, now)

    # 갭 구간(지금 타고 있는 구간)의 마지막 성공 조회 (→ D-57). verdict가 끝난 뒤에만
    # 채운다 — 표시 전용이라는 경계를 코드 순서로도 지킨다. GPS 보정이 있으면
    # current_seg_idx가 실측이므로 갭이 더 정확해진다
    gap_start, gap_end = snapshot_gap_range(current_seg_idx, sellable_idx, board_idx, alight_idx)
    snapshots: list[SnapshotSegOut] = []
    for seg_idx in range(gap_start, gap_end):
        snap = seat_snapshot.load(conn, train_no, date, names[seg_idx], names[seg_idx + 1])
        if snap is None:
            continue  # 스냅샷이 없으면 프론트가 기존 회색(past) 표시로 폴백한다
        snapshots.append(
            SnapshotSegOut(
                seg_idx=seg_idx,
                as_of=snap.fetched_at,
                seats=[
                    SnapshotSeatOut(car=s.car, seat_no=s.seat_no, sold=s.sold)
                    for s in snap.seats
                ],
            )
        )

    return MatrixOut(
        train_no=train_no,
        train_name=train_name,
        date=date,
        stops=names,
        current_seg_idx=current_seg_idx,
        position_source=position_source,
        delay_minutes=delay_minutes,
        board_at=board_at,
        alight_at=alight_at,
        sub_status=sub_status,
        my_car=my_car,
        my_seat_no=my_seat_no,
        seats=[SeatRowOut(car=s.car, seat_no=s.seat_no, cells=s.cells) for s in matrix.seats],
        failed_seg_idxs=matrix.failed_seg_idxs,
        snapshots=snapshots,
        verdict=verdict,
        next_poll=(
            NextPollOut(station=hint.station, offset_min=hint.offset_min, basis=hint.basis)
            if hint
            else None
        ),
        fetched_at=matrix.fetched_at,
    )
