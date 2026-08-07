"""MockKorailAdapter — 프로토타입(`seat-matrix.jsx`) 목업 데이터 재현 (PLAN 11절 Phase 1).

Phase 1은 이 어댑터만으로 전체를 관통한다. 실 코레일 호출은 Phase 2.
개발·디버깅 중에도 실 API를 루프로 때리지 않기 위한 기본 어댑터이기도 하다 (CLAUDE.md 10).

열차 선택 화면(D-25)을 눈으로 확정하려면 열차가 한 편이어서는 안 되므로,
**같은 노선을 다른 시각대에 달리는 편성 4개**를 준다. `1004`는 프로토타입과 1:1로 유지하고
나머지는 좌석표를 결정적으로 회전시켜 화면이 편성마다 달라지게 한다.
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
    StationInfo,
    StopInfo,
    TrainSummary,
)

TRAIN_NO = "1004"  # 프로토타입 목업과 1:1인 기준 편성
TRAIN_NAME = "ITX-마음"

# 정차역 + 시각표 도착시각(첫 역 출발 기준 분 오프셋). 전 편성이 같은 노선을 달린다.
# (역명, 도착 오프셋(분), 출발 오프셋(분) — 종착역은 None)
#
# **정차 시간을 담는 것이 목업의 의무다** (→ D-47). 도착과 출발이 같으면 "정차 중"과
# "주행 중"을 가를 수 없고, 그러면 목업이 이슈 #35의 구간(출발한 구간은 팔 수 없다)을
# 통째로 가린다. Phase 1이 목업만으로 관통했던 이유가 그런 은폐였다 (D-31/D-32와 같은 종류).
STOPS: tuple[tuple[str, int, int | None], ...] = (
    ("천안", 0, 3),
    ("평택", 12, 15),
    ("수원", 26, 29),
    ("안양", 38, 41),
    ("영등포", 48, 51),
    ("서울", 56, None),
)

# (열차번호, 열차명, 첫 역 출발시각, 좌석표 회전량)
TRAINS: tuple[tuple[str, str, time, int], ...] = (
    (TRAIN_NO, TRAIN_NAME, time(8, 0), 0),
    ("1008", "ITX-새마을", time(9, 30), 1),
    ("1012", "무궁화호", time(17, 10), 2),
    ("1016", "ITX-마음", time(18, 40), 3),
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


class MockKorailAdapter:
    """KorailPort 구현. 목업 노선 하나를 여러 편성으로 제공한다."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        # 어댑터는 I/O 계층이라 시계를 가져도 되지만, 테스트를 위해 주입 가능하게 둔다.
        self._clock = clock or (lambda: datetime.now(KST))

    # ── KorailPort ──────────────────────────────────────────────────
    async def list_stations(self) -> list[StationInfo]:
        return [StationInfo(name=name) for name, *_ in STOPS]

    async def search_trains(
        self,
        cred: KorailCred | None,
        d: _date,
        frm: str,
        to: str,
        at: datetime | None = None,
    ) -> list[TrainSummary]:
        """`at` 이후 출발하는 편성만, 출발 시각 오름차순 (D-25)."""
        found: list[TrainSummary] = []
        for train_no, train_name, _, _ in TRAINS:
            stops = self._stops(train_no, d)
            names = [s.name for s in stops]
            if frm not in names or to not in names:
                continue
            i, j = names.index(frm), names.index(to)
            if i >= j:
                continue
            dep, arr = stops[i], stops[j]
            if at is not None and dep.arrival < at:
                continue
            found.append(
                TrainSummary(
                    train_no=train_no,
                    train_name=train_name,
                    date=d,
                    dep_station=dep.name,
                    arr_station=arr.name,
                    dep_time=dep.arrival,
                    arr_time=arr.arrival,
                )
            )
        return sorted(found, key=lambda t: t.dep_time)

    async def get_train_name(self, train_no: str, d: _date) -> str | None:
        return self._train(train_no)[1]

    async def get_stops(self, cred: KorailCred | None, train_no: str, d: _date) -> list[StopInfo]:
        return self._stops(train_no, d)

    async def get_seat_map(
        self, cred: KorailCred | None, train_no: str, d: _date, frm: str, to: str
    ) -> SeatMap:
        seg_idx = self._segment_idx(frm, to)
        shift = self._train(train_no)[3]
        return SeatMap(
            train_no=train_no,
            date=d,
            frm=frm,
            to=to,
            seats=[
                SeatState(car=car, seat_no=seat_no, sold=self._rotate(cells, shift)[seg_idx])
                for car, seat_no, cells in SEAT_CELLS
            ],
            fetched_at=self._clock(),
        )

    # ── 내부 ────────────────────────────────────────────────────────
    def _train(self, train_no: str) -> tuple[str, str, time, int]:
        for train in TRAINS:
            if train[0] == train_no:
                return train
        raise ValueError(f"목업에 없는 열차번호다: {train_no}")

    def _stops(self, train_no: str, d: _date) -> list[StopInfo]:
        base = datetime.combine(d, self._train(train_no)[2], tzinfo=KST)
        return [
            StopInfo(
                name=name,
                arrival=base + timedelta(minutes=arr),
                departure=None if dep is None else base + timedelta(minutes=dep),
            )
            for name, arr, dep in STOPS
        ]

    @staticmethod
    def _rotate(cells: tuple[bool, ...], shift: int) -> tuple[bool, ...]:
        """편성별 좌석표 변형. 난수가 아니라 회전이라 **결정적**이다."""
        if shift == 0:
            return cells
        k = shift % len(cells)
        return cells[k:] + cells[:k]

    def _segment_idx(self, frm: str, to: str) -> int:
        names = [name for name, *_ in STOPS]
        try:
            i, j = names.index(frm), names.index(to)
        except ValueError as exc:  # pragma: no cover - 목업에 없는 역
            raise ValueError(f"목업 노선에 없는 역이다: {frm} → {to}") from exc
        if j != i + 1:
            raise ValueError(f"인접 구간만 조회한다: {frm} → {to}")
        return i
