"""구간별 마지막 성공 조회 스냅샷 (→ D-57).

핵심은 두 가지다:
1. **역행 방지** — 화면 조회와 스케줄러 폴이 경합해도 더 오래된 관측이
   더 새로운 관측을 덮지 않는다.
2. **빈 좌석맵(전 좌석 판매)도 기록된다** — sellable 범위 안의 빈 응답은
   실패가 아니라 데이터다 (D-36).

시간은 전부 fetched_at 주입 — sleep/실제 시계 금지 (CLAUDE.md).
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime

import pytest

from app.domain.models import KST, SeatMap, SeatState
from app.storage.db import connect, init_db
from app.storage.seat_snapshot import (
    SqliteSeatSnapshotStore,
    load,
    purge_before,
    record,
)

RIDE_DATE = _date(2026, 8, 5)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 5, hour, minute, tzinfo=KST)


def make_map(frm: str, to: str, *, sold: bool, fetched_at: datetime) -> SeatMap:
    return SeatMap(
        train_no="1004",
        date=RIDE_DATE,
        frm=frm,
        to=to,
        seats=[SeatState(car=3, seat_no="7A", sold=sold)],
        fetched_at=fetched_at,
    )


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "snap.db"
    init_db(path)
    c = connect(path)
    try:
        yield c
    finally:
        c.close()


class TestRecordLoad:
    def test_기록하고_다시_읽는다(self, conn):
        record(conn, make_map("천안", "평택", sold=False, fetched_at=at(7, 11)))
        got = load(conn, "1004", RIDE_DATE, "천안", "평택")
        assert got is not None
        assert got.seats[0].sold is False
        assert got.fetched_at == at(7, 11)

    def test_없으면_None(self, conn):
        assert load(conn, "1004", RIDE_DATE, "천안", "평택") is None

    def test_더_새로운_관측이_덮는다(self, conn):
        record(conn, make_map("천안", "평택", sold=False, fetched_at=at(7, 8)))
        record(conn, make_map("천안", "평택", sold=True, fetched_at=at(7, 11)))
        got = load(conn, "1004", RIDE_DATE, "천안", "평택")
        assert got.seats[0].sold is True
        assert got.fetched_at == at(7, 11)

    def test_더_오래된_관측은_덮지_못한다(self, conn):
        # 스케줄러(07:11)와 화면(07:08 캐시 경유 늦은 flush)이 경합해도 역행 없음
        record(conn, make_map("천안", "평택", sold=True, fetched_at=at(7, 11)))
        record(conn, make_map("천안", "평택", sold=False, fetched_at=at(7, 8)))
        got = load(conn, "1004", RIDE_DATE, "천안", "평택")
        assert got.seats[0].sold is True
        assert got.fetched_at == at(7, 11)

    def test_빈_좌석맵도_기록된다(self, conn):
        # sellable 범위 안의 빈 응답 = 전 좌석 판매 (D-36). 실패가 아니라 데이터다
        empty = SeatMap(
            train_no="1004", date=RIDE_DATE, frm="천안", to="평택",
            seats=[], fetched_at=at(7, 11),
        )
        record(conn, empty)
        got = load(conn, "1004", RIDE_DATE, "천안", "평택")
        assert got is not None
        assert got.seats == []

    def test_구간_키가_다르면_별개_항목(self, conn):
        record(conn, make_map("천안", "평택", sold=False, fetched_at=at(7, 11)))
        record(conn, make_map("평택", "수원", sold=True, fetched_at=at(7, 25)))
        assert load(conn, "1004", RIDE_DATE, "천안", "평택").seats[0].sold is False
        assert load(conn, "1004", RIDE_DATE, "평택", "수원").seats[0].sold is True


class TestPurge:
    def test_지난_운행일만_삭제(self, conn):
        old = make_map("천안", "평택", sold=False, fetched_at=at(7, 11)).model_copy(
            update={"date": _date(2026, 8, 4)}
        )
        record(conn, old)
        record(conn, make_map("천안", "평택", sold=False, fetched_at=at(7, 11)))
        deleted = purge_before(conn, RIDE_DATE)
        assert deleted == 1
        assert load(conn, "1004", _date(2026, 8, 4), "천안", "평택") is None
        assert load(conn, "1004", RIDE_DATE, "천안", "평택") is not None


def test_store_어댑터는_record를_위임한다(conn):
    store = SqliteSeatSnapshotStore(conn)
    store.record(make_map("천안", "평택", sold=False, fetched_at=at(7, 11)))
    assert load(conn, "1004", RIDE_DATE, "천안", "평택") is not None
