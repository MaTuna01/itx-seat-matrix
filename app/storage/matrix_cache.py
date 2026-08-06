"""구간 좌석맵 60초 TTL 캐시 (PLAN.md 5절, D-17).

**화면 트래픽 전용.** 스케줄러는 `use_cache=False`로 우회한다 — 캐시된 값으로 판정하면
상태 변화를 통째로 놓치고, 그러면 알림이 조용히 안 온다 (원칙 6).

`now`는 전부 인자로 받는다 (CLAUDE.md 절대규칙 2). TTL 판정에 `datetime.now()`를
내부에서 부르면 테스트가 sleep 없이는 불가능해진다.
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import datetime, timedelta

from app.domain.models import SeatMap
from app.storage.db import to_db

TTL_SECONDS = 60


def _key(train_no: str, d: _date, frm: str, to: str) -> tuple[str, str, str, str]:
    return (train_no, d.isoformat(), frm, to)


def get_cached(
    conn: sqlite3.Connection,
    train_no: str,
    d: _date,
    frm: str,
    to: str,
    *,
    now: datetime,
    ttl_seconds: int = TTL_SECONDS,
) -> SeatMap | None:
    """TTL 내 항목만 반환한다. 만료·부재는 둘 다 None."""
    row = conn.execute(
        "SELECT payload, fetched_at FROM matrix_cache"
        " WHERE train_no = ? AND date = ? AND frm = ? AND to_station = ?",
        _key(train_no, d, frm, to),
    ).fetchone()
    if row is None:
        return None

    fetched_at = datetime.fromisoformat(row["fetched_at"])
    if now - fetched_at >= timedelta(seconds=ttl_seconds):
        return None
    # 시계가 뒤로 간 경우(NTP 보정 등) 미래 항목은 신뢰하지 않는다
    if fetched_at > now:
        return None
    return SeatMap.model_validate_json(row["payload"])


def put_cached(conn: sqlite3.Connection, seat_map: SeatMap) -> None:
    conn.execute(
        "INSERT INTO matrix_cache (train_no, date, frm, to_station, payload, fetched_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(train_no, date, frm, to_station) DO UPDATE SET"
        " payload = excluded.payload, fetched_at = excluded.fetched_at",
        (
            seat_map.train_no,
            seat_map.date.isoformat(),
            seat_map.frm,
            seat_map.to,
            seat_map.model_dump_json(),
            to_db(seat_map.fetched_at),
        ),
    )


class SqliteSeatMapCache:
    """`adapters.seatmap_fetcher.SeatMapCache` 구현 (SQLite 바인딩).

    **화면 경로에서만 만든다.** 스케줄러는 `cache=None`을 넘겨 우회한다 (D-17).
    """

    def __init__(self, conn: sqlite3.Connection, *, ttl_seconds: int = TTL_SECONDS) -> None:
        self._conn = conn
        self._ttl = ttl_seconds

    def get(
        self, train_no: str, d: _date, frm: str, to: str, *, now: datetime
    ) -> SeatMap | None:
        return get_cached(
            self._conn, train_no, d, frm, to, now=now, ttl_seconds=self._ttl
        )

    def put(self, seat_map: SeatMap) -> None:
        put_cached(self._conn, seat_map)


def purge_expired(
    conn: sqlite3.Connection, *, now: datetime, ttl_seconds: int = TTL_SECONDS
) -> int:
    """만료 항목 삭제. 반환값은 삭제된 행 수.

    경계는 `get_cached`와 **같아야 한다** — 거기서는 `now - fetched_at >= ttl`이
    만료이므로 `fetched_at <= now - ttl`이 삭제 대상이다. 부등호가 어긋나면
    "조회로는 만료인데 청소는 안 되는" 항목이 남는다.
    """
    cutoff = to_db(now - timedelta(seconds=ttl_seconds))
    cur = conn.execute("DELETE FROM matrix_cache WHERE fetched_at <= ?", (cutoff,))
    return cur.rowcount
