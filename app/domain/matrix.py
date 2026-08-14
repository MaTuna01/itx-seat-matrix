"""매트릭스 병합 (PLAN.md 5절, D-18). 순수 함수만.

조회(병렬 호출·Semaphore·지터)는 도메인의 일이 아니다 →
`app/adapters/seatmap_fetcher.py`가 담당하고, 여기서는 그 결과를 병합만 한다.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime

from app.domain.models import SeatMap, SeatMatrix, SeatRow, Segment, seat_key

# 조회하지 않은 구간(지나온 구간·탑승 전 구간)의 셀 채움값.
# 판정은 실효 시작 인덱스부터만 읽고, 화면은 `current_seg_idx` 이전을 흐리게 처리한다.
# 보수적으로 '판매됨'을 채운다 — 이 값이 판정에 새어들어가도 좌석을 권하지는 않는다.
UNQUERIED_CELL = True


def build_segments(stops: list[str]) -> list[Segment]:
    """정차역 N개 → 인접 구간 N-1개 (PLAN 5절 1)."""
    return [
        Segment(from_station=frm, to_station=to, idx=i)
        for i, (frm, to) in enumerate(zip(stops, stops[1:]))
    ]


def route_indexes(names: list[str], board_at: str, alight_at: str) -> tuple[int, int]:
    """노선 정차역 이름 목록에서 승차/하차 인덱스를 찾는다 (D-18: 인덱스는 전체 `stops` 기준).

    방향(상·하행)이라는 개념은 도메인에 따로 없다 — "이 열차의 stops 안에서
    승차가 하차보다 앞인가"가 방향의 전부다. 구간 스왑 UX가 기대는 안전장치이므로
    api 두 곳(subscriptions/trains)이 이 함수 하나를 공유한다.

    - 역이 노선에 없으면 LookupError (api는 404로 매핑)
    - 승차가 하차보다 뒤거나 같은 역이면 ValueError (api는 422로 매핑)
    """
    if board_at not in names or alight_at not in names:
        raise LookupError("노선에 없는 역입니다")
    board_idx, alight_idx = names.index(board_at), names.index(alight_at)
    if board_idx >= alight_idx:
        raise ValueError("탑승역이 하차역보다 뒤에 있습니다")
    return board_idx, alight_idx


def effective_start_idx(sellable_seg_idx: int, board_idx: int) -> int:
    """실효 시작 = max(팔 수 있는 첫 구간, 탑승역) (D-18 인덱스 규칙, D-47).

    모든 인덱스는 **전체 노선 `stops` 기준**이다. 탑승역 이전 구간은
    열차가 어디를 달리든 관심 밖.

    첫 인자는 **열차의 현재 위치가 아니다.** 위치를 넣으면 이미 출발해 팔 수 없는 구간이
    실효 시작이 되어 그 열 전체가 '판매됨'으로 채워진다 (이슈 #35 → D-47).
    """
    return max(sellable_seg_idx, board_idx)


def query_range(sellable_seg_idx: int, board_idx: int, alight_idx: int) -> tuple[int, int]:
    """실제로 조회할 구간 인덱스 범위 `[start, end)` (PLAN 5절 2, D-17).

    지나온 구간·탑승 전 구간은 판정·표시 모두에 불필요하므로 호출하지 않는다.

    **`start == end`(빈 범위)도 정상 결과다** (→ D-47). 이용 구간의 마지막 구간을 달리는
    중이면 팔 수 있는 구간이 하나도 남지 않는다. 예전처럼 `alight_idx - 1`로 되돌리면
    바로 그 '팔 수 없는 구간'을 조회하게 되어 매진 오판이 되살아난다. 호출은 0회가 되고,
    `build_verdict`가 이 상태를 `decision_needed=False`로 답한다.
    """
    if not (0 <= board_idx < alight_idx):
        raise ValueError(f"구간 인덱스가 올바르지 않다: board={board_idx}, alight={alight_idx}")
    start = min(effective_start_idx(sellable_seg_idx, board_idx), alight_idx)
    return start, alight_idx


def snapshot_gap_range(
    current_seg_idx: int, sellable_seg_idx: int, board_idx: int, alight_idx: int
) -> tuple[int, int]:
    """스냅샷으로 보여줄 갭 구간 `[start, end)` (→ D-57). 빈 범위일 수 있다.

    갭 = **지금 타고 있는데 더는 팔 수 없는 구간** = `[열차 위치, 실효 시작)`.
    이용 구간으로 클램프한다 — 탑승 전 구간(board 이전)과 하차 이후는 관심 밖이고,
    완전히 지나온 구간은 기존 회색(past) 표시를 유지한다.

    - 정차 중(위치 == 실효 시작)이면 빈 범위 — 스냅샷 없이 전부 실시간
    - 마지막 구간 주행 중이면 `[alight-1, alight)` — `decision_needed=False`여도
      이 범위의 스냅샷이 있으면 화면은 매트릭스를 그린다

    표시 전용이다. 판정·알림·추천은 이 범위를 모른다 (#35 재발 방지).
    """
    if not (0 <= board_idx < alight_idx):
        raise ValueError(f"구간 인덱스가 올바르지 않다: board={board_idx}, alight={alight_idx}")
    start = min(max(current_seg_idx, board_idx), alight_idx)
    end = min(max(sellable_seg_idx, board_idx), alight_idx)
    return start, max(start, end)


def merge_seat_maps(
    *,
    train_no: str,
    date: _date,
    stops: list[str],
    seat_maps: dict[int, SeatMap],
    start_idx: int,
    end_idx: int,
    fetched_at: datetime,
    failed_seg_idxs: list[int] | None = None,
) -> SeatMatrix:
    """구간별 좌석맵을 좌석 키로 조인해 매트릭스를 만든다 (PLAN 5절 4).

    좌석 유니버스 (D-18):
    - 유니버스 = **조회한 전 구간 응답의 합집합**
    - 특정 구간 응답에 없는 좌석 → 그 구간은 **판매됨(True)** 으로 채운다

    Phase 0 항목 6 실측 결과 코레일 응답은 '전체 좌석+상태'라 실제로는 전 구간
    좌석 집합이 동일하다 → 이 규칙은 그 경우 단순 조인과 동일하게 동작한다.
    응답이 부분집합으로 바뀌어도 조용히 틀리지 않도록 규칙 자체는 유지한다.

    `failed_seg_idxs`는 **조회에 실패한 구간**이다 (→ D-48). 셀은 채움값(판매됨)이 되지만
    그 사실을 매트릭스가 들고 다녀야 화면·판정이 매진과 구분할 수 있다.
    """
    seg_count = len(stops) - 1
    if not (0 <= start_idx <= end_idx <= seg_count):
        raise ValueError(f"조회 범위가 올바르지 않다: [{start_idx}, {end_idx}) / 구간 {seg_count}개")

    failed = sorted(set(failed_seg_idxs or ()))

    # 유니버스 = 합집합. 좌석 메타(car, seat_no)도 함께 보관한다.
    universe: dict[str, tuple[int, str]] = {}
    sold_by_seg: dict[int, dict[str, bool]] = {}
    for seg_idx in range(start_idx, end_idx):
        seat_map = seat_maps.get(seg_idx)
        if seat_map is None:
            if seg_idx in failed:
                continue  # 조회 실패 — 채움값(판매됨)으로 남는다. 아래에서 표시로 구분한다
            raise ValueError(f"구간 {seg_idx}의 좌석맵이 없다 (조회 범위 불일치)")
        by_key: dict[str, bool] = {}
        for seat in seat_map.seats:
            key = seat_key(seat.car, seat.seat_no)
            universe.setdefault(key, (seat.car, seat.seat_no))
            by_key[key] = seat.sold
        sold_by_seg[seg_idx] = by_key

    rows: list[SeatRow] = []
    for key, (car, seat_no) in universe.items():
        cells = [UNQUERIED_CELL] * seg_count
        for seg_idx in range(start_idx, end_idx):
            if seg_idx not in sold_by_seg:
                continue  # 조회 실패 구간 — 채움값 유지 (D-48)
            cells[seg_idx] = sold_by_seg[seg_idx].get(key, True)  # 부재 = 판매 (D-18)
        rows.append(SeatRow(car=car, seat_no=seat_no, cells=cells))

    rows.sort(key=lambda r: (r.car, r.seat_no))
    return SeatMatrix(
        train_no=train_no,
        date=date,
        stops=stops,
        seats=rows,
        fetched_at=fetched_at,
        queried_from_idx=start_idx,
        queried_to_idx=end_idx,
        failed_seg_idxs=[i for i in failed if start_idx <= i < end_idx],
    )
