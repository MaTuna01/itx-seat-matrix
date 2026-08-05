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
    usable: bool = False  # 여객역으로 확인됨 → 드롭다운 노출 (004_station.sql 주석 참고)

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lng is not None


def upsert(conn: sqlite3.Connection, station: Station, *, source: str, now: datetime) -> None:
    """이름 기준 upsert. **이미 있는 값을 NULL로 덮지 않는다.**

    좌표 CSV와 역코드 CSV가 서로 다른 컬럼을 채우므로, 두 파일을 순서와 무관하게
    적재해도 합쳐지도록 `COALESCE(새 값, 기존 값)`으로 병합한다. 이게 없으면
    나중에 적재한 파일이 앞선 파일의 컬럼을 지워버린다.

    `usable`도 같은 이유로 **끄는 방향으로는 덮지 않는다**(`MAX`). 한 번 여객역으로
    확정된 역을 나중에 다른 파일 적재로 0으로 되돌리면 드롭다운이 조용히 비어버린다.

    `usable`은 **좌표 유무로 추론하지 않는다.** 적재하는 쪽이 명시해야 한다 (D-28 개정) —
    '전국 도시철도역사정보'처럼 좌표가 있어도 ITX가 서지 않는 역이 1,100개나 되는
    파일이 있어서, 좌표를 근거로 삼으면 드롭다운이 지하철역으로 범람한다.
    """
    usable = 1 if station.usable else 0
    conn.execute(
        "INSERT INTO station (name, code, lat, lng, line, usable, source, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(name) DO UPDATE SET"
        "   code = COALESCE(excluded.code, station.code),"
        "   lat  = COALESCE(excluded.lat,  station.lat),"
        "   lng  = COALESCE(excluded.lng,  station.lng),"
        "   line = COALESCE(excluded.line, station.line),"
        "   usable = MAX(excluded.usable, station.usable),"
        "   source = excluded.source,"
        "   updated_at = excluded.updated_at",
        (
            station.name,
            station.code,
            station.lat,
            station.lng,
            station.line,
            usable,
            source,
            to_db(now),
        ),
    )


def fill_coords_only(
    conn: sqlite3.Connection, station: Station, *, source: str, now: datetime
) -> bool:
    """**이미 있는 역의 좌표만** 채운다. 없는 역은 만들지 않는다.

    '전국 도시철도역사정보'(1,100행)처럼 우리 유니버스보다 넓은 좌표 소스를 쓸 때
    필요하다. 그 파일에는 `강남`·`신사`처럼 ITX가 서지 않는 지하철역이 대부분인데,
    새로 넣으면 역 테이블이 지하철로 뒤덮인다. **코레일 역코드 사전에 있는 역**
    (= 코레일이 운영하는 지점)에만 좌표를 얹는 것이 이 함수의 목적이다.

    반환값은 실제로 갱신했는지 여부.
    """
    if not station.has_coords:
        return False
    cur = conn.execute(
        "UPDATE station SET"
        "   lat = COALESCE(lat, ?),"
        "   lng = COALESCE(lng, ?),"
        "   line = COALESCE(line, ?),"
        "   updated_at = ?"
        " WHERE name = ? AND (lat IS NULL OR lng IS NULL)",
        (station.lat, station.lng, station.line, to_db(now), station.name),
    )
    return cur.rowcount > 0


def mark_usable(
    conn: sqlite3.Connection,
    names: list[str],
    *,
    now: datetime,
    codes: dict[str, str] | None = None,
) -> int:
    """시각표에 정차역으로 등장한 역을 여객역으로 확정한다.

    열차가 서는 곳이면 여객역이다 — 이름 목록을 하드코딩하지 않고 데이터로 판별하는
    두 번째 경로다 (원칙 1). 아직 없는 역은 이름만으로 새로 만든다.

    `codes`(역명 → 역코드)를 주면 **역코드를 덮어쓴다**. 역코드 CSV에는 같은 역명에
    구/신 코드가 함께 있는 경우가 있는데(`경주` 3900647/3900895 등), 어느 쪽이
    현재 쓰이는 코드인지는 CSV만으로 알 수 없다. **시각표가 그 답을 안다** —
    열차가 실제로 그 코드로 운행하므로 여기서는 시각표 값을 권위로 삼는다.
    """
    codes = codes or {}
    touched = 0
    for raw in names:
        name = normalize_name(raw)
        if not name:
            continue
        code = codes.get(raw) or codes.get(name)
        conn.execute(
            "INSERT INTO station (name, code, usable, source, updated_at)"
            " VALUES (?, ?, 1, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET"
            "   usable = 1,"
            "   code = COALESCE(excluded.code, station.code),"
            "   source = excluded.source,"
            "   updated_at = excluded.updated_at",
            (name, code, "timetable", to_db(now)),
        )
        touched += 1
    return touched


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM station").fetchone()[0]


def count_with_coords(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM station WHERE lat IS NOT NULL AND lng IS NOT NULL"
    ).fetchone()[0]


def count_usable(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM station WHERE usable = 1").fetchone()[0]


def list_usable(conn: sqlite3.Connection) -> list[StationInfo]:
    """드롭다운 소스 (D-25). **여객역으로 확인된 것만**, 이름 오름차순.

    역코드 CSV에는 '본청'·'구로열차소'처럼 열차를 탈 수 없는 지점이 절반 이상 섞여
    있다. 그것을 그대로 노출하면 사용자가 고를 수 없는 역을 고르게 된다.
    """
    rows = conn.execute(
        "SELECT name, code FROM station WHERE usable = 1 ORDER BY name"
    ).fetchall()
    return [StationInfo(name=r["name"], code=r["code"]) for r in rows]


def get(conn: sqlite3.Connection, name: str) -> Station | None:
    """역 1개 조회. `usable` 여부와 무관하게 찾는다 — 코드 사전 용도도 겸한다."""
    row = conn.execute(
        "SELECT name, code, lat, lng, line, usable FROM station WHERE name = ?",
        (normalize_name(name),),
    ).fetchone()
    if row is None:
        return None
    return Station(
        name=row["name"],
        code=row["code"],
        lat=row["lat"],
        lng=row["lng"],
        line=row["line"],
        usable=bool(row["usable"]),
    )


def code_for(conn: sqlite3.Connection, name: str) -> str | None:
    """역명 → 공공데이터 역코드. 이 CSV의 코드 체계는 운행정보 API의 `stn_cd`와 같다
    (`3900023 서울`, `3900883 광명`이 양쪽에서 일치함을 실측 확인)."""
    station = get(conn, name)
    return station.code if station else None


def coords_for(conn: sqlite3.Connection, names: list[str]) -> dict[str, tuple[float, float]]:
    """GPS 선분 투영용 좌표 조회 (D-13). 좌표 없는 역은 결과에서 빠진다."""
    out: dict[str, tuple[float, float]] = {}
    for name in names:
        station = get(conn, name)
        if station and station.has_coords:
            out[name] = (station.lat, station.lng)  # type: ignore[arg-type]
    return out
