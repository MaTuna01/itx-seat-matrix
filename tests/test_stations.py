"""역 마스터 — 정규화 / 병합 적재 / 드롭다운 소스 (Phase 2 항목 G, D-25).

가장 중요한 것은 **역명 정규화**다. 세 소스(공공데이터 운행정보 / 좌표 CSV / korail2)의
역코드 체계가 서로 달라 역명이 유일한 조인 축인데, 표기가 조금씩 다르면
조용히 조인이 깨진다 (에러가 아니라 '좌표 없는 역'으로 나타난다).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from app.domain.models import KST
from app.storage.db import connect, init_db
from app.storage.stations import (
    Station,
    coords_for,
    count,
    count_with_coords,
    get,
    list_all,
    normalize_name,
    upsert,
)

NOW = datetime(2026, 8, 5, 9, 0, tzinfo=KST)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "stations.db"
    init_db(path)
    c = connect(path)
    try:
        yield c
    finally:
        c.close()


# ── 역명 정규화 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("수원", "수원"),
        ("  수원  ", "수원"),
        ("수원역", "수원"),
        ("서울역", "서울"),
        ("수원(수원역)", "수원"),
        ("서울(경부)", "서울"),
        ("동대구  ", "동대구"),
        ("영등포 ", "영등포"),
        ("청량리（1）", "청량리"),  # 전각 괄호
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_normalize_keeps_single_char_name() -> None:
    """'역'을 떼면 빈 문자열이 되는 경우는 남긴다."""
    assert normalize_name("역") == "역"


def test_normalize_handles_none_and_blank() -> None:
    assert normalize_name("") == ""
    assert normalize_name(None) == ""  # type: ignore[arg-type]


def test_normalize_makes_variants_join() -> None:
    """★ 이게 깨지면 좌표 조인이 조용히 실패한다."""
    assert normalize_name("서울역") == normalize_name("서울") == normalize_name(" 서울 ")


# ── 병합 적재 ────────────────────────────────────────────────────────────
def test_upsert_inserts(conn: sqlite3.Connection) -> None:
    upsert(conn, Station(name="수원", code="3900032"), source="codes.csv", now=NOW)
    got = get(conn, "수원")
    assert got is not None and got.code == "3900032"
    assert count(conn) == 1


def test_two_files_merge_by_name(conn: sqlite3.Connection) -> None:
    """★ 역코드 파일과 좌표 파일을 따로 적재해도 역명 기준으로 합쳐진다."""
    upsert(conn, Station(name="수원", code="3900032"), source="codes.csv", now=NOW)
    upsert(conn, Station(name="수원", lat=37.2656, lng=127.0002), source="coords.csv", now=NOW)

    got = get(conn, "수원")
    assert got is not None
    assert got.code == "3900032"  # 앞선 파일의 값이 지워지지 않았다
    assert (got.lat, got.lng) == (37.2656, 127.0002)
    assert got.has_coords


def test_merge_is_order_independent(conn: sqlite3.Connection) -> None:
    """반대 순서로 적재해도 결과가 같아야 한다."""
    upsert(conn, Station(name="수원", lat=37.2656, lng=127.0002), source="coords.csv", now=NOW)
    upsert(conn, Station(name="수원", code="3900032"), source="codes.csv", now=NOW)

    got = get(conn, "수원")
    assert got is not None and got.code == "3900032" and got.has_coords


def test_null_does_not_overwrite_existing(conn: sqlite3.Connection) -> None:
    """NULL로 기존 값을 덮으면 나중 파일이 앞선 파일을 지워버린다."""
    upsert(conn, Station(name="수원", code="3900032", lat=37.2, lng=127.0), source="a", now=NOW)
    upsert(conn, Station(name="수원"), source="b", now=NOW)

    got = get(conn, "수원")
    assert got is not None and got.code == "3900032" and got.has_coords


def test_get_normalizes_lookup(conn: sqlite3.Connection) -> None:
    upsert(conn, Station(name="서울", lat=37.55, lng=126.97), source="a", now=NOW)
    assert get(conn, "서울역") is not None
    assert get(conn, "  서울  ") is not None


def test_count_with_coords(conn: sqlite3.Connection) -> None:
    upsert(conn, Station(name="수원", lat=37.2, lng=127.0), source="a", now=NOW)
    upsert(conn, Station(name="평택", code="123"), source="a", now=NOW)
    assert count(conn) == 2
    assert count_with_coords(conn) == 1


def test_coords_for_skips_stations_without_coords(conn: sqlite3.Connection) -> None:
    """좌표 없는 역은 GPS 투영 대상에서 빠진다 (D-13)."""
    upsert(conn, Station(name="수원", lat=37.2, lng=127.0), source="a", now=NOW)
    upsert(conn, Station(name="평택"), source="a", now=NOW)

    got = coords_for(conn, ["수원", "평택", "없는역"])
    assert got == {"수원": (37.2, 127.0)}


def test_list_all_is_sorted(conn: sqlite3.Connection) -> None:
    for name in ("평택", "서울", "수원"):
        upsert(conn, Station(name=name), source="a", now=NOW)
    assert [s.name for s in list_all(conn)] == sorted(["평택", "서울", "수원"])


# ── CSV 헤더 매핑 ────────────────────────────────────────────────────────
def test_header_mapping_recognizes_korean_columns() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "load_stations", "scripts/load_stations.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 한국철도공사_역 위치 정보 (15127532)의 실제 헤더
    mapping, unknown = mod.map_headers(["지역본부", "역명", "위도", "경도", "출입구 개수"])
    assert mapping["name"] == "역명"
    assert mapping["lat"] == "위도"
    assert mapping["lng"] == "경도"
    assert "출입구 개수" in unknown  # 못 알아본 컬럼은 조용히 무시하되 보고한다

    mapping2, _ = mod.map_headers(["역코드", "역명"])
    assert mapping2["code"] == "역코드" and mapping2["name"] == "역명"


# ── API ──────────────────────────────────────────────────────────────────
def test_api_falls_back_to_mock_when_table_empty(client) -> None:
    """테이블을 아직 적재하지 않은 개발 환경에서 화면이 죽지 않아야 한다."""
    res = client.get("/api/stations")
    assert res.status_code == 200
    assert [s["name"] for s in res.json()] == ["천안", "평택", "수원", "안양", "영등포", "서울"]


def test_api_prefers_station_table(client) -> None:
    from app.storage.db import connect

    c = connect()
    try:
        upsert(c, Station(name="대전", code="3900112"), source="test", now=NOW)
        upsert(c, Station(name="김천", code="3900123"), source="test", now=NOW)
    finally:
        c.close()

    res = client.get("/api/stations")
    assert res.status_code == 200
    assert [s["name"] for s in res.json()] == ["김천", "대전"]  # 테이블이 이긴다


def test_api_requires_auth(anon_client) -> None:
    assert anon_client.get("/api/stations").status_code == 401
