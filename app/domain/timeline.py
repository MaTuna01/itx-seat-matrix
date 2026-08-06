"""구간 추정 + 폴 포인트 계산 (PLAN.md 5절 시각 규칙, 9절 스케줄러, D-18/D-19).

순수 함수만. **시간은 전부 `now: datetime` 인자로 주입받는다** — 내부에서
`datetime.now()`를 부르지 않는다 (D-21, 테스트 가능성).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.domain.models import KST, StopInfo


@dataclass(frozen=True)
class TimelineConfig:
    """조정 예정 값은 설정을 가진 순수 함수로 격리한다 (D-17)."""

    poll_offsets_min: tuple[int, ...] = (10, 4)  # 정차역 실효 도착 n분 전 (D-12)
    grace_min: int = 2  # 늦은 폴 유예 (D-19)


DEFAULT_TIMELINE = TimelineConfig()


def _require_aware(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("naive datetime은 허용하지 않는다 (KST aware 필수, PLAN 3절)")
    return now.astimezone(KST)


def effective_arrival(stop: StopInfo, delay_min: int) -> datetime:
    """실효 도착시각 = 시각표 도착시각 + 지연분 (PLAN 9절)."""
    return stop.arrival + timedelta(minutes=delay_min)


def estimate_seg(stops: list[StopInfo], delay_min: int, now: datetime) -> int:
    """현재 구간 인덱스 = `max i s.t. 실효도착(stops[i]) <= now` (PLAN 5절 시각 규칙).

    - 역 **정차 중에는 그 역부터의 구간**을 본다 (도착시각만 기준). "이번 역에서 탈
      사람이 산 자리"를 판정해야 하므로 이 방향이 맞다 (D-18).
    - 반환값은 구간 인덱스이므로 `[0, len(stops) - 2]`로 클램프한다.
      운행 전(첫 역 도착 전)은 0, 종착 이후는 마지막 구간.

    지연의 부호: 열차가 `delay_min`만큼 늦으면 실효 도착시각이 **뒤로** 밀리므로
    현재 구간은 오히려 앞(작은 인덱스)이 된다. PLAN 5절 본문의
    `arrival(stops[i]) <= now + 지연보정` 표기는 9절의 "실효 도착시각 = 시각표 + 지연분"과
    부호가 반대인데, 물리적으로 성립하는 9절 정의를 채택했다.
    """
    if len(stops) < 2:
        raise ValueError("stops는 최소 2개 이상이어야 한다")
    now = _require_aware(now)

    idx = 0
    for i, stop in enumerate(stops):
        if effective_arrival(stop, delay_min) <= now:
            idx = i
        else:
            break
    return min(idx, len(stops) - 2)


def compute_poll_points(
    stops: list[StopInfo],
    board_idx: int,
    alight_idx: int,
    delay_min: int = 0,
    config: TimelineConfig = DEFAULT_TIMELINE,
) -> list[datetime]:
    """폴 포인트 목록 = 이용 구간 각 정차역의 실효 도착시각 - offsets (PLAN 9절).

    범위는 `stops[board_idx] ~ stops[alight_idx - 1]`:
    - 탑승역 도착 전 조회는 그대로 두는 것이 **탑승 전 착석 가능 다이제스트**가 된다 (D-18)
    - 하차역 도착 전 조회는 취할 행동이 없으므로 제외한다 (호출량 최소화, PLAN 10절)

    반환값은 오름차순 정렬 + 중복 제거.
    """
    if not (0 <= board_idx < alight_idx <= len(stops) - 1):
        raise ValueError(f"구간 인덱스가 올바르지 않다: board={board_idx}, alight={alight_idx}")

    points: set[datetime] = set()
    for i in range(board_idx, alight_idx):
        eff = effective_arrival(stops[i], delay_min)
        for offset in config.poll_offsets_min:
            points.add(eff - timedelta(minutes=offset))
    return sorted(points)


def first_poll_at(
    poll_points: list[datetime],
    now: datetime,
    config: TimelineConfig = DEFAULT_TIMELINE,
) -> datetime | None:
    """구독 생성/갱신 시 기록할 첫 `next_poll_at` (D-19).

    이미 지난 포인트라도 grace 이내면 살린다 (재시작 직후 구독 갱신 대응).
    """
    now = _require_aware(now)
    grace = timedelta(minutes=config.grace_min)
    for point in poll_points:
        if point + grace >= now:
            return point
    return None


@dataclass(frozen=True)
class PollHint:
    """다음 자동 조회 안내 (화면 표시용, PLAN 7절 `next_poll`)."""

    station: str
    offset_min: int
    at: datetime


def next_poll_hint(
    stops: list[StopInfo],
    board_idx: int,
    alight_idx: int,
    delay_min: int,
    now: datetime,
    config: TimelineConfig = DEFAULT_TIMELINE,
) -> PollHint | None:
    """`now` 이후 가장 이른 폴 포인트를 (역, offset)과 함께 돌려준다."""
    now = _require_aware(now)
    hints: list[PollHint] = []
    for i in range(board_idx, alight_idx):
        eff = effective_arrival(stops[i], delay_min)
        for offset in config.poll_offsets_min:
            hints.append(PollHint(station=stops[i].name, offset_min=offset, at=eff - timedelta(minutes=offset)))
    upcoming = sorted((h for h in hints if h.at >= now), key=lambda h: h.at)
    return upcoming[0] if upcoming else None


@dataclass(frozen=True)
class PollDecision:
    """폴 포인터 전진 결과 (순수). 스케줄러는 이 결과대로 DB를 갱신한다."""

    fire: bool  # 지금 조회를 실행할지
    next_poll_at: datetime | None  # 전진시킨 포인터 (None = 남은 폴 포인트 없음)
    skipped: list[datetime] = field(default_factory=list)  # grace 초과로 버린 포인트


def resolve_poll(
    *,
    next_poll_at: datetime | None,
    poll_points: list[datetime],
    now: datetime,
    config: TimelineConfig = DEFAULT_TIMELINE,
) -> PollDecision:
    """`next_poll_at` 포인터를 현재 시각 기준으로 해석한다 (D-19, 멱등).

    - `now < next_poll_at` → 실행하지 않고 포인터 유지
    - `next_poll_at <= now <= next_poll_at + grace` → **실행**하고 다음 포인트로 전진
    - grace 초과 → **스킵**하고 다음 포인트로 전진 (낡은 시점의 조회는 다음 조회와 겹칠 뿐)

    재시작으로 여러 포인트가 한꺼번에 지났을 수 있으므로 스킵은 반복 적용한다.
    """
    if next_poll_at is None:
        return PollDecision(fire=False, next_poll_at=None)

    now = _require_aware(now)
    pointer = next_poll_at.astimezone(KST)
    grace = timedelta(minutes=config.grace_min)
    skipped: list[datetime] = []

    while True:
        if now < pointer:
            return PollDecision(fire=False, next_poll_at=pointer, skipped=skipped)
        if now <= pointer + grace:
            return PollDecision(fire=True, next_poll_at=_next_after(poll_points, pointer), skipped=skipped)
        skipped.append(pointer)
        nxt = _next_after(poll_points, pointer)
        if nxt is None:
            return PollDecision(fire=False, next_poll_at=None, skipped=skipped)
        pointer = nxt


def _next_after(poll_points: list[datetime], pointer: datetime) -> datetime | None:
    for point in sorted(poll_points):
        if point > pointer:
            return point
    return None


def is_ride_over(
    stops: list[StopInfo], alight_idx: int, delay_min: int, now: datetime
) -> bool:
    """하차역 실효 도착시각 경과 → 구독 만료 (PLAN 9절)."""
    now = _require_aware(now)
    return effective_arrival(stops[alight_idx], delay_min) <= now
