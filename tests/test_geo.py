"""GPS 포그라운드 보정 (PLAN 10절, D-13/D-21).

핵심 두 가지:
1. 신선도 안전장치 — 낡거나 부정확한 좌표는 아예 안 쓴다 (D-21)
2. 선분 투영 — 역 좌표가 있는 인접 구간에만 투영하고, 노선에서 크게 벗어나면
   None을 돌려줘 호출부가 시각표 추정으로 폴백하게 한다 (D-13)
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.geo import (
    DEFAULT_GEO,
    REJECT_FUTURE,
    REJECT_INACCURATE,
    REJECT_NO_COORDS,
    REJECT_OFF_ROUTE,
    REJECT_STALE,
    GeoConfig,
    GeoFix,
    _point_segment_distance_m,
    _to_plane,
    fix_rejection,
    is_fix_usable,
    project_onto_route,
    project_onto_route_detail,
)
from app.domain.models import KST

NOW = datetime(2026, 8, 5, 8, 30, tzinfo=KST)

# 실제 station 테이블에서 확보한 좌표 (경부선, 천안~수원) — 임의 좌표가 아니라
# 실측값을 써서 "말이 되는 거리"인지 감으로도 검증되게 한다.
CHEONAN = (36.808837, 127.1471716)
PYEONGTAEK = (36.995815, 127.082538)
SUWON = (37.26608, 126.999231)
BUSAN = (35.115, 129.042)  # 완전히 다른 노선 — 오매칭 대조군


def fix(*, age_seconds: float = 0, accuracy_m: float = 20.0, lat=0.0, lng=0.0) -> GeoFix:
    return GeoFix(
        lat=lat, lng=lng, accuracy_m=accuracy_m, fixed_at=NOW - timedelta(seconds=age_seconds)
    )


# ── 신선도 안전장치 ──────────────────────────────────────────────────────
def test_fresh_accurate_fix_is_usable() -> None:
    assert is_fix_usable(fix(age_seconds=5, accuracy_m=15), now=NOW) is True


def test_stale_fix_is_rejected() -> None:
    assert is_fix_usable(fix(age_seconds=31), now=NOW) is False


def test_fix_at_exact_age_boundary_is_usable() -> None:
    """`30초 초과`가 거부 조건이므로 정확히 30초는 통과해야 한다."""
    assert is_fix_usable(fix(age_seconds=30.0), now=NOW) is True


def test_inaccurate_fix_is_rejected() -> None:
    assert is_fix_usable(fix(accuracy_m=150), now=NOW) is False


def test_fix_at_exact_accuracy_boundary_is_usable() -> None:
    assert is_fix_usable(fix(accuracy_m=100.0), now=NOW) is True


def test_future_fixed_at_is_rejected() -> None:
    """시계 오차로 미래 시각이 와도 '낡음'과 같은 방향으로 안전하게 거부한다."""
    assert is_fix_usable(fix(age_seconds=-5), now=NOW) is False


def test_naive_fixed_at_raises() -> None:
    naive = GeoFix(lat=0, lng=0, accuracy_m=10, fixed_at=datetime(2026, 8, 5, 8, 30))
    with pytest.raises(ValueError):
        is_fix_usable(naive, now=NOW)


def test_naive_now_raises() -> None:
    with pytest.raises(ValueError):
        is_fix_usable(fix(), now=datetime(2026, 8, 5, 8, 30))


def test_custom_config_thresholds() -> None:
    strict = GeoConfig(max_fix_age_seconds=5.0, max_accuracy_m=10.0)
    assert is_fix_usable(fix(age_seconds=10), now=NOW, config=strict) is False
    assert is_fix_usable(fix(age_seconds=3, accuracy_m=8), now=NOW, config=strict) is True


# ── 거부 사유 구조화 (D-59) ──────────────────────────────────────────────
def test_fix_rejection_none_when_usable() -> None:
    assert fix_rejection(fix(age_seconds=5, accuracy_m=15), now=NOW) is None


def test_fix_rejection_stale_reports_age_and_limit() -> None:
    rej = fix_rejection(fix(age_seconds=31), now=NOW)
    assert rej is not None
    assert rej.reason == REJECT_STALE
    assert rej.value == pytest.approx(31.0)
    assert rej.limit == 30.0


def test_fix_rejection_future_reports_negative_age() -> None:
    rej = fix_rejection(fix(age_seconds=-5), now=NOW)
    assert rej is not None
    assert rej.reason == REJECT_FUTURE
    assert rej.value is not None and rej.value < 0


def test_fix_rejection_inaccurate_reports_accuracy() -> None:
    rej = fix_rejection(fix(accuracy_m=150), now=NOW)
    assert rej is not None
    assert rej.reason == REJECT_INACCURATE
    assert rej.value == pytest.approx(150.0)
    assert rej.limit == 100.0


def test_fix_rejection_checks_age_before_accuracy() -> None:
    """낡음과 부정확이 동시면 검사 순서대로 stale이 먼저 보고된다 (기존 로직 순서 유지)."""
    rej = fix_rejection(fix(age_seconds=31, accuracy_m=150), now=NOW)
    assert rej is not None and rej.reason == REJECT_STALE


def test_is_fix_usable_equals_fix_rejection_is_none() -> None:
    for f in (fix(age_seconds=5), fix(age_seconds=31), fix(accuracy_m=150), fix(age_seconds=-5)):
        assert is_fix_usable(f, now=NOW) == (fix_rejection(f, now=NOW) is None)


# ── 투영 상세 (거리·사유) ────────────────────────────────────────────────
def test_project_detail_success_carries_distance() -> None:
    lat, lng = _midpoint(CHEONAN, PYEONGTAEK)
    proj = project_onto_route_detail(STOPS, COORDS, lat, lng)
    assert proj.seg_idx == 0
    assert proj.rejection is None
    assert proj.distance_m is not None and proj.distance_m < 300


def test_project_detail_off_route_reports_best_distance_and_limit() -> None:
    proj = project_onto_route_detail(STOPS, COORDS, *BUSAN)
    assert proj.seg_idx is None
    assert proj.rejection is not None
    assert proj.rejection.reason == REJECT_OFF_ROUTE
    assert proj.rejection.value is not None and proj.rejection.value > 300
    assert proj.rejection.limit == 300.0
    assert proj.distance_m == proj.rejection.value  # 실패해도 최근접 거리는 채운다


def test_project_detail_no_coords() -> None:
    for coords in ({}, {"천안": CHEONAN, "수원": SUWON}):  # 빈 사전 · 평택 빠져 후보 0개
        proj = project_onto_route_detail(STOPS, coords, *CHEONAN)
        assert proj.seg_idx is None
        assert proj.rejection is not None and proj.rejection.reason == REJECT_NO_COORDS
        assert proj.rejection.value is None and proj.rejection.limit is None


def test_project_onto_route_is_detail_seg_idx() -> None:
    lat, lng = _midpoint(PYEONGTAEK, SUWON)
    assert project_onto_route(STOPS, COORDS, lat, lng) == project_onto_route_detail(
        STOPS, COORDS, lat, lng
    ).seg_idx


# ── 평면 투영 헬퍼 (기하 오류가 조용히 나기 쉬운 지점) ───────────────────
def test_to_plane_scales_longitude_by_latitude_cosine() -> None:
    """위도가 올라갈수록 경도 1도의 실거리가 줄어든다 — 보정이 없으면 오차가 쌓인다."""
    x_at_equator, _ = _to_plane(0.0, 1.0, ref_lat=0.0)
    x_at_60, _ = _to_plane(60.0, 1.0, ref_lat=60.0)
    assert x_at_60 == pytest.approx(x_at_equator * 0.5, rel=1e-3)  # cos(60°) = 0.5


def test_point_segment_distance_zero_on_segment() -> None:
    assert _point_segment_distance_m(5, 0, 0, 0, 10, 0) == pytest.approx(0.0, abs=1e-6)


def test_point_segment_distance_perpendicular() -> None:
    assert _point_segment_distance_m(5, 3, 0, 0, 10, 0) == pytest.approx(3.0, abs=1e-6)


def test_point_segment_distance_clamps_beyond_endpoint() -> None:
    """선분 밖으로 넘어간 투영은 끝점 거리로 클램프돼야 한다."""
    assert _point_segment_distance_m(15, 0, 0, 0, 10, 0) == pytest.approx(5.0, abs=1e-6)
    assert _point_segment_distance_m(-5, 0, 0, 0, 10, 0) == pytest.approx(5.0, abs=1e-6)


def test_point_segment_distance_degenerate_segment() -> None:
    """A와 B가 같은 좌표(역 데이터 결함)여도 죽지 않고 점 거리를 낸다."""
    assert _point_segment_distance_m(3, 4, 0, 0, 0, 0) == pytest.approx(5.0, abs=1e-6)


# ── 선분 투영 (실제 노선) ────────────────────────────────────────────────
STOPS = ["천안", "평택", "수원"]
COORDS = {"천안": CHEONAN, "평택": PYEONGTAEK, "수원": SUWON}


def _midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def test_point_on_first_segment() -> None:
    lat, lng = _midpoint(CHEONAN, PYEONGTAEK)
    assert project_onto_route(STOPS, COORDS, lat, lng) == 0


def test_point_on_second_segment() -> None:
    lat, lng = _midpoint(PYEONGTAEK, SUWON)
    assert project_onto_route(STOPS, COORDS, lat, lng) == 1


def test_point_far_from_any_segment_returns_none() -> None:
    """★ 완전히 다른 노선(부산)에 있으면 오매칭하지 말고 None — 시각표 추정으로 폴백."""
    lat, lng = BUSAN
    assert project_onto_route(STOPS, COORDS, lat, lng) is None


def test_point_slightly_off_route_within_tolerance() -> None:
    """선분에서 살짝 벗어나도(정차역 인근 오차) 기본 허용치(300m) 안이면 잡는다."""
    lat, lng = _midpoint(CHEONAN, PYEONGTAEK)
    assert project_onto_route(STOPS, COORDS, lat + 0.001, lng) == 0  # 위도로 ~111m 이동


def test_missing_station_coords_excludes_that_segment() -> None:
    """★ 한쪽 역이라도 좌표가 없으면 그 구간은 후보에서 빠진다 — 조용히 틀린 구간을 고르지 않는다."""
    partial = {"천안": CHEONAN, "수원": SUWON}  # 평택 좌표 없음 → 두 구간 다 제외
    lat, lng = _midpoint(CHEONAN, PYEONGTAEK)
    assert project_onto_route(STOPS, partial, lat, lng) is None


def test_no_coords_at_all_returns_none() -> None:
    assert project_onto_route(STOPS, {}, *CHEONAN) is None


def test_project_is_limited_to_given_stops_candidates() -> None:
    """후보를 `stops` 내 역으로만 한정 — 좌표 사전에 다른 노선 역이 섞여 있어도 무시한다."""
    coords = dict(COORDS)
    coords["서울"] = (37.5547, 126.9707)  # stops에 없는 역
    lat, lng = _midpoint(CHEONAN, PYEONGTAEK)
    assert project_onto_route(STOPS, coords, lat, lng) == 0


def test_custom_route_distance_threshold() -> None:
    lat, lng = _midpoint(CHEONAN, PYEONGTAEK)
    tight = GeoConfig(max_route_distance_m=1.0)  # 1m — 거의 모든 오차를 거부
    assert project_onto_route(STOPS, COORDS, lat + 0.001, lng, config=tight) is None
