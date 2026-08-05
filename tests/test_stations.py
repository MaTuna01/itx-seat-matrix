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
    code_for,
    coords_for,
    count,
    count_usable,
    count_with_coords,
    get,
    list_usable,
    mark_usable,
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


def test_list_usable_is_sorted(conn: sqlite3.Connection) -> None:
    for name in ("평택", "서울", "수원"):
        upsert(conn, Station(name=name, usable=True), source="a", now=NOW)
    assert [s.name for s in list_usable(conn)] == sorted(["평택", "서울", "수원"])


# ── usable: 여객역과 운영 지점 구분 ──────────────────────────────────────
def test_code_dictionary_rows_are_not_usable(conn: sqlite3.Connection) -> None:
    """★ 역코드 CSV의 '본청'·'구로열차소'가 드롭다운에 새면 안 된다."""
    for name in ("본청", "구로열차소", "송도교"):
        upsert(conn, Station(name=name, code="390000x"), source="역코드.csv", now=NOW)
    assert count(conn) == 3
    assert count_usable(conn) == 0
    assert list_usable(conn) == []


def test_coords_imply_usable(conn: sqlite3.Connection) -> None:
    """좌표 CSV(15127532)는 정의상 간선 여객역이므로 좌표가 근거가 된다."""
    upsert(conn, Station(name="수원", lat=37.2656, lng=127.0002), source="좌표.csv", now=NOW)
    assert count_usable(conn) == 1
    assert [s.name for s in list_usable(conn)] == ["수원"]


def test_timetable_marks_usable(conn: sqlite3.Connection) -> None:
    """열차가 서는 곳이면 여객역이다 — 두 번째 데이터 근거 (원칙 1)."""
    upsert(conn, Station(name="평택", code="3900057"), source="역코드.csv", now=NOW)
    assert count_usable(conn) == 0

    mark_usable(conn, ["평택역", "  천안 "], now=NOW)  # 정규화도 거친다
    assert sorted(s.name for s in list_usable(conn)) == ["천안", "평택"]
    assert get(conn, "평택").code == "3900057"  # 기존 코드가 지워지지 않았다


def test_usable_is_never_turned_off_by_relaod(conn: sqlite3.Connection) -> None:
    """코드 사전을 다시 적재해도 usable이 0으로 되돌아가면 안 된다.

    되돌아가면 드롭다운이 조용히 비어버린다 — 에러 없이 기능이 사라지는 종류의 사고다.
    """
    upsert(conn, Station(name="수원", lat=37.2, lng=127.0), source="좌표.csv", now=NOW)
    upsert(conn, Station(name="수원", code="3900047"), source="역코드.csv", now=NOW)
    assert count_usable(conn) == 1


def test_code_for_resolves_public_data_code(conn: sqlite3.Connection) -> None:
    """이 CSV의 코드 체계는 운행정보 API의 stn_cd와 같다 (실측 확인)."""
    upsert(conn, Station(name="서울", code="3900023"), source="역코드.csv", now=NOW)
    assert code_for(conn, "서울역") == "3900023"
    assert code_for(conn, "없는역") is None


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


def test_header_mapping_handles_name_with_code_in_parens() -> None:
    """★ 공공데이터는 `역코드(STN_CD)` 형태를 자주 쓴다.

    통째로 슬러그를 만들면 어느 별칭과도 안 맞아 컬럼이 조용히 버려진다.
    실제 파일(한국철도공사_철도운영정보_역코드_20240901)의 헤더로 확인한다.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("load_stations", "scripts/load_stations.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mapping, unknown = mod.map_headers(
        ["역코드(STN_CD)", "역명(STN_NM)", "역약어명(STN_AVVR_NM)"]
    )
    assert mapping["code"] == "역코드(STN_CD)"
    assert mapping["name"] == "역명(STN_NM)"
    assert unknown == ["역약어명(STN_AVVR_NM)"]  # 약어는 쓰지 않는다


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
        upsert(c, Station(name="대전", code="3900112", usable=True), source="test", now=NOW)
        upsert(c, Station(name="김천", code="3900123", usable=True), source="test", now=NOW)
    finally:
        c.close()

    res = client.get("/api/stations")
    assert res.status_code == 200
    assert [s["name"] for s in res.json()] == ["김천", "대전"]  # 테이블이 이긴다


def test_api_requires_auth(anon_client) -> None:
    assert anon_client.get("/api/stations").status_code == 401


def test_api_falls_back_when_only_code_dictionary_loaded(client) -> None:
    """★ 역코드 CSV만 적재된 상태에서 드롭다운에 '본청'이 새면 안 된다.

    여객역 확정 근거가 없으면 Mock 노선으로 폴백하는 편이, 고를 수 없는 역을
    1,255개 늘어놓는 것보다 낫다.
    """
    from app.storage.db import connect

    c = connect()
    try:
        for name in ("본청", "구로열차소", "송도교"):
            upsert(c, Station(name=name, code="3900001"), source="역코드.csv", now=NOW)
    finally:
        c.close()

    names = [s["name"] for s in client.get("/api/stations").json()]
    assert "본청" not in names
    assert names == ["천안", "평택", "수원", "안양", "영등포", "서울"]  # Mock 폴백


# ── 역코드 충돌 (폐역·이설로 구/신 코드가 함께 남은 경우) ────────────────
def _loader():
    import importlib.util

    spec = importlib.util.spec_from_file_location("load_stations", "scripts/load_stations.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_find_code_collisions() -> None:
    mod = _loader()
    rows = [
        Station(name="경주", code="3900895"),
        Station(name="경주", code="3900647"),
        Station(name="수원", code="3900047"),
        Station(name="광주선분기", code="3900734"),
        Station(name="광주선분기", code="3900734"),  # 완전 중복은 충돌이 아니다
    ]
    assert mod.find_code_collisions(rows) == {"경주": ["3900647", "3900895"]}


def test_dedupe_is_deterministic_not_last_wins() -> None:
    """★ '마지막 행이 이긴다'로 두면 파일 정렬이 바뀌면 저장 코드도 바뀐다.

    재현되지 않는 적재는 디버깅이 불가능하다. 오름차순 첫 번째로 고정한다.
    """
    mod = _loader()
    forward = mod.dedupe([Station(name="경주", code="3900895"), Station(name="경주", code="3900647")])
    reverse = mod.dedupe([Station(name="경주", code="3900647"), Station(name="경주", code="3900895")])
    assert forward[0].code == reverse[0].code == "3900647"


def test_dedupe_fills_gaps_across_duplicate_rows() -> None:
    """코드는 첫 번째를 유지하되 빈 칸(좌표 등)은 뒤 행에서 메운다."""
    mod = _loader()
    out = mod.dedupe(
        [
            Station(name="수원", code="3900047"),
            Station(name="수원", code="3900999", lat=37.2, lng=127.0, line="경부선"),
        ]
    )
    assert len(out) == 1
    assert out[0].code == "3900047"  # 코드는 첫 번째
    assert out[0].has_coords and out[0].line == "경부선"  # 빈 칸은 메워졌다


def test_timetable_code_overrides_csv_ambiguity(conn: sqlite3.Connection) -> None:
    """★ 시각표가 권위다 — 열차가 실제로 쓰는 코드로 덮는다."""
    upsert(conn, Station(name="경주", code="3900647"), source="역코드.csv", now=NOW)
    mark_usable(conn, ["경주"], now=NOW, codes={"경주": "3900895"})

    got = get(conn, "경주")
    assert got is not None
    assert got.code == "3900895"
    assert got.usable
