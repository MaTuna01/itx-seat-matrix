"""구간 좌석맵 병렬 조회 (PLAN.md 5절 3, 10절 호출 예절).

도메인은 순수 함수만 담으므로(CLAUDE.md 절대규칙 4) 조회 오케스트레이션은 여기에 둔다.
`domain/matrix.py`는 그 결과를 병합만 한다. api·scheduler 양쪽이 이 모듈을 쓴다.

호출 예절 (CLAUDE.md 10, D-17):
- 동시성 `Semaphore(3)`
- 요청마다 0.1~0.4초 지터
- 조회 범위는 실효 시작~하차역으로 이미 좁혀서 들어온다 (D-18)
"""

from __future__ import annotations

import asyncio
import random
from datetime import date as _date
from datetime import datetime

from app.adapters.korail_port import KorailPort
from app.domain.matrix import merge_seat_maps
from app.domain.models import KorailCred, SeatMap, SeatMatrix

MAX_CONCURRENCY = 3
JITTER_RANGE = (0.1, 0.4)


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
) -> dict[int, SeatMap]:
    """`[start_idx, end_idx)` 구간의 좌석맵을 병렬 조회한다."""
    sem = asyncio.Semaphore(concurrency)

    async def fetch(seg_idx: int) -> tuple[int, SeatMap]:
        async with sem:
            if jitter is not None:
                await asyncio.sleep(random.uniform(*jitter))
            seat_map = await port.get_seat_map(
                cred, train_no, d, stops[seg_idx], stops[seg_idx + 1]
            )
            return seg_idx, seat_map

    results = await asyncio.gather(*(fetch(i) for i in range(start_idx, end_idx)))
    return dict(results)


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
) -> SeatMatrix:
    """조회 + 병합. `now`는 호출자가 주입한다 (fetched_at, D-21)."""
    seat_maps = await fetch_segment_maps(
        port, cred, train_no, d, stops, start_idx, end_idx, jitter=jitter
    )
    return merge_seat_maps(
        train_no=train_no,
        date=d,
        stops=stops,
        seat_maps=seat_maps,
        start_idx=start_idx,
        end_idx=end_idx,
        fetched_at=now,
    )
