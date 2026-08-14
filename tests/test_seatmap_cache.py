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
from app.adapters.korail_client import KorailApiError
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


# ── 스냅샷 기록 훅 (→ D-57): 성공한 실조회만 기록되는가 ──────────────────
class RecordingList:
    """SeatMapRecorder 최소 구현 — 기록된 구간 키만 모은다."""

    def __init__(self) -> None:
        self.recorded: list[tuple[str, str]] = []

    def record(self, seat_map: SeatMap) -> None:
        self.recorded.append((seat_map.frm, seat_map.to))


async def test_recorder_records_real_fetches(conn) -> None:
    port = CountingPort()
    recorder = RecordingList()
    await fetch_segment_maps(
        port, None, "1004", RIDE_DATE, STOPS, 0, 2, jitter=None,
        recorder=recorder, now=at(8, 0, 10),
    )
    assert recorder.recorded == [("천안", "평택"), ("평택", "수원")]


async def test_recorder_skips_cache_hits(conn) -> None:
    """캐시 히트는 기록하지 않는다 — 원 조회 때 이미 기록됐다 (D-57)."""
    port = CountingPort()
    cache = SqliteSeatMapCache(conn)
    first = RecordingList()
    await fetch_segment_maps(
        port, None, "1004", RIDE_DATE, STOPS, 0, 2, jitter=None,
        cache=cache, recorder=first, now=at(8, 0, 10),
    )
    assert len(first.recorded) == 2

    second = RecordingList()
    await fetch_segment_maps(
        port, None, "1004", RIDE_DATE, STOPS, 0, 2, jitter=None,
        cache=cache, recorder=second, now=at(8, 0, 20),
    )
    assert second.recorded == []  # 전 구간 캐시 히트 → 기록 없음


async def test_recorder_skips_failed_segments(conn) -> None:
    """실패 구간은 SeatMap이 생기지 않으므로 기록될 수 없다 — 오염 방지 ① (D-57)."""

    class HalfFailPort:
        async def get_seat_map(self, cred, train_no, d, frm, to):  # noqa: ANN001, ANN201
            if frm == "천안":
                raise KorailApiError("ERR911081 좌석선택 예약불가")
            return make_map(frm, to, sold=True, fetched_at=at(8, 0))

    recorder = RecordingList()
    result = await fetch_segment_maps(
        HalfFailPort(), None, "1004", RIDE_DATE, STOPS, 0, 2, jitter=None,
        recorder=recorder, retry=NO_RETRY, now=at(8, 0, 10),
    )
    assert result.failed_idxs == [0]
    assert recorder.recorded == [("평택", "수원")]


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
    assert result.maps[0].seats[0].sold is False


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


# ── 구간 단위 실패 격리 (이슈 #40 → D-48) ─────────────────────────────
class OneBadSegmentPort:
    """특정 구간만 실패하는 포트. 나머지 구간은 정상 응답한다."""

    def __init__(self, bad_from: str, exc: Exception) -> None:
        self.bad_from = bad_from
        self.exc = exc
        self.calls: list[str] = []

    async def get_seat_map(self, cred, train_no, d, frm, to):  # noqa: ANN001, ANN201
        self.calls.append(frm)
        if frm == self.bad_from:
            raise self.exc
        return make_map(frm, to, sold=False, fetched_at=at(8, 0))


# 구간 3개짜리 노선 — "가운데 하나만 실패"를 만들려면 최소 3구간이 필요하다
LONG_STOPS = ["천안", "평택", "수원", "안양"]


async def test_한_구간이_실패해도_나머지는_살아남는다() -> None:
    """★ 회귀 방어 (이슈 #40). "수원까지는 앉을 수 있다"가 가장 쓸모 있는 정보인데,
    한 구간의 실패가 그것까지 통째로 버리고 있었다 (D-36이 매진에만 적용한 판단을 확장).
    """
    port = OneBadSegmentPort("평택", KorailApiError("ERR911081", "좌석선택 예약불가"))
    result = await fetch_segment_maps(
        port, None, "1004", RIDE_DATE, LONG_STOPS, 0, 3, jitter=None, retry=NO_RETRY
    )
    assert result.failed_idxs == [1]
    assert sorted(result.maps) == [0, 2], "성공한 구간까지 함께 버려졌다"
    assert isinstance(result.failed[1], KorailApiError)


async def test_전_구간이_실패하면_원래_예외를_올린다() -> None:
    """보여줄 것이 없을 때는 실패가 맞다. 예외 타입이 호출부의 상태코드 매핑에 필요하다."""
    port = FlakyPort(99, CredentialsRequired("코레일 계정이 연결되지 않았습니다."))
    with pytest.raises(CredentialsRequired):
        await fetch_segment_maps(
            port, None, "1004", RIDE_DATE, STOPS, 0, 2, jitter=None, retry=NO_RETRY
        )


async def test_빈_조회_범위는_실패가_아니다() -> None:
    """마지막 구간 주행 중 (D-47). 조회할 구간이 없는 것과 전부 실패한 것은 다르다."""
    port = OneBadSegmentPort("천안", RuntimeError("불려선 안 된다"))
    result = await fetch_segment_maps(
        port, None, "1004", RIDE_DATE, STOPS, 2, 2, jitter=None, retry=NO_RETRY
    )
    assert result.maps == {} and result.failed == {}
    assert port.calls == []
