"""열차별 정차역 캐시 — get_stops() 소스 (Phase 2 항목 A, D-29).

저장은 `scripts/load_train_stops.py`(공공데이터 API를 실제로 부른다)가 하고,
여기는 **순수 조회/변환**만 한다. 절대 시각이 아니라 시각(time-of-day) + 날짜
오프셋으로 저장하는 이유는 마이그레이션 파일 상단 주석 참고.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, time as _time, timedelta
import sqlite3

from app.domain.models import KST, StopInfo
from app.storage.db import to_db


def normalize_train_no(raw: str) -> str:
    """선행 0을 없앤다. `'01472'` → `'1472'`. 단, 전부 0이면 `'0'`을 남긴다."""
    stripped = str(raw or "").lstrip("0")
    return stripped or "0"


@dataclass(frozen=True)
class StopRow:
    """저장 직전 형태. 로더가 원시 API 행을 이 모양으로 변환한다."""

    seq: int
    station_name: str
    station_code: str | None
    stop_type: str
    arrival: datetime | None  # 절대 시각 (관측된 운행일 기준)
    departure: datetime | None
    run_ymd: _date  # 관측한 실제 운행일 — day_offset 계산 기준


def _split(dt: datetime | None, base: _date) -> tuple[int | None, str | None]:
    if dt is None:
        return None, None
    return (dt.date() - base).days, dt.strftime("%H:%M:%S")


def save_stops(
    conn: sqlite3.Connection, train_no: str, rows: list[StopRow], *, now: datetime
) -> None:
    """열차 하나의 정차역 전체를 통째로 교체한다 (부분 갱신은 순서가 어긋날 위험).

    `now`는 인자로 받는다 — 이 함수 자체는 순수하지 않지만(DB 쓰기), 시각을
    내부에서 만들지 않아야 테스트가 sleep 없이 가능하다 (D-21).
    """
    key = normalize_train_no(train_no)
    conn.execute("DELETE FROM train_stop WHERE train_no = ?", (key,))
    for row in rows:
        a_off, a_time = _split(row.arrival, row.run_ymd)
        d_off, d_time = _split(row.departure, row.run_ymd)
        conn.execute(
            "INSERT INTO train_stop (train_no, seq, station_name, station_code, stop_type,"
            " arrival_day_offset, arrival_time, departure_day_offset, departure_time,"
            " source_run_ymd, refreshed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                row.seq,
                row.station_name,
                row.station_code,
                row.stop_type,
                a_off,
                a_time,
                d_off,
                d_time,
                row.run_ymd.isoformat(),
                to_db(now),
            ),
        )


def _combine(target: _date, day_offset: int | None, hms: str | None) -> datetime | None:
    if hms is None or day_offset is None:
        return None
    h, m, s = (int(x) for x in hms.split(":"))
    return datetime.combine(target + timedelta(days=day_offset), _time(h, m, s), tzinfo=KST)


def get_stops(conn: sqlite3.Connection, train_no: str, d: _date) -> list[StopInfo] | None:
    """캐시에서 정차역을 조립해 요청 날짜에 재적용한다. 없으면 None (호출부가 판단).

    시발역은 도착 기록이 없으므로 **출발시각으로 대신한다** — "그 시각에 그 역에
    있다"는 사실은 동일하고, `StopInfo.arrival`은 필수 필드다 (D-18 실효 시작
    계산이 이 값을 쓴다).
    """
    rows = conn.execute(
        "SELECT seq, station_name, arrival_day_offset, arrival_time,"
        " departure_day_offset, departure_time"
        " FROM train_stop WHERE train_no = ? ORDER BY seq",
        (normalize_train_no(train_no),),
    ).fetchall()
    if not rows:
        return None

    stops: list[StopInfo] = []
    for row in rows:
        arrival = _combine(d, row["arrival_day_offset"], row["arrival_time"])
        departure = _combine(d, row["departure_day_offset"], row["departure_time"])
        effective_arrival = arrival or departure  # 시발역 보정
        if effective_arrival is None:  # pragma: no cover — 저장 시 최소 한쪽은 있어야 정상
            continue
        stops.append(
            StopInfo(name=row["station_name"], arrival=effective_arrival, departure=departure)
        )
    return stops or None


def known_train_numbers(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT DISTINCT train_no FROM train_stop").fetchall()
    return {r["train_no"] for r in rows}


def freshness(conn: sqlite3.Connection, train_no: str) -> _date | None:
    """이 열차의 정차역 정보가 어느 실제 운행일에서 관측됐는지."""
    row = conn.execute(
        "SELECT source_run_ymd FROM train_stop WHERE train_no = ? LIMIT 1",
        (normalize_train_no(train_no),),
    ).fetchone()
    return _date.fromisoformat(row["source_run_ymd"]) if row else None


def count_trains(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(DISTINCT train_no) FROM train_stop").fetchone()[0]
