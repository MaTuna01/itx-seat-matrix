"""판정 로직 (PLAN.md 5절). 순수 함수 — 외부 의존 없음, 테스트 필수 (원칙 5).

**틀려도 조용히 틀리는 유일한 지점**이다. 어댑터가 깨지면 에러가 나지만,
여기가 틀리면 "빈 줄 알고 앉았다가 쫓겨난다".
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.matrix import effective_start_idx
from app.domain.models import (
    SeatMatrix,
    SeatRecommendation,
    SeatRow,
    SubscriptionStatus,
    Verdict,
    seat_key,
)


@dataclass(frozen=True)
class RankingConfig:
    """추천 랭킹 손잡이. 실사용 후 조정 예정이라 설정값으로 격리한다 (D-17)."""

    max_recommendations: int = 3  # 화면·다이제스트 상한 (D-20)
    prefer_same_car: bool = True  # SEATED: 내 호차 근접순으로 이동 거리 최소화


DEFAULT_RANKING = RankingConfig()


@dataclass(frozen=True)
class EnrichedSeat:
    """좌석 + 파생 판정값. 매트릭스 렌더·추천 랭킹이 공유한다."""

    car: int
    seat_no: str
    cells: list[bool]
    clear_until_idx: int
    clear_all: bool

    @property
    def key(self) -> str:
        return seat_key(self.car, self.seat_no)


def clear_until(cells: list[bool], start_idx: int, alight_idx: int) -> int:
    """실효 시작 구간부터 **연속으로** 비어있는 마지막 역 인덱스.

    시작 구간이 이미 판매면 `start_idx`를 그대로 반환한다 (= 앉을 수 없음).
    """
    until = start_idx
    for i in range(start_idx, alight_idx):
        if cells[i]:
            break
        until = i + 1
    return until


def enrich_seats(
    seats: list[SeatRow], start_idx: int, alight_idx: int
) -> list[EnrichedSeat]:
    out: list[EnrichedSeat] = []
    for seat in seats:
        until = clear_until(seat.cells, start_idx, alight_idx)
        out.append(
            EnrichedSeat(
                car=seat.car,
                seat_no=seat.seat_no,
                cells=seat.cells,
                clear_until_idx=until,
                clear_all=until >= alight_idx,
            )
        )
    return out


def rank_seats(
    seats: list[EnrichedSeat],
    *,
    status: SubscriptionStatus,
    my_car: int | None,
    config: RankingConfig = DEFAULT_RANKING,
) -> list[EnrichedSeat]:
    """추천 정렬 (PLAN 5절 판정 로직).

    - 공통 1순위: `clear_until` 내림차순 (오래 앉을 수 있는 좌석 우선)
    - SEATED: 동률이면 **현재 호차 근접순** (이동 거리 최소화)
    - STANDING: 동률이면 호차 오름차순 (기준이 될 내 호차가 없다)
    """
    same_car = config.prefer_same_car and status is SubscriptionStatus.SEATED and my_car is not None

    def sort_key(seat: EnrichedSeat) -> tuple:
        proximity = abs(seat.car - my_car) if same_car else seat.car  # type: ignore[operator]
        return (-seat.clear_until_idx, proximity, seat.car, seat.seat_no)

    return sorted(seats, key=sort_key)


def build_verdict(
    *,
    matrix: SeatMatrix,
    status: SubscriptionStatus,
    board_idx: int,
    alight_idx: int,
    current_seg_idx: int,
    my_car: int | None = None,
    my_seat_no: str | None = None,
    config: RankingConfig = DEFAULT_RANKING,
) -> Verdict:
    """매트릭스 + 구독 상태 → 판정 (PLAN 5절, D-15/D-18).

    실효 시작 = `max(current_seg_idx, board_idx)`. 인덱스는 전부 전체 노선 기준.
    """
    start_idx = min(effective_start_idx(current_seg_idx, board_idx), alight_idx - 1)
    stops = matrix.stops
    enriched = enrich_seats(matrix.seats, start_idx, alight_idx)

    my_key = seat_key(my_car, my_seat_no) if my_car is not None and my_seat_no else None
    candidates = [s for s in enriched if s.key != my_key]

    clear_all_seats = [s for s in candidates if s.clear_all]
    pool = clear_all_seats if clear_all_seats else candidates
    ranked = rank_seats(pool, status=status, my_car=my_car, config=config)
    move_to = [
        SeatRecommendation(
            car=s.car,
            seat_no=s.seat_no,
            clear_until_idx=s.clear_until_idx,
            clear_all=s.clear_all,
        )
        # 시작 구간부터 이미 팔린 좌석은 추천이 아니다
        for s in ranked
        if s.clear_until_idx > start_idx
    ][: config.max_recommendations]

    # 내 자리를 포함해 남은 구간에 앉을 수 있는 좌석이 하나도 없으면 환승 판단이 필요하다
    all_sold = all(s.clear_until_idx <= start_idx for s in enriched)

    my_seat_status = None
    my_seat_sold_from = None
    my_seat_clear_until_idx = None

    if status is SubscriptionStatus.SEATED:
        if my_key is None:
            # SEATED인데 좌석 정보가 없다 — API가 422로 막지만 도메인은 죽지 않는다
            my_seat_status = "UNKNOWN"
        else:
            mine = next((s for s in enriched if s.key == my_key), None)
            if mine is None:
                # 내 좌석 부재 규칙 (D-18): 잔여 전 구간 판매로 간주.
                # 이 규칙이 없으면 KeyError 아니면 UNKNOWN으로 조용히 빠진다.
                my_seat_status = "SOLD_FROM"
                my_seat_clear_until_idx = start_idx
                my_seat_sold_from = (
                    stops[start_idx + 1] if start_idx + 1 < len(stops) else stops[alight_idx]
                )
            else:
                my_seat_clear_until_idx = mine.clear_until_idx
                if mine.clear_all:
                    my_seat_status = "CLEAR_ALL"
                else:
                    my_seat_status = "SOLD_FROM"
                    my_seat_sold_from = stops[mine.clear_until_idx]

    return Verdict(
        sub_status=status,
        my_seat_status=my_seat_status,
        my_seat_sold_from=my_seat_sold_from,
        my_seat_clear_until_idx=my_seat_clear_until_idx,
        move_to=move_to,
        all_sold_after_current=all_sold,
        current_seg_idx=start_idx,
    )
