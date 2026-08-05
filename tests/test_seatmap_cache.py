"""60초 TTL 캐시 + 재시도 (PLAN 5절, D-17 / Phase 2 항목 D).

핵심은 두 가지다:
1. **스케줄러가 캐시를 우회하는가** — 캐시된 값으로 판정하면 상태 변화를 놓치고
   알림이 조용히 안 온다 (원칙 6). 여기가 이 기능의 유일한 위험 지점이다.
2. 재시도가 **다시 불러도 같은 답인 실패**(ValueError)에는 낭비되지 않는가.

시간은 전부 `now` 주입 — sleep/실제 시계 금지 (CLAUDE.md).
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timedelta

import pytest

from app.adapters.korail2_adapter import CredentialsRequired
from app.adapters.seatmap_fetcher import (
    NO_RETRY,
    RetryPolicy,
    fetch_segment_maps,
)
from app.domain.models import KST, SeatMap, SeatState
from app.storage.db import connect, init_db
from app.storage.matrix_cache import (
    SqliteSeatMapCache,
    get_cached,
    purge_expired,
    put_cached,
)

RIDE_DATE = _date(2026, 8, 5)
STOPS = ["천안", "평택", "수원"]


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 5, hour, minute, second, tzinfo=KST)


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
    path = tmp_path / "cache.db"
    init_db(path)
    c = connect(path)
    try:
        yield c
    finally:
        c.close()


# ── TTL ──────────────────────────────────────────────────────────────────
def test_hit_within_ttl(conn) -> None:
    put_cached(conn, make_map("천안", "평택", sold=True, fetched_at=at(8, 0, 0)))
    hit = get_cached(conn, "1004", RIDE_DATE, "천안", "평택", now=at(8, 0, 59))
    assert hit is not None
    assert hit.seats[0].sold is True


def test_miss_after_ttl(conn) -> None:
    put_cached(conn, make_map("천안", "평택", sold=True, fetched_at=at(8, 0, 0)))
    assert get_cached(conn, "1004", RIDE_DATE, "천안", "평택", now=at(8, 1, 0)) is None


def test_miss_when_absent(conn) -> None:
    assert get_cached(conn, "1004", RIDE_DATE, "천안", "평택", now=at(8, 0)) is None


def test_future_entry_is_not_trusted(conn) -> None:
    """시계가 뒤로 가면(NTP 보정) 미래 fetched_at이 영원히 유효해 보일 수 있다."""
    put_cached(conn, make_map("천안", "평택", sold=True, fetched_at=at(9, 0)))
    assert get_cached(conn, "1004", RIDE_DATE, "천안", "평택", now=at(8, 0)) is None


def test_key_is_per_segment(conn) -> None:
    """키는 (train_no, date, frm, to) — 구간이 다르면 다른 항목이다."""
    put_cached(conn, make_map("천안", "평택", sold=True, fetched_at=at(8, 0)))
    assert get_cached(conn, "1004", RIDE_DATE, "평택", "수원", now=at(8, 0)) is None
    assert get_cached(conn, "9999", RIDE_DATE, "천안", "평택", now=at(8, 0)) is None
    other_day = RIDE_DATE + timedelta(days=1)
    assert get_cached(conn, "1004", other_day, "천안", "평택", now=at(8, 0)) is None


def test_put_overwrites_same_key(conn) -> None:
    put_cached(conn, make_map("천안", "평택", sold=True, fetched_at=at(8, 0)))
    put_cached(conn, make_map("천안", "평택", sold=False, fetched_at=at(8, 0, 30)))
    hit = get_cached(conn, "1004", RIDE_DATE, "천안", "평택", now=at(8, 0, 40))
    assert hit is not None and hit.seats[0].sold is False


def test_purge_expired_removes_only_stale(conn) -> None:
    put_cached(conn, make_map("천안", "평택", sold=True, fetched_at=at(8, 0, 0)))
    put_cached(conn, make_map("평택", "수원", sold=True, fetched_at=at(8, 0, 50)))
    assert purge_expired(conn, now=at(8, 1, 0)) == 1
    assert get_cached(conn, "1004", RIDE_DATE, "평택", "수원", now=at(8, 1, 0)) is not None


# ── fetcher 통합: 캐시 우회가 진짜 되는가 ────────────────────────────────
class CountingPort:
    """호출 횟수를 세는 최소 KorailPort (좌석맵만 쓴다)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get_seat_map(self, cred, train_no, d, frm, to) -> SeatMap:  # noqa: ANN001
        self.calls.append((frm, to))
        return make_map(frm, to, sold=True, fetched_at=at(8, 0))


