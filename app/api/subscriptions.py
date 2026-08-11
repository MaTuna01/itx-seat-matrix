"""구독 CRUD + 상태 전이 (PLAN.md 7절, D-15/D-19).

`PATCH /api/subscriptions/{id}` 하나로 세 전이를 모두 커버한다:
앉음(STANDING→SEATED) / 이동(SEATED 좌석 변경) / 일어남(SEATED→STANDING).
**옮기는 행위가 이 앱의 핵심 루프**다 — 전이 입력이 없으면 이후 모든 알림이
이미 떠난 자리를 기준으로 울린다.

`last_verdict_hash` / `last_cells_snapshot`은 **스케줄러만 기록한다** (D-13/D-17).
단, 상태 전이 시 스냅샷 무효화(NULL)는 여기서 한다 — 새 좌석의 셀 전이를
옛 좌석 스냅샷과 비교하면 거짓 `SEAT_EXTENDED`가 나간다 (D-16).
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, model_validator

from app.adapters.delay_zero import ZeroDelayAdapter
from app.adapters.korail_port import KorailPort
from app.api.deps import get_delay_port, get_korail_port, now_kst
from app.auth.session import current_user
from app.domain.matrix import route_indexes
from app.domain.models import SubscriptionStatus, User
from app.domain.timeline import compute_poll_points, first_poll_at
from app.storage.db import date_from_db, db_session, dt_from_db, to_db

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class SubscriptionIn(BaseModel):
    train_no: str
    date: _date
    board_at: str
    alight_at: str
    status: SubscriptionStatus = SubscriptionStatus.STANDING
    my_car: int | None = None
    my_seat_no: str | None = None

    @model_validator(mode="after")
    def check_seat(self) -> "SubscriptionIn":
        # status=SEATED면 my_car/my_seat_no 필수 (422 검증, PLAN 7절)
        if self.status is SubscriptionStatus.SEATED and (self.my_car is None or not self.my_seat_no):
            raise ValueError("SEATED 구독은 my_car/my_seat_no가 필요하다")
        if self.status is SubscriptionStatus.STANDING and (self.my_car is not None or self.my_seat_no):
            raise ValueError("STANDING 구독에는 좌석 정보를 넣지 않는다")
        return self


class SubscriptionPatch(BaseModel):
    """부분 갱신. 최종 상태가 SEATED인데 좌석이 없으면 422 (엔드포인트에서 검증)."""

    status: SubscriptionStatus | None = None
    my_car: int | None = None
    my_seat_no: str | None = None


class SubscriptionOut(BaseModel):
    id: int
    train_no: str
    date: _date
    board_at: str
    alight_at: str
    status: SubscriptionStatus
    my_car: int | None
    my_seat_no: str | None
    active: bool
    next_poll_at: datetime | None
    created_at: datetime


def _row_to_out(row: sqlite3.Row) -> SubscriptionOut:
    return SubscriptionOut(
        id=row["id"],
        train_no=row["train_no"],
        date=date_from_db(row["date"]),
        board_at=row["board_at"],
        alight_at=row["alight_at"],
        status=SubscriptionStatus(row["status"]),
        my_car=row["my_car"],
        my_seat_no=row["my_seat_no"],
        active=bool(row["active"]),
        next_poll_at=dt_from_db(row["next_poll_at"]),
        created_at=dt_from_db(row["created_at"]),
    )


def _load_own(conn: sqlite3.Connection, sub_id: int, user_id: int) -> sqlite3.Row:
    """자기 구독만 만질 수 있다 — user_id는 세션에서만 온다 (IDOR 방지)."""
    row = conn.execute(
        "SELECT * FROM subscription WHERE id = ? AND user_id = ?", (sub_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="구독을 찾을 수 없습니다")
    return row


async def _compute_next_poll_at(
    port: KorailPort,
    delay_port: ZeroDelayAdapter,
    *,
    train_no: str,
    date: _date,
    board_at: str,
    alight_at: str,
    now: datetime,
) -> str | None:
    """구독 생성/갱신 시 첫 폴 포인트를 기록한다 (D-19 재시작 내구성).

    30초 틱은 이 포인터만 보고 실행/전진한다 (Phase 3).
    """
    try:
        stops = await port.get_stops(None, train_no, date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="열차를 찾을 수 없습니다") from exc
    names = [s.name for s in stops]
    try:
        board_idx, alight_idx = route_indexes(names, board_at, alight_at)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # starlette 버전에 따라 상수명이 갈려 숫자로 고정
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    delay = await delay_port.get_delay_minutes(train_no, date)
    points = compute_poll_points(stops, board_idx, alight_idx, delay or 0)
    return to_db(first_poll_at(points, now))


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(
    active_only: bool = True,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> list[SubscriptionOut]:
    sql = "SELECT * FROM subscription WHERE user_id = ?"
    params: list = [user.id]
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY created_at DESC"
    return [_row_to_out(row) for row in conn.execute(sql, params).fetchall()]


@router.post("", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    payload: SubscriptionIn,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
    port: KorailPort = Depends(get_korail_port),
    delay_port: ZeroDelayAdapter = Depends(get_delay_port),
) -> SubscriptionOut:
    now = now_kst()
    next_poll_at = await _compute_next_poll_at(
        port,
        delay_port,
        train_no=payload.train_no,
        date=payload.date,
        board_at=payload.board_at,
        alight_at=payload.alight_at,
        now=now,
    )
    cur = conn.execute(
        "INSERT INTO subscription"
        " (user_id, train_no, date, board_at, alight_at, status, my_car, my_seat_no,"
        "  active, created_at, next_poll_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (
            user.id,
            payload.train_no,
            to_db(payload.date),
            payload.board_at,
            payload.alight_at,
            payload.status.value,
            payload.my_car,
            payload.my_seat_no,
            to_db(now),
            next_poll_at,
        ),
    )
    row = conn.execute("SELECT * FROM subscription WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_out(row)


@router.patch("/{sub_id}", response_model=SubscriptionOut)
def patch_subscription(
    sub_id: int,
    payload: SubscriptionPatch,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> SubscriptionOut:
    row = _load_own(conn, sub_id, user.id)

    new_status = payload.status or SubscriptionStatus(row["status"])
    if new_status is SubscriptionStatus.STANDING:
        # 일어남 — 좌석 정보를 비운다
        my_car, my_seat_no = None, None
    else:
        my_car = payload.my_car if payload.my_car is not None else row["my_car"]
        my_seat_no = payload.my_seat_no if payload.my_seat_no is not None else row["my_seat_no"]
        if my_car is None or not my_seat_no:
            raise HTTPException(
                status_code=422,  # starlette 버전에 따라 상수명이 갈려 숫자로 고정
                detail="SEATED 상태에는 my_car/my_seat_no가 필요합니다",
            )

    seat_changed = (my_car, my_seat_no) != (row["my_car"], row["my_seat_no"])
    status_changed = new_status.value != row["status"]

    # 전이 직후 스냅샷 무효화 (D-16). 해시는 유지한다 —
    # 상태 전이만으로 베이스라인이 재발송되면 소음이다 (D-20).
    snapshot = row["last_cells_snapshot"]
    if seat_changed or status_changed:
        snapshot = None

    conn.execute(
        "UPDATE subscription SET status = ?, my_car = ?, my_seat_no = ?, last_cells_snapshot = ?"
        " WHERE id = ? AND user_id = ?",
        (new_status.value, my_car, my_seat_no, snapshot, sub_id, user.id),
    )
    return _row_to_out(_load_own(conn, sub_id, user.id))


@router.delete("/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(
    sub_id: int,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> Response:
    _load_own(conn, sub_id, user.id)
    # 하드 삭제 대신 비활성화 — 스케줄러는 active만 본다 (알림 자동 중단)
    conn.execute(
        "UPDATE subscription SET active = 0, next_poll_at = NULL WHERE id = ? AND user_id = ?",
        (sub_id, user.id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
