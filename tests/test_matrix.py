"""매트릭스 병합/조인 + 부분 구간 + 부재 추론 유니버스 (PLAN 13절, D-18)."""

from __future__ import annotations

import pytest

from app.domain.matrix import (
    UNQUERIED_CELL,
    build_segments,
    effective_start_idx,
    merge_seat_maps,
    query_range,
)
from app.domain.models import SeatMap, SeatState
from tests.conftest import RIDE_DATE, STOPS, at


def seat_map(frm: str, to: str, sold: dict[str, bool]) -> SeatMap:
    return SeatMap(
        train_no="1004",
        date=RIDE_DATE,
        frm=frm,
        to=to,
        seats=[
            SeatState(car=int(key.split("-")[0]), seat_no=key.split("-")[1], sold=value)
            for key, value in sold.items()
        ],
        fetched_at=at(8, 14),
    )


def test_정차역_N개는_인접_구간_N_1개가_된다():
    segments = build_segments(STOPS)
    assert len(segments) == len(STOPS) - 1
    assert (segments[0].from_station, segments[0].to_station, segments[0].idx) == ("천안", "평택", 0)
    assert segments[-1].to_station == "서울"


class TestQueryRange:
    def test_실효_시작은_max_현재구간_탑승역(self):
        assert effective_start_idx(0, 2) == 2
        assert effective_start_idx(3, 2) == 3

    def test_조회_범위는_실효_시작부터_하차역까지(self):
        assert query_range(current_seg_idx=1, board_idx=0, alight_idx=5) == (1, 5)
        assert query_range(current_seg_idx=0, board_idx=2, alight_idx=4) == (2, 4)

    def test_열차가_하차역에_거의_다다랐으면_마지막_한_구간(self):
        assert query_range(current_seg_idx=9, board_idx=0, alight_idx=5) == (4, 5)

    def test_잘못된_구간은_거부(self):
        with pytest.raises(ValueError):
            query_range(current_seg_idx=0, board_idx=4, alight_idx=2)


class TestMerge:
    def test_전체_좌석_응답은_단순_조인이_된다(self):
        """Phase 0 항목 6 실측: 응답이 전체 좌석+상태 → 구간별 좌석 집합이 동일하다."""
        maps = {
            0: seat_map("천안", "평택", {"3-7A": False, "4-1B": True}),
            1: seat_map("평택", "수원", {"3-7A": True, "4-1B": True}),
        }
        matrix = merge_seat_maps(
            train_no="1004", date=RIDE_DATE, stops=STOPS, seat_maps=maps,
            start_idx=0, end_idx=2, fetched_at=at(8, 14),
        )
        by_key = {row.key: row.cells for row in matrix.seats}
        assert by_key["3-7A"][:2] == [False, True]
        assert by_key["4-1B"][:2] == [True, True]

    def test_조회하지_않은_구간은_채움값이다(self):
        maps = {2: seat_map("수원", "안양", {"3-7A": False})}
        matrix = merge_seat_maps(
            train_no="1004", date=RIDE_DATE, stops=STOPS, seat_maps=maps,
            start_idx=2, end_idx=3, fetched_at=at(8, 14),
        )
        cells = matrix.seats[0].cells
        assert len(cells) == len(STOPS) - 1
        assert cells[2] is False
        assert cells[0] is UNQUERIED_CELL and cells[4] is UNQUERIED_CELL
        assert (matrix.queried_from_idx, matrix.queried_to_idx) == (2, 3)

    def test_유니버스는_전_구간_응답의_합집합이고_부재는_판매다(self):
        """응답이 '구매 가능 좌석만'으로 바뀌어도 조용히 틀리지 않는다 (D-18)."""
        maps = {
            0: seat_map("천안", "평택", {"3-7A": False, "4-1B": False}),
            1: seat_map("평택", "수원", {"3-7A": False}),  # 4-1B가 사라졌다
        }
        matrix = merge_seat_maps(
            train_no="1004", date=RIDE_DATE, stops=STOPS, seat_maps=maps,
            start_idx=0, end_idx=2, fetched_at=at(8, 14),
        )
        by_key = {row.key: row.cells for row in matrix.seats}
        assert by_key["4-1B"][:2] == [False, True]  # 부재 = 그 구간 판매

    def test_좌석은_호차_좌석번호_순으로_정렬된다(self):
        maps = {0: seat_map("천안", "평택", {"4-1B": False, "3-7A": False, "3-5A": False})}
        matrix = merge_seat_maps(
            train_no="1004", date=RIDE_DATE, stops=STOPS, seat_maps=maps,
            start_idx=0, end_idx=1, fetched_at=at(8, 14),
        )
        assert [row.key for row in matrix.seats] == ["3-5A", "3-7A", "4-1B"]

    def test_조회_범위에_구멍이_있으면_거부한다(self):
        maps = {0: seat_map("천안", "평택", {"3-7A": False})}
        with pytest.raises(ValueError):
            merge_seat_maps(
                train_no="1004", date=RIDE_DATE, stops=STOPS, seat_maps=maps,
                start_idx=0, end_idx=2, fetched_at=at(8, 14),
            )


async def test_목업_어댑터_전체_흐름():
    """Mock 어댑터 → 병렬 조회 → 병합까지 관통 (Phase 1 스모크)."""
    from app.adapters.korail_mock import MockKorailAdapter
    from app.adapters.seatmap_fetcher import fetch_matrix

    port = MockKorailAdapter()
    stops = [s.name for s in await port.get_stops(None, "1004", RIDE_DATE)]
    matrix = await fetch_matrix(
        port, None, "1004", RIDE_DATE, stops, 1, 5, now=at(8, 14), jitter=None
    )
    assert len(matrix.seats) == 18
    by_key = {row.key: row.cells for row in matrix.seats}
    # 프로토타입 목업의 3-7A: [T, T, T, F, F]
    assert by_key["3-7A"][1:] == [True, True, False, False]
