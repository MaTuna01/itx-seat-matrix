"""역 마스터 저장소 (PLAN.md 11절 Phase 2, D-25).

소스는 공공데이터 CSV다 (`scripts/load_stations.py`가 적재). 런타임에는 **읽기만** 한다 —
정적 참조 데이터를 요청마다 외부 API로 긁지 않는다.

역명 정규화(`normalize_name`)가 이 모듈의 핵심이다. 세 소스(공공데이터 운행정보 /
좌표 CSV / korail2)의 역코드 체계가 서로 달라 **역명이 유일한 조인 축**인데,
표기가 조금씩 다르면 조용히 조인이 깨진다.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import StationInfo
from app.storage.db import to_db

_PARENS = re.compile(r"\s*[（(][^)）]*[)）]\s*")
_SPACES = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """역명 정규화 — 조인 키를 만든다.

    실제로 관측되는 표기 차이:
    - 앞뒤·중간 공백 (`'서울 '`, `'동대구  '`)
    - 괄호 부기 (`'수원(수원역)'`, `'서울(경부)'`)
    - `'~역'` 접미 유무 (`'서울역'` vs `'서울'`)

    접미 `'역'`은 **떼는 방향으로 통일한다.** 코레일·공공데이터 양쪽 모두 기본 표기가
    접미 없는 쪽이고, 붙이는 쪽은 UI 관용이다. 단 이름 자체가 한 글자인 경우
    (`'역'`)는 떼면 빈 문자열이 되므로 남긴다.
    """
    name = _PARENS.sub("", str(raw or ""))
    name = _SPACES.sub(" ", name).strip()
    if len(name) > 1 and name.endswith("역"):
        name = name[:-1].strip()
    return name


@dataclass(frozen=True)
class Station:
    name: str
    code: str | None = None
    lat: float | None = None
    lng: float | None = None
    line: str | None = None

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lng is not None


def upsert(conn: sqlite3.Connection, station: Station, *, source: str, now: datetime) -> None:
    """이름 기준 upsert. **이미 있는 값을 NULL로 덮지 않는다.**

    좌표 CSV와 역코드 CSV가 서로 다른 컬럼을 채우므로, 두 파일을 순서와 무관하게
    적재해도 합쳐지도록 `COALESCE(새 값, 기존 값)`으로 병합한다. 이게 없으면
    나중에 적재한 파일이 앞선 파일의 컬럼을 지워버린다.
    """
    conn.execute(
        "INSERT INTO station (name, code, lat, lng, line, source, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(name) DO UPDATE SET"
        "   code = COALESCE(excluded.code, station.code),"
        "   lat  = COALESCE(excluded.lat,  station.lat),"
        "   lng  = COALESCE(excluded.lng,  station.lng),"
        "   line = COALESCE(excluded.line, station.line),"
        "   source = excluded.source,"
        "   updated_at = excluded.updated_at",
        (
            station.name,
            station.code,
            station.lat,
            station.lng,
            station.line,
            source,
            to_db(now),
        ),
    )


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM station").fetchone()[0]


def count_with_coords(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM station WHERE lat IS NOT NULL AND lng IS NOT NULL"
    ).fetchone()[0]


def list_all(conn: sqlite3.Connection) -> list[StationInfo]:
    """드롭다운 소스 (D-25). 이름 오름차순."""
    rows = conn.execute("SELECT name, code FROM station ORDER BY name").fetchall()
    return [StationInfo(name=r["name"], code=r["code"]) for r in rows]


def get(conn: sqlite3.Connection, name: str) -> Station | None:
    row = conn.execute(
        "SELECT name, code, lat, lng, line FROM station WHERE name = ?",
        (normalize_name(name),),
    ).fetchone()
    if row is None:
        return None
    return Station(
        name=row["name"], code=row["code"], lat=row["lat"], lng=row["lng"], line=row["line"]
    )


def coords_for(conn: sqlite3.Connection, names: list[str]) -> dict[str, tuple[float, float]]:
    """GPS 선분 투영용 좌표 조회 (D-13). 좌표 없는 역은 결과에서 빠진다."""
    out: dict[str, tuple[float, float]] = {}
    for name in names:
        station = get(conn, name)
        if station and station.has_coords:
            out[name] = (station.lat, station.lng)  # type: ignore[arg-type]
    return out
