"""도메인 모델 (PLAN.md 5절).

이 모듈은 순수 데이터 정의만 담는다. I/O·DB·네트워크 금지.

공통 구현 규칙 (PLAN 3절, D-21):
- 모든 datetime은 **KST aware**. naive datetime은 검증 단계에서 거부한다.
- `date`는 열차 **운행일** 기준.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, BeforeValidator, Field

KST = ZoneInfo("Asia/Seoul")


def ensure_kst(value: datetime) -> datetime:
    """KST aware datetime을 보장한다. naive면 거부 (D-21).

    다른 시간대의 aware datetime은 KST로 변환한다 (거부하면 클라이언트가 보낸
    UTC 문자열을 전부 400으로 떨구게 되는데, 그건 규칙의 의도가 아니다).
    """
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        raise ValueError("naive datetime은 허용하지 않는다 (KST aware 필수, PLAN 3절)")
    return value.astimezone(KST)


KstDatetime = Annotated[datetime, BeforeValidator(ensure_kst)]


def seat_key(car: int, seat_no: str) -> str:
    """좌석 조인 키. 매트릭스 병합·판정·알림이 전부 이 키를 쓴다."""
    return f"{car}-{seat_no}"


# ── 사용자 ──────────────────────────────────────────────────────────
class User(BaseModel):
    id: int
    email: str
    display_name: str
    created_at: KstDatetime
    # korail_id / korail_pw_enc / discord_webhook_enc 는 DB에만 둔다.
    # API 응답에 절대 노출하지 않는다 (PLAN 6절, CLAUDE.md 절대규칙 9).


class KorailCred(BaseModel):
    """코레일 자격증명. Phase 0 결과 '로그인 필수 + 본계정' 확정 (D-22).

    Phase 1의 Mock 어댑터는 이 값을 사용하지 않는다.
    """

    korail_id: str
    korail_pw: str


# ── 구독 상태 (D-15) ─────────────────────────────────────────────────
class SubscriptionStatus(str, Enum):
    STANDING = "STANDING"  # 입석 — 앉을 자리를 찾는 중
    SEATED = "SEATED"  # 착석 — my_car / my_seat_no 필수


# ── 어댑터 경유 원시 데이터 ───────────────────────────────────────────
class StopInfo(BaseModel):
    """정차역 1개. `arrival`은 시각표 도착시각(KST aware).

    실효 도착시각 = arrival + 지연분 (PLAN 9절). 지연 보정은 domain/timeline.py가 한다.
    """

    name: str
    arrival: KstDatetime
    departure: KstDatetime | None = None


class SeatState(BaseModel):
    car: int
    seat_no: str
    sold: bool  # True = 판매됨(앉을 수 없음)

    @property
    def key(self) -> str:
        return seat_key(self.car, self.seat_no)


class SeatMap(BaseModel):
    """특정 인접 구간 1개의 좌석별 판매 여부 (KorailPort.get_seat_map 반환)."""

    train_no: str
    date: _date
    frm: str
    to: str
    seats: list[SeatState]
    fetched_at: KstDatetime


class TrainSummary(BaseModel):
    """열차 선택 화면용 요약 (GET /api/trains/search)."""

    train_no: str
    train_name: str
    date: _date
    dep_station: str
    arr_station: str
    dep_time: KstDatetime
    arr_time: KstDatetime


# ── 좌석 매트릭스 ────────────────────────────────────────────────────
class Segment(BaseModel):
    from_station: str
    to_station: str
    idx: int


class SeatRow(BaseModel):
    car: int
    seat_no: str
    cells: list[bool]  # 구간별 판매 여부, len == len(stops) - 1

    @property
    def key(self) -> str:
        return seat_key(self.car, self.seat_no)


class SeatMatrix(BaseModel):
    train_no: str
    date: _date
    stops: list[str]  # 조회로 파생된 전체 노선 정차역 (순서 보장, D-18)
    seats: list[SeatRow]
    fetched_at: KstDatetime
    # 실제 조회한 구간 범위 [start_idx, end_idx). 범위 밖 셀은 채움값이다 (matrix.py 참고)
    queried_from_idx: int
    queried_to_idx: int


class SeatRecommendation(BaseModel):
    car: int
    seat_no: str
    clear_until_idx: int
    clear_all: bool

    @property
    def key(self) -> str:
        return seat_key(self.car, self.seat_no)


class Verdict(BaseModel):
    sub_status: SubscriptionStatus
    # ── SEATED일 때만 채워짐, STANDING이면 None ──
    my_seat_status: Literal["CLEAR_ALL", "SOLD_FROM", "UNKNOWN"] | None = None
    my_seat_sold_from: str | None = None
    my_seat_clear_until_idx: int | None = None
    # ── 공통 ──
    move_to: list[SeatRecommendation] = Field(default_factory=list)
    all_sold_after_current: bool = False
    current_seg_idx: int


# ── 알림 (PLAN 8절, D-16) ────────────────────────────────────────────
class AlertKind(str, Enum):
    """5종 고정. 늘리지 않는다 (PLAN 8절 '이것만. 늘리지 말 것')."""

    SEATS_AVAILABLE = "SEATS_AVAILABLE"  # [입석] 착석 가능 좌석 다이제스트
    MY_SEAT_SOLD = "MY_SEAT_SOLD"  # [착석] 내 자리가 잔여 구간 내 판매됨
    SEAT_EXTENDED = "SEAT_EXTENDED"  # [착석] 내 자리 이용 가능 구간 연장
    ALL_SOLD = "ALL_SOLD"  # [공통] 잔여 0 → 환승 판단 필요
    FETCH_FAILED = "FETCH_FAILED"  # [공통] 한 조회 시점 내 3회 실패


class Alert(BaseModel):
    kind: AlertKind
    title: str
    body: str
    subscription_id: int
