"""MockKorailAdapter — 프로토타입(`seat-matrix.jsx`) 목업 데이터 재현 (PLAN 11절 Phase 1).

Phase 1은 이 어댑터만으로 전체를 관통한다. 실 코레일 호출은 Phase 2.
개발·디버깅 중에도 실 API를 루프로 때리지 않기 위한 기본 어댑터이기도 하다 (CLAUDE.md 10).
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, time, timedelta
from typing import Callable

from app.domain.models import (
    KST,
    KorailCred,
    SeatMap,
    SeatState,
    StopInfo,
    TrainSummary,
)

TRAIN_NO = "1004"
TRAIN_NAME = "ITX-마음"

# 정차역 + 시각표 도착시각(분 단위 오프셋). 첫 역 08:00 기준.
STOPS: tuple[tuple[str, int], ...] = (
    ("천안", 0),
    ("평택", 12),
    ("수원", 26),
    ("안양", 38),
    ("영등포", 48),
    ("서울", 56),
)

# 좌석 × 구간 판매 여부 — 프로토타입 MOCK_RESPONSE.seats와 1:1 (True = 판매됨)
SEAT_CELLS: tuple[tuple[int, str, tuple[bool, ...]], ...] = (
    (3, "5A", (True, True, True, True, True)),
    (3, "5B", (True, True, True, True, False)),
    (3, "6A", (False, False, True, True, True)),
    (3, "6B", (False, False, True, True, False)),
    (3, "7A", (True, True, True, False, False)),
    (3, "7B", (True, True, False, True, True)),
    (3, "8A", (True, False, False, False, False)),
    (3, "8B", (False, False, False, False, False)),
    (3, "9A", (True, True, True, True, True)),
    (3, "9B", (True, True, True, True, True)),
    (4, "1A", (False, False, False, True, True)),
    (4, "1B", (False, False, False, False, False)),
    (4, "2A", (True, True, True, True, False)),
    (4, "2B", (True, True, False, False, False)),
    (4, "3A", (False, True, True, True, True)),
    (4, "3B", (True, True, True, True, True)),
    (4, "4A", (True, True, True, False, True)),
    (4, "4B", (False, False, False, False, True)),
)

FIRST_DEPARTURE = time(8, 0)


class MockKorailAdapter:
    """KorailPort 구현. 어떤 열차번호를 물어도 같은 목업 노선을 돌려준다."""

    #: 화면 배지용 열차명. Phase 2 실어댑터는 열차별 이름을 응답에서 가져온다.
    train_name = TRAIN_NAME

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        # 어댑터는 I/O 계층이라 시계를 가져도 되지만, 테스트를 위해 주입 가능하게 둔다.
        self._clock = clock or (lambda: datetime.now(KST))

    # ── KorailPort ──────────────────────────────────────────────────
    async def search_trains(
        self,
        cred: KorailCred | None,
        d: _date,
        frm: str,
        to: str,
        at: datetime | None = None,
    ) -> list[TrainSummary]:
        stops = self._stops(d)
        names = [s.name for s in stops]
        dep = stops[names.index(frm)] if frm in names else stops[0]
        arr = stops[names.index(to)] if to in names else stops[-1]
        return [
            TrainSummary(
                train_no=TRAIN_NO,
                train_name=TRAIN_NAME,
                date=d,
                dep_station=dep.name,
                arr_station=arr.name,
                dep_time=dep.arrival,
                arr_time=arr.arrival,
            )
        ]

    async def get_stops(self, cred: KorailCred | None, train_no: str, d: _date) -> list[StopInfo]:
        return self._stops(d)

    async def get_seat_map(
        self, cred: KorailCred | None, train_no: str, d: _date, frm: str, to: str
    ) -> SeatMap:
        seg_idx = self._segment_idx(frm, to)
        return SeatMap(
            train_no=train_no,
            date=d,
            frm=frm,
            to=to,
            seats=[
                SeatState(car=car, seat_no=seat_no, sold=cells[seg_idx])
                for car, seat_no, cells in SEAT_CELLS
            ],
            fetched_at=self._clock(),
        )

    # ── 내부 ────────────────────────────────────────────────────────
    def _stops(self, d: _date) -> list[StopInfo]:
        base = datetime.combine(d, FIRST_DEPARTURE, tzinfo=KST)
        return [
            StopInfo(name=name, arrival=base + timedelta(minutes=offset))
            for name, offset in STOPS
        ]

    def _segment_idx(self, frm: str, to: str) -> int:
        names = [name for name, _ in STOPS]
        try:
            i, j = names.index(frm), names.index(to)
        except ValueError as exc:  # pragma: no cover - 목업에 없는 역
            raise ValueError(f"목업 노선에 없는 역이다: {frm} → {to}") from exc
        if j != i + 1:
            raise ValueError(f"인접 구간만 조회한다: {frm} → {to}")
        return i
