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
    # 남은 구간 안에서 가장 긴 연속 빈 구간 (→ D-46). 지금 앉을 수 있으면
    # best_from_idx == 실효 시작이고, 그렇지 않으면 "그 역부터 앉을 수 있다"는 뜻이다
    best_from_idx: int
    best_until_idx: int

    @property
    def key(self) -> str:
        return seat_key(self.car, self.seat_no)

    @property
    def best_len(self) -> int:
        return self.best_until_idx - self.best_from_idx


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


def longest_free_run(cells: list[bool], start_idx: int, alight_idx: int) -> tuple[int, int]:
    """`[start_idx, alight_idx)` 안에서 **가장 긴 연속 빈 구간** `(from, until)` (→ D-46).

    `until`은 `clear_until`과 같은 의미의 역 인덱스다 (구간 i가 비면 `until = i + 1`).
    빈 구간이 하나도 없으면 `(start_idx, start_idx)` — 길이 0이다.

    **길이가 같으면 더 이른 쪽을 고른다.** 같은 값이면 빨리 앉는 편이 낫고, 멀리 있는
    구간일수록 그때까지 그 자리가 남아 있을 가능성이 낮다 (5절 "빈 좌석 ≠ 착석 가능"의
    한계는 시간이 갈수록 커진다).
    """
    best_from, best_until = start_idx, start_idx
    run_from: int | None = None
    for i in range(start_idx, alight_idx):
        if cells[i]:
            run_from = None
            continue
        if run_from is None:
            run_from = i
        if (i + 1) - run_from > best_until - best_from:
            best_from, best_until = run_from, i + 1
    return best_from, best_until


def enrich_seats(
    seats: list[SeatRow], start_idx: int, alight_idx: int
) -> list[EnrichedSeat]:
    out: list[EnrichedSeat] = []
    for seat in seats:
        until = clear_until(seat.cells, start_idx, alight_idx)
        best_from, best_until = longest_free_run(seat.cells, start_idx, alight_idx)
        out.append(
            EnrichedSeat(
                car=seat.car,
                seat_no=seat.seat_no,
                cells=seat.cells,
                clear_until_idx=until,
                clear_all=until >= alight_idx,
                best_from_idx=best_from,
                best_until_idx=best_until,
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


def rank_later_seats(
    seats: list[EnrichedSeat],
    *,
    status: SubscriptionStatus,
    my_car: int | None,
    config: RankingConfig = DEFAULT_RANKING,
) -> list[EnrichedSeat]:
    """지연 착석 좌석 정렬 — **가장 길게 앉아 갈 수 있는 좌석 우선** (→ D-46).

    `rank_seats`와 기준이 다르다. 저쪽은 "지금부터 어디까지"라 `clear_until` 하나로
    충분하지만, 여기는 시작 시점이 좌석마다 다르므로 **구간 길이**로 비교해야 한다.
    동률이면 **일찍 앉을 수 있는 쪽**이 위다 (`best_from_idx` 오름차순).
    """
    same_car = config.prefer_same_car and status is SubscriptionStatus.SEATED and my_car is not None

    def sort_key(seat: EnrichedSeat) -> tuple:
        proximity = abs(seat.car - my_car) if same_car else seat.car  # type: ignore[operator]
        return (-seat.best_len, seat.best_from_idx, proximity, seat.car, seat.seat_no)

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
            clear_from_idx=start_idx,  # 지금 앉을 수 있다
            clear_until_idx=s.clear_until_idx,
            clear_all=s.clear_all,
        )
        # 시작 구간부터 이미 팔린 좌석은 **지금** 앉을 수 있는 좌석이 아니다.
        # 그런 좌석 중 뒤 구간이 비는 것은 아래 move_to_later로 간다 (→ D-46)
        for s in ranked
        if s.clear_until_idx > start_idx
    ][: config.max_recommendations]

    # 지금은 못 앉지만 몇 정거장 뒤부터 앉을 수 있는 좌석 (→ D-46).
    # 퇴근길처럼 탑승 구간만 매진일 때 위 목록은 비고 이쪽만 찬다.
    later_pool = [
        s for s in candidates if s.clear_until_idx <= start_idx and s.best_len > 0
    ]
    move_to_later = [
        SeatRecommendation(
            car=s.car,
            seat_no=s.seat_no,
            clear_from_idx=s.best_from_idx,
            clear_until_idx=s.best_until_idx,
            clear_all=s.best_until_idx >= alight_idx,
        )
        for s in rank_later_seats(later_pool, status=status, my_car=my_car, config=config)
    ][: config.max_recommendations]

    # 내 자리를 포함해 남은 구간 [start, alight)에 **빈 셀이 하나도 없을 때만** 매진이다.
    #
    # `clear_until` 기준으로 판단하면 안 된다. 그 값은 시작 구간부터 **연속으로** 빈 구간만
    # 세므로, 시작 구간이 팔려 있으면 뒤가 아무리 비어 있어도 start_idx를 그대로 돌려준다.
    # 그러면 "시작 구간 매진"이 "남은 전 구간 매진"으로 뒤집히고, 화면은 환승을 권하고
    # ALL_SOLD 푸시가 나간다 — 정작 몇 정거장 뒤부터는 앉아서 갈 수 있는데도.
    # 퇴근길(영등포→천안, 영등포-수원만 매진)에서 실제로 겪었다 (→ D-45).
    all_sold = all(all(seat.cells[start_idx:alight_idx]) for seat in enriched)

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
        move_to_later=move_to_later,
        all_sold_after_current=all_sold,
        current_seg_idx=start_idx,
    )