async def test_screen_path_uses_cache(conn) -> None:
    port = CountingPort()
    cache = SqliteSeatMapCache(conn)
    kwargs = dict(jitter=None, cache=cache, now=at(8, 0, 10))

    await fetch_segment_maps(port, None, "1004", RIDE_DATE, STOPS, 0, 2, **kwargs)
    assert len(port.calls) == 2

    # 같은 조회를 TTL 안에서 반복 — 코레일을 다시 때리지 않아야 한다
    await fetch_segment_maps(port, None, "1004", RIDE_DATE, STOPS, 0, 2, **kwargs)
    assert len(port.calls) == 2


async def test_scheduler_path_bypasses_cache(conn) -> None:
    """★ cache=None이면 TTL 안이어도 항상 실조회한다.

    이게 깨지면 스케줄러가 캐시된 좌석맵으로 판정해 상태 변화를 통째로 놓친다
    — 알림이 '조용히' 안 오는 가장 나쁜 실패 모드다 (원칙 6, D-17).
    """
    port = CountingPort()
    cache = SqliteSeatMapCache(conn)

    await fetch_segment_maps(
        port, None, "1004", RIDE_DATE, STOPS, 0, 2, jitter=None, cache=cache, now=at(8, 0, 10)
    )
    assert len(port.calls) == 2

    await fetch_segment_maps(
        port, None, "1004", RIDE_DATE, STOPS, 0, 2, jitter=None, cache=None, now=at(8, 0, 10)
    )
    assert len(port.calls) == 4


async def test_cache_is_populated_by_fetch(conn) -> None:
    port = CountingPort()
    await fetch_segment_maps(
        port,
        None,
        "1004",
        RIDE_DATE,
        STOPS,
        0,
        1,
        jitter=None,
        cache=SqliteSeatMapCache(conn),
        now=at(8, 0, 10),
    )
    assert get_cached(conn, "1004", RIDE_DATE, "천안", "평택", now=at(8, 0, 20)) is not None


# ── 재시도 ───────────────────────────────────────────────────────────────
class FlakyPort:
    def __init__(self, fail_times: int, exc: Exception) -> None:
        self.remaining = fail_times
        self.exc = exc
        self.attempts = 0

    async def get_seat_map(self, cred, train_no, d, frm, to) -> SeatMap:  # noqa: ANN001
        self.attempts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.exc
        return make_map(frm, to, sold=False, fetched_at=at(8, 0))


async def _run(port, retry: RetryPolicy, slept: list[float]):  # noqa: ANN001, ANN202
    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    return await fetch_segment_maps(
        port,
        None,
        "1004",
        RIDE_DATE,
        STOPS,
        0,
        1,
        jitter=None,
        retry=retry,
        sleep=fake_sleep,
    )


async def test_retry_recovers_from_transient_failure() -> None:
    port = FlakyPort(2, ConnectionError("일시적 네트워크 장애"))
    slept: list[float] = []
    result = await _run(port, RetryPolicy(attempts=3, delay_seconds=30.0), slept)
    assert port.attempts == 3
    assert slept == [30.0, 30.0]  # 시도 사이에만 대기 (마지막 뒤에는 없음)
    assert result[0].seats[0].sold is False


async def test_retry_gives_up_after_three_attempts() -> None:
    """상한은 3회다 — 무한 재시도로 코레일을 때리면 안 된다 (CLAUDE.md 10)."""
    port = FlakyPort(99, ConnectionError("계속 실패"))
    slept: list[float] = []
    with pytest.raises(ConnectionError):
        await _run(port, RetryPolicy(attempts=3, delay_seconds=30.0), slept)
    assert port.attempts == 3
    assert slept == [30.0, 30.0]


async def test_value_error_is_not_retried() -> None:
    """'없는 열차/역'은 다시 불러도 같은 답이다 — 30초씩 기다릴 이유가 없다."""
    port = FlakyPort(99, ValueError("목업에 없는 열차번호다"))
    slept: list[float] = []
    with pytest.raises(ValueError):
        await _run(port, RetryPolicy(attempts=3, delay_seconds=30.0), slept)
    assert port.attempts == 1
    assert slept == []


async def test_credentials_required_is_not_retried() -> None:
    """계정 미연결도 '다시 불러도 같은 답'이다 — `ValueError` 상속으로 재시도 제외된다."""
    port = FlakyPort(99, CredentialsRequired("코레일 계정이 연결되지 않았습니다."))
    slept: list[float] = []
    with pytest.raises(CredentialsRequired):
        await _run(port, RetryPolicy(attempts=3, delay_seconds=30.0), slept)
    assert port.attempts == 1
    assert slept == []


async def test_no_retry_policy_attempts_once() -> None:
    port = FlakyPort(99, ConnectionError("실패"))
    slept: list[float] = []
    with pytest.raises(ConnectionError):
        await _run(port, NO_RETRY, slept)
    assert port.attempts == 1
