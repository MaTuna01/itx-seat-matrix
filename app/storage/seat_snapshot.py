"""구간별 마지막 성공 조회 스냅샷 (→ D-57).

`matrix_cache`(60초 TTL, 화면 전용)와 다르다 — TTL이 없고, 스케줄러 폴과 화면 조회
**양쪽이** 기록한다. 갭 구간(지금 타고 있는 구간)을 "HH:MM 조회 기준"으로 보여주는
**표시 전용** 데이터라 알림 상태가 아니고(절대규칙 5 무관), 캐시처럼 읽기 경로를
오염시키지도 않는다 — 조회 경로는 이 테이블을 읽지 않는다.

`now`류 시간은 전부 SeatMap.fetched_at으로 들어온다 (절대규칙 2).
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date

from app.domain.models import SeatMap
from app.storage.db import to_db


def record(conn: sqlite3.Connection, seat_map: SeatMap) -> None:
    """마지막 성공 조회를 남긴다. **더 새로운 관측만** 덮는다.

    화면 조회와 스케줄러 폴이 경합해도 fetched_at 역행이 없도록 UPSERT에 조건을 건다
    (KST 고정 ISO8601이라 문자열 비교로 안전하다 — to_db가 보장).
    """
    conn.execute(
        "INSERT INTO seat_snapshot (train_no, date, frm, to_station, payload, fetched_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(train_no, date, frm, to_station) DO UPDATE SET"
        " payload = excluded.payload, fetched_at = excluded.fetched_at"
        " WHERE excluded.fetched_at >= seat_snapshot.fetched_at",
        (
            seat_map.train_no,
            seat_map.date.isoformat(),
            seat_map.frm,
            seat_map.to,
            seat_map.model_dump_json(),
            to_db(seat_map.fetched_at),
        ),
    )


def load(
    conn: sqlite3.Connection, train_no: str, d: _date, frm: str, to: str
) -> SeatMap | None:
    row = conn.execute(
        "SELECT payload FROM seat_snapshot"
        " WHERE train_no = ? AND date = ? AND frm = ? AND to_station = ?",
        (train_no, d.isoformat(), frm, to),
    ).fetchone()
    if row is None:
        return None
    return SeatMap.model_validate_json(row["payload"])


def purge_before(conn: sqlite3.Connection, ride_date: _date) -> int:
    """지난 운행일 스냅샷 삭제. 반환값은 삭제된 행 수.

    당일치는 하차 후에도 남지만 규모가 정차역 수 × 열차 수라 무시할 수준이고,
    다음 날 청소된다 (D-34의 만료 안전망과 같은 자리에서 부른다).
    """
    cur = conn.execute("DELETE FROM seat_snapshot WHERE date < ?", (ride_date.isoformat(),))
    return cur.rowcount


class SqliteSeatSnapshotStore:
    """`adapters.seatmap_fetcher.SeatMapRecorder` 구현 (SQLite 바인딩)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, seat_map: SeatMap) -> None:
        record(self._conn, seat_map)
