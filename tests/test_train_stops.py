"""열차별 정차역 캐시 (Phase 2 항목 A/D-29).

핵심은 **날짜 재적용**이다 — 캐시는 특정 관측일(예: 8/4)에서 왔지만, 요청은
다른 날짜(예: 오늘)로 온다. 시각(time-of-day)만 재사용하고 날짜는 요청값을
써야 한다. 시발역(도착 기록 없음)을 출발시각으로 보정하는 규칙도 함께 본다.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime

import pytest

from app.domain.models import KST
from app.storage.db import connect, init_db
from app.storage.train_stops import (
    StopRow,
    count_trains,
    freshness,
    get_stops,
    known_train_numbers,
    normalize_train_no,
    save_stops,
)

OBSERVED_DAY = _date(2026, 8, 4)  # 캐시가 관측된 실제 운행일
REQUEST_DAY = _date(2026, 8, 6)  # 사용자가 실제로 조회하는 날짜 (다르다!)


def at(d: _date, h: int, m: int) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=KST)


def sample_rows() -> list[StopRow]:
    return [
        StopRow(
            seq=1,
            station_name="천안",
            station_code="3900061",
            stop_type="시발",
            arrival=None,  # 시발역은 도착 기록이 없다
            departure=at(OBSERVED_DAY, 7, 39),
            run_ymd=OBSERVED_DAY,
        ),
        StopRow(
            seq=2,
            station_name="평택",
            station_code="3900057",
            stop_type="여객승하차",
            arrival=at(OBSERVED_DAY, 7, 51),
            departure=at(OBSERVED_DAY, 7, 53),
            run_ymd=OBSERVED_DAY,
        ),
        StopRow(
            seq=3,
            station_name="용산",
            station_code="3900025",
            stop_type="종착",
            arrival=at(OBSERVED_DAY, 8, 54),
            departure=None,  # 종착역은 출발 기록이 없다
            run_ymd=OBSERVED_DAY,
        ),
    ]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "stops.db"
    init_db(path)
    c = connect(path)
    try:
        yield c
    finally:
        c.close()


# ── 열차번호 정규화 ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"), [("01472", "1472"), ("1472", "1472"), ("0000", "0"), ("", "0")]
)
def test_normalize_train_no(raw: str, expected: str) -> None:
    assert normalize_train_no(raw) == expected


# ── 저장 + 재조립 ────────────────────────────────────────────────────────
def test_save_and_get_roundtrip(conn) -> None:
    now = datetime.now(KST)
    save_stops(conn, "01472", sample_rows(), now=now)

    stops = get_stops(conn, "1472", REQUEST_DAY)  # 선행 0 다르게 조회해도 찾는다
    assert stops is not None
    assert [s.name for s in stops] == ["천안", "평택", "용산"]


def test_date_is_reapplied_not_observed_day(conn) -> None:
    """★ 이게 이 기능의 핵심이다. 캐시는 8/4 관측인데 요청은 8/6이다."""
    save_stops(conn, "1472", sample_rows(), now=datetime.now(KST))
    stops = get_stops(conn, "1472", REQUEST_DAY)
    assert stops is not None
    assert all(s.arrival.date() == REQUEST_DAY for s in stops)
    # 시각(time-of-day)은 그대로 유지된다
    assert (stops[1].arrival.hour, stops[1].arrival.minute) == (7, 51)


def test_origin_station_uses_departure_as_arrival(conn) -> None:
    """시발역은 도착 기록이 없다 — StopInfo.arrival은 필수 필드라 출발시각으로 대신한다."""
    save_stops(conn, "1472", sample_rows(), now=datetime.now(KST))
    stops = get_stops(conn, "1472", REQUEST_DAY)
    assert stops is not None
    origin = stops[0]
    assert origin.name == "천안"
    assert (origin.arrival.hour, origin.arrival.minute) == (7, 39)  # 출발시각과 동일
    assert origin.departure is not None
    assert (origin.departure.hour, origin.departure.minute) == (7, 39)


def test_terminus_has_no_departure(conn) -> None:
    save_stops(conn, "1472", sample_rows(), now=datetime.now(KST))
    stops = get_stops(conn, "1472", REQUEST_DAY)
    assert stops is not None
    terminus = stops[-1]
    assert terminus.name == "용산"
    assert terminus.departure is None
    assert (terminus.arrival.hour, terminus.arrival.minute) == (8, 54)


def test_stops_are_ordered_by_seq(conn) -> None:
    shuffled = [sample_rows()[2], sample_rows()[0], sample_rows()[1]]
    save_stops(conn, "1472", shuffled, now=datetime.now(KST))
    stops = get_stops(conn, "1472", REQUEST_DAY)
    assert stops is not None
    assert [s.name for s in stops] == ["천안", "평택", "용산"]


def test_missing_train_returns_none(conn) -> None:
    assert get_stops(conn, "9999", REQUEST_DAY) is None


def test_resave_replaces_entirely(conn) -> None:
    """부분 갱신은 순서가 어긋날 위험이 있다 — 통째로 교체해야 한다."""
    save_stops(conn, "1472", sample_rows(), now=datetime.now(KST))
    shorter = sample_rows()[:2]  # 정차역이 줄어든 새 관측
    save_stops(conn, "1472", shorter, now=datetime.now(KST))

    stops = get_stops(conn, "1472", REQUEST_DAY)
    assert stops is not None
    assert len(stops) == 2  # 옛 3번째 정차역이 남아있지 않다


# ── 자정을 넘는 운행 (day_offset) ────────────────────────────────────────
def test_overnight_run_uses_day_offset(conn) -> None:
    """자정을 넘는 운행은 다음날 시각으로 저장돼야 하고, 요청 날짜에도 그렇게 재적용된다."""
    rows = [
        StopRow(
            seq=1,
            station_name="서울",
            station_code="3900023",
            stop_type="시발",
            arrival=None,
            departure=at(OBSERVED_DAY, 23, 50),
            run_ymd=OBSERVED_DAY,
        ),
        StopRow(
            seq=2,
            station_name="부산",
            station_code="3900114",
            stop_type="종착",
            arrival=datetime(2026, 8, 5, 5, 10, tzinfo=KST),  # 다음날 새벽
            departure=None,
            run_ymd=OBSERVED_DAY,
        ),
    ]
    save_stops(conn, "9000", rows, now=datetime.now(KST))
    stops = get_stops(conn, "9000", REQUEST_DAY)
    assert stops is not None
    assert stops[0].arrival.date() == REQUEST_DAY
    assert stops[1].arrival.date() == REQUEST_DAY + (datetime(2026, 8, 5) - datetime(2026, 8, 4))


# ── 메타데이터 ───────────────────────────────────────────────────────────
def test_known_train_numbers(conn) -> None:
    save_stops(conn, "1472", sample_rows(), now=datetime.now(KST))
    save_stops(conn, "1008", sample_rows(), now=datetime.now(KST))
    assert known_train_numbers(conn) == {"1472", "1008"}


def test_freshness_reports_observed_run_day(conn) -> None:
    save_stops(conn, "1472", sample_rows(), now=datetime.now(KST))
    assert freshness(conn, "1472") == OBSERVED_DAY
    assert freshness(conn, "9999") is None


def test_count_trains(conn) -> None:
    assert count_trains(conn) == 0
    save_stops(conn, "1472", sample_rows(), now=datetime.now(KST))
    assert count_trains(conn) == 1
