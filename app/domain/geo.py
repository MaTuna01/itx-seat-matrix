"""GPS 포그라운드 보정 — 인접역 선분 투영 (PLAN.md 10절, D-13).

순수 함수만. 좌표 조회(station 테이블)는 api 계층이 하고 여기는 계산만 한다
(CLAUDE.md 절대규칙 4).

## 판정 방식 (D-13, D-17)

역 '점'과의 최근접 비교는 역간 거리가 짧은 도심 구간·병주 구간에서 애매하다.
대신 `stops` 내 **인접 두 역을 잇는 선분**에 GPS 좌표를 투영해 진행률로 구간을
확정한다. 후보를 `stops` 내 역으로만 한정하므로 타 노선 역 오매칭이 원천 차단된다.

좌표는 위경도(도) 그대로 유클리드 거리를 재지 않는다 — 위도 1도와 경도 1도가
실제 거리로 다르기 때문에(위도가 올라갈수록 경도 1도의 거리가 줄어든다),
등장방형(equirectangular) 근사로 평면 좌표로 바꾼 뒤 투영한다. ITX 이동거리
(최대 수백km)에서 이 근사의 오차는 무시할 수준이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

EARTH_RADIUS_M = 6_371_000.0

# GPS를 안 쓴 이유의 고정 어휘 (D-59). 도메인은 사용자 문구를 모른다 —
# api 계층(`app/api/trains.py`)이 이 값을 한국어 `position_note`로 바꾼다.
REJECT_STALE = "stale"  # 좌표가 max_fix_age_seconds보다 낡음
REJECT_FUTURE = "future"  # fixed_at > now (기기 시계 오차)
REJECT_INACCURATE = "inaccurate"  # accuracy_m > max_accuracy_m
REJECT_NO_COORDS = "no_coords"  # 양 끝 좌표를 가진 인접 구간이 하나도 없음
REJECT_OFF_ROUTE = "off_route"  # 최근접 구간이 max_route_distance_m보다 멂 (탑승 전/하차 후)


@dataclass(frozen=True)
class GeoConfig:
    """조정 예정 값은 설정을 가진 순수 함수로 격리한다 (D-17).

    수치는 실사용 전 잠정값 — Phase 4 '실사용 몇 주 후 조정' 대상에 포함된다.
    """

    max_fix_age_seconds: float = 30.0  # D-21: 30초 초과 낡은 좌표는 무시
    max_accuracy_m: float = 100.0  # 정확도 반경이 이보다 크면 무시
    max_route_distance_m: float = 300.0  # 선분에서 이만큼 벗어나면 노선 밖으로 간주


DEFAULT_GEO = GeoConfig()


@dataclass(frozen=True)
class GeoFix:
    """클라이언트가 보낸 GPS 원시값. `Geolocation.getCurrentPosition()` 1:1."""

    lat: float
    lng: float
    accuracy_m: float
    fixed_at: datetime  # 좌표를 측정한 시각 (KST aware)


@dataclass(frozen=True)
class GeoRejection:
    """좌표를 안 쓴 이유 + 관측값/임계값 (D-59).

    `value`(관측: 나이 초 / 정확도 m / 이탈 거리 m)와 `limit`(비교한 임계값)이
    쌍으로 있어야 실사용 분포를 보고 GeoConfig를 조정할 수 있다 (D-30이 남긴 Phase 4 신호).
    `no_coords`는 관측할 수치가 없어 둘 다 None.
    """

    reason: str
    value: float | None = None
    limit: float | None = None


def fix_rejection(
    fix: GeoFix, *, now: datetime, config: GeoConfig = DEFAULT_GEO
) -> GeoRejection | None:
    """신선도 검사 (D-21) — 문제가 있으면 사유를, 없으면 None. 검사 순서는 고정이다
    (future → stale → inaccurate): 같은 좌표가 여러 조건을 어겨도 첫 사유만 보고한다.
    """
    if fix.fixed_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("naive datetime은 허용하지 않는다 (KST aware 필수, PLAN 3절)")
    age = now - fix.fixed_at
    age_s = age.total_seconds()
    if age < timedelta(0):
        # 시계 오차로 미래 시각이 와도 "낡음"과 같은 방향으로 안전하게 거부한다
        return GeoRejection(REJECT_FUTURE, value=age_s, limit=0.0)
    if age > timedelta(seconds=config.max_fix_age_seconds):
        return GeoRejection(REJECT_STALE, value=age_s, limit=config.max_fix_age_seconds)
    if fix.accuracy_m > config.max_accuracy_m:
        return GeoRejection(REJECT_INACCURATE, value=fix.accuracy_m, limit=config.max_accuracy_m)
    return None


def is_fix_usable(fix: GeoFix, *, now: datetime, config: GeoConfig = DEFAULT_GEO) -> bool:
    """신선도 안전장치 (D-21) — 낡았거나 부정확하면 좌표를 아예 쓰지 않는다.

    `now`는 인자로 받는다 (D-21 공통 구현 규칙, 테스트 가능성).
    사유가 필요하면 `fix_rejection`을 쓴다 — 이 함수는 그 얇은 불리언 래퍼다.
    """
    return fix_rejection(fix, now=now, config=config) is None


def _to_plane(lat: float, lng: float, ref_lat: float) -> tuple[float, float]:
    """등장방형 근사로 (경도, 위도)를 평면 미터 좌표로. `ref_lat`는 구간의 대표 위도.

    경도 1도의 실거리는 `cos(위도)`에 비례해 줄어든다 — 이 보정이 없으면
    남북으로 뻗은 노선일수록 오차가 커진다.
    """
    x = math.radians(lng) * math.cos(math.radians(ref_lat)) * EARTH_RADIUS_M
    y = math.radians(lat) * EARTH_RADIUS_M
    return x, y


def _point_segment_distance_m(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """점 P를 선분 AB에 투영했을 때의 최단 거리(미터). 투영은 [0,1]로 클램프된다."""
    abx, aby = bx - ax, by - ay
    seg_len_sq = abx * abx + aby * aby
    if seg_len_sq == 0:  # A와 B가 같은 좌표 (역 위치 데이터 결함)
        t = 0.0
    else:
        t = ((px - ax) * abx + (py - ay) * aby) / seg_len_sq
        t = max(0.0, min(1.0, t))
    closest_x, closest_y = ax + t * abx, ay + t * aby
    return math.hypot(px - closest_x, py - closest_y)


@dataclass(frozen=True)
class RouteProjection:
    """선분 투영 결과 (D-59).

    성공(`seg_idx is not None`)해도 `distance_m`를 채운다 — 300m 이탈 임계값을
    실사용 분포로 조정하려면 "성공했지만 얼마나 아슬아슬했나"가 필요하다.
    실패면 `rejection`으로 이유를 준다.
    """

    seg_idx: int | None
    distance_m: float | None
    rejection: GeoRejection | None


def project_onto_route_detail(
    stops: list[str],
    station_coords: dict[str, tuple[float, float]],
    lat: float,
    lng: float,
    *,
    config: GeoConfig = DEFAULT_GEO,
) -> RouteProjection:
    """GPS 좌표를 `stops`의 인접 구간 선분들에 투영한다. 사유·거리까지 돌려주는 상세판.

    후보는 **양 끝 역 모두 좌표를 가진 구간**으로 한정한다 — 한쪽이라도 좌표가
    없으면 그 구간은 판정에서 제외한다(조용히 틀린 구간을 고르지 않는다). 후보가
    하나도 없으면 `no_coords`, 최근접이 `max_route_distance_m`보다 멀면 `off_route`.

    반환 인덱스는 `stops` 전체 노선 기준이다 (D-18 인덱스 규칙과 동일 기준).
    """
    candidates: list[tuple[float, int]] = []
    for i, (frm, to) in enumerate(zip(stops, stops[1:])):
        a = station_coords.get(frm)
        b = station_coords.get(to)
        if a is None or b is None:
            continue
        ref_lat = (a[0] + b[0]) / 2
        px, py = _to_plane(lat, lng, ref_lat)
        ax, ay = _to_plane(a[0], a[1], ref_lat)
        bx, by = _to_plane(b[0], b[1], ref_lat)
        distance = _point_segment_distance_m(px, py, ax, ay, bx, by)
        candidates.append((distance, i))

    if not candidates:
        return RouteProjection(seg_idx=None, distance_m=None, rejection=GeoRejection(REJECT_NO_COORDS))
    best_distance, best_idx = min(candidates, key=lambda c: c[0])
    if best_distance > config.max_route_distance_m:
        return RouteProjection(
            seg_idx=None,
            distance_m=best_distance,
            rejection=GeoRejection(REJECT_OFF_ROUTE, value=best_distance, limit=config.max_route_distance_m),
        )
    return RouteProjection(seg_idx=best_idx, distance_m=best_distance, rejection=None)


def project_onto_route(
    stops: list[str],
    station_coords: dict[str, tuple[float, float]],
    lat: float,
    lng: float,
    *,
    config: GeoConfig = DEFAULT_GEO,
) -> int | None:
    """가장 가까운 구간 인덱스만 필요한 호출부용 얇은 래퍼. 사유·거리는 `project_onto_route_detail`."""
    return project_onto_route_detail(stops, station_coords, lat, lng, config=config).seg_idx
