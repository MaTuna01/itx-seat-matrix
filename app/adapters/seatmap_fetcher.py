"""구간 좌석맵 병렬 조회 (PLAN.md 5절 3, 10절 호출 예절).

도메인은 순수 함수만 담으므로(CLAUDE.md 절대규칙 4) 조회 오케스트레이션은 여기에 둔다.
`domain/matrix.py`는 그 결과를 병합만 한다. api·scheduler 양쪽이 이 모듈을 쓴다.

호출 예절 (CLAUDE.md 10, D-17):
- 동시성 `Semaphore(3)`
- 요청마다 0.1~0.4초 지터
- 조회 범위는 실효 시작~하차역으로 이미 좁혀서 들어온다 (D-18)
- 실패 재시도 **30초 × 3회가 상한** (`RetryPolicy`)
- 60초 TTL 캐시는 **화면 전용** — 스케줄러는 `cache=None`으로 우회한다 (D-17)
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from typing import Awaitable, Callable, Protocol

from app.adapters.korail_port import KorailPort
from app.domain.matrix import merge_seat_maps
from app.domain.models import KorailCred, SeatMap, SeatMatrix

log = logging.getLogger(__name__)

MAX_CONCURRENCY = 3
JITTER_RANGE = (0.1, 0.4)


@dataclass(frozen=True)
class RetryPolicy:
    """조정 예정 손잡이 — 매직 넘버를 로직에 인라인하지 않는다 (D-17).

    `attempts`는 **총 시도 횟수**다 (최초 1회 + 재시도 2회가 아니라 3회 시도).
    """

    attempts: int = 3
    delay_seconds: float = 30.0


# 스케줄러용 — CLAUDE.md 10의 "재시도(30초×3)가 상한"을 그대로 옮긴 값.
# 8절의 FETCH_FAILED("한 조회 시점 내 3회 실패")가 세는 대상이 이것이다.
SCHEDULER_RETRY = RetryPolicy(attempts=3, delay_seconds=30.0)

# 화면용 — 30초×3은 최악 60초 대기라 사용자를 화면 앞에 세워둔다 (D-27).
# 화면은 실패하면 빨리 실패하는 편이 낫다. 새로고침이 곧 재시도다.
SCREEN_RETRY = RetryPolicy(attempts=2, delay_seconds=2.0)

DEFAULT_RETRY = SCHEDULER_RETRY
NO_RETRY = RetryPolicy(attempts=1, delay_seconds=0.0)


class SeatMapCache(Protocol):
    """60초 TTL 캐시 경계. 구현은 `storage/matrix_cache.py`.

    fetcher가 sqlite에 직접 기대지 않게 Protocol로 끊는다 — 테스트도 쉬워진다.
    """

    def get(self, train_no: str, d: _date, frm: str, to: str, *, now: datetime) -> SeatMap | None:
        ...

    def put(self, seat_map: SeatMap) -> None:
        ...


class SeatMapRecorder(Protocol):
    """구간별 마지막 성공 조회 기록 경계 (→ D-57). 구현은 `storage/seat_snapshot.py`.

    캐시와 달리 **쓰기 전용**이다 — 조회 경로는 스냅샷을 읽지 않는다. 갭 구간
    (지금 타고 있는 구간)을 화면이 "HH:MM 조회 기준"으로 보여주기 위한 표시 전용
    데이터라 스케줄러·화면 양 경로 모두 기록해도 알림 상태(절대규칙 5)와 무관하다.

    기록 조건 불변식: **조회 시점에 sellable했던 구간의 성공한 조회만** 여기 온다.
    호출부가 조회 범위를 이미 `[max(sellable, board), alight)`로 좁혀서 들어오고
    (D-47), 실패는 예외로 빠져 SeatMap 자체가 생기지 않는다. 캐시 히트는 기록하지
    않는다 — 원 조회 때 이미 기록됐다.
    """

    def record(self, seat_map: SeatMap) -> None:
        ...


async def _with_retry(
    call: Callable[[], Awaitable[SeatMap]],
    policy: RetryPolicy,
    sleep: Callable[[float], Awaitable[None]],
) -> SeatMap:
    """일시적 실패만 재시도한다.

    `ValueError`는 재시도하지 않는다 — 어댑터가 "없는 열차/역"처럼 **다시 불러도
    같은 결과인 것**에 쓰는 예외다. 30초씩 3번 기다렸다 같은 답을 받을 이유가 없다.
    """
    last: Exception | None = None
    for attempt in range(1, policy.attempts + 1):
        try:
            return await call()
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 — 네트워크/코레일 장애 전반
            last = exc
            if attempt < policy.attempts:
                await sleep(policy.delay_seconds)
    assert last is not None
    raise last


@dataclass(frozen=True)
class SegmentMaps:
    """구간별 조회 결과 + **실패한 구간** (→ D-48).

    한 구간의 실패가 매트릭스 전체를 죽이면 안 된다 — "수원까지는 앉을 수 있다"가 가장
    쓸모 있는 정보인데 그게 통째로 사라진다. D-36이 매진 한 가지 사유에만 적용했던 판단을
    **실패 사유 전반**으로 넓힌 것이다. 코레일 코드표를 쫓아다니지 않아도 견딘다.
    """

    maps: dict[int, SeatMap]
    failed: dict[int, Exception]

    @property
    def failed_idxs(self) -> list[int]:
        return sorted(self.failed)


async def fetch_segment_maps(
    port: KorailPort,
    cred: KorailCred | None,
    train_no: str,
    d: _date,
    stops: list[str],
    start_idx: int,
    end_idx: int,
    *,
    concurrency: int = MAX_CONCURRENCY,
    jitter: tuple[float, float] | None = JITTER_RANGE,
    cache: SeatMapCache | None = None,
    recorder: SeatMapRecorder | None = None,
    retry: RetryPolicy = DEFAULT_RETRY,
    now: datetime | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SegmentMaps:
    """`[start_idx, end_idx)` 구간의 좌석맵을 병렬 조회한다.

    `cache`가 주어지면 TTL 내 항목은 코레일을 호출하지 않는다. **스케줄러는 넘기지 마라**
    — 캐시된 값으로 판정하면 상태 변화를 놓치고 알림이 조용히 안 온다 (D-17).

    **구간 단위 실패는 예외로 올리지 않는다** (→ D-48). 실패한 구간만 `failed`에 담고
    나머지 결과는 살린다. 단 **조회한 구간이 전부 실패하면** 첫 예외를 그대로 올린다 —
    보여줄 것이 없을 때는 실패가 맞고, `CredentialsRequired`(→409) 같은 예외 타입이
    호출부의 상태코드 매핑에 필요하다.
    """
    sem = asyncio.Semaphore(concurrency)

    async def fetch(seg_idx: int) -> tuple[int, SeatMap]:
        frm, to = stops[seg_idx], stops[seg_idx + 1]

        if cache is not None and now is not None:
            hit = cache.get(train_no, d, frm, to, now=now)
            if hit is not None:
                return seg_idx, hit

        async with sem:
            if jitter is not None:
                await asyncio.sleep(random.uniform(*jitter))
            seat_map = await _with_retry(
                lambda: port.get_seat_map(cred, train_no, d, frm, to), retry, sleep
            )

        if cache is not None:
            cache.put(seat_map)
        if recorder is not None:
            # 실조회 성공 직후에만 — 캐시 히트는 위에서 이미 반환됐다 (D-57)
            recorder.record(seat_map)
        return seg_idx, seat_map

    segments = list(range(start_idx, end_idx))
    # `return_exceptions=True`가 이 격리의 핵심이다. 없으면 첫 예외가 그대로 올라가면서
    # **이미 성공적으로 받아온 다른 구간의 좌석표까지 버려진다** (이슈 #40).
    results = await asyncio.gather(
        *(fetch(i) for i in segments), return_exceptions=True
    )

    maps: dict[int, SeatMap] = {}
    failed: dict[int, Exception] = {}
    for seg_idx, result in zip(segments, results):
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result  # 취소·KeyboardInterrupt 등은 삼키지 않는다
            log.warning("구간 %s 좌석맵 조회 실패: %s", seg_idx, result)
            failed[seg_idx] = result
        else:
            maps[result[0]] = result[1]

    if segments and not maps:
        raise failed[segments[0]]
    return SegmentMaps(maps=maps, failed=failed)


async def fetch_matrix(
    port: KorailPort,
    cred: KorailCred | None,
    train_no: str,
    d: _date,
    stops: list[str],
    start_idx: int,
    end_idx: int,
    *,
    now: datetime,
    jitter: tuple[float, float] | None = JITTER_RANGE,
    cache: SeatMapCache | None = None,
    recorder: SeatMapRecorder | None = None,
    retry: RetryPolicy = DEFAULT_RETRY,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SeatMatrix:
    """조회 + 병합. `now`는 호출자가 주입한다 (fetched_at, D-21)."""
    fetched = await fetch_segment_maps(
        port,
        cred,
        train_no,
        d,
        stops,
        start_idx,
        end_idx,
        jitter=jitter,
        cache=cache,
        recorder=recorder,
        retry=retry,
        now=now,
        sleep=sleep,
    )
    return merge_seat_maps(
        train_no=train_no,
        date=d,
        stops=stops,
        seat_maps=fetched.maps,
        start_idx=start_idx,
        end_idx=end_idx,
        fetched_at=now,
        failed_seg_idxs=fetched.failed_idxs,
    )
