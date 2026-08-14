"""estimate_seg 경계 + 폴 포인터 전진 + grace 2분 (PLAN 13절, D-18/D-19/D-47)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.models import StopInfo
from app.domain.timeline import (
    TimelineConfig,
    compute_poll_points,
    estimate_seg,
    first_poll_at,
    is_ride_over,
    next_poll_hint,
    resolve_poll,
    sellable_seg_idx,
)
from tests.conftest import STOPS, at, stop_infos

# 시각표: 천안 08:00/08:03 · 평택 08:12/08:15 · 수원 08:26/08:29 · 안양 08:38/08:41 ·
#         영등포 08:48/08:51 · 서울 08:56(종착, 출발 없음)  — 도착/출발


class TestEstimateSeg:
    def test_운행_전에는_첫_구간(self):
        assert estimate_seg(stop_infos(), 0, at(7, 30)) == 0

    def test_주행_중_구간(self):
        # 08:14 = 평택(08:12) 지나 수원(08:26) 전 → 평택→수원 구간
        assert estimate_seg(stop_infos(), 0, at(8, 14)) == 1

    def test_역_정차_중에는_그_역부터의_구간(self):
        # 수원 도착시각 정각. "이번 역에서 탈 사람이 산 자리"를 봐야 하므로 수원→안양 (D-18)
        assert estimate_seg(stop_infos(), 0, at(8, 26)) == 2

    def test_종착_이후에는_마지막_구간으로_클램프(self):
        assert estimate_seg(stop_infos(), 0, at(9, 30)) == len(STOPS) - 2

    def test_지연이_반영되면_구간이_뒤로_밀린다(self):
        # 10분 지연이면 08:26에 열차는 아직 평택~수원 사이 (실효 도착 = 시각표 + 지연)
        assert estimate_seg(stop_infos(), 10, at(8, 26)) == 1
        assert estimate_seg(stop_infos(), 0, at(8, 26)) == 2

    def test_naive_datetime은_거부한다(self):
        with pytest.raises(ValueError):
            estimate_seg(stop_infos(), 0, datetime(2026, 8, 5, 8, 14))


class TestSellableSegIdx:
    """**팔 수 있는 첫 구간** — 조회·판정의 시작점 (→ D-47, 이슈 #35).

    `estimate_seg`(위치)와 갈라지는 지점이 이 클래스의 전부다.
    """

    def test_정차_중에는_그_구간을_그대로_본다(self):
        # 수원 도착 08:26, 출발 08:29. 정차 중에는 아직 수원→안양을 팔 수 있다
        assert sellable_seg_idx(stop_infos(), 0, at(8, 27)) == 2
        assert estimate_seg(stop_infos(), 0, at(8, 27)) == 2

    def test_출발했으면_다음_구간으로_넘어간다(self):
        # 08:30 = 수원 출발(08:29) 후. 열차는 수원-안양을 달리는 중이고
        # 그 구간은 이미 팔 수 없다 → 판정은 안양→영등포부터
        assert estimate_seg(stop_infos(), 0, at(8, 30)) == 2  # 위치는 그대로
        assert sellable_seg_idx(stop_infos(), 0, at(8, 30)) == 3

    def test_출발시각_정각은_아직_출발하지_않은_것으로_보지_않는다(self):
        """경계는 `<=`다. 출발 시각에 이미 판매가 닫힌다고 보는 편이 안전하다."""
        assert sellable_seg_idx(stop_infos(), 0, at(8, 29)) == 3

    def test_운행_전에는_첫_구간(self):
        assert sellable_seg_idx(stop_infos(), 0, at(7, 30)) == 0

    def test_지연되면_판매_마감도_함께_밀린다(self):
        # 10분 지연이면 실효 출발은 08:39 — 08:30에는 아직 수원에 서 있다
        assert sellable_seg_idx(stop_infos(), 10, at(8, 30)) == 2
        assert sellable_seg_idx(stop_infos(), 0, at(8, 30)) == 3

    def test_종착_이후에도_마지막_구간을_넘지_않는다(self):
        assert sellable_seg_idx(stop_infos(), 0, at(9, 30)) == len(STOPS) - 2

    def test_출발시각이_없으면_도착시각으로_떨어진다(self):
        """캐시가 부실할 때의 방어. 늦게 판단하면 원래 버그로 돌아간다."""
        stops = [StopInfo(name=s.name, arrival=s.arrival) for s in stop_infos()]
        assert sellable_seg_idx(stops, 0, at(8, 27)) == 3  # 수원 도착 08:26 → 이미 넘어감

    def test_GPS_보정값도_같은_규칙을_거친다(self):
        """GPS는 주행 중 구간을 정확히 짚는다 — 그대로 조회에 쓰면 버그를 더 확실히 밟는다."""
        # 시각표상 08:30은 수원 출발 후지만, GPS가 아직 평택-수원이라고 말한다
        assert sellable_seg_idx(stop_infos(), 0, at(8, 30), position_idx=1) == 2

    def test_naive_datetime은_거부한다(self):
        with pytest.raises(ValueError):
            sellable_seg_idx(stop_infos(), 0, datetime(2026, 8, 5, 8, 30))


class TestPollPoints:
    def test_이용_구간_정차역마다_offset만큼_앞선_포인트(self):
        points = compute_poll_points(stop_infos(), board_idx=0, alight_idx=5)
        # 천안~영등포 5개 역 × (도착 2 + 출발 1) = 15개인데, 천안 출발-1분(08:02)이
        # 평택 도착-10분과, 수원 출발-1분(08:28)이 안양 도착-10분과 겹쳐 13개 (D-57 dedup)
        assert len(points) == 13
        assert points[0] == at(7, 50)  # 천안 08:00 - 10분 → 탑승 전 다이제스트 (D-18)
        assert points[1] == at(7, 56)
        assert max(points) == at(8, 50)  # 영등포 출발 08:51 - 1분 (D-57)
        assert points == sorted(points)

    def test_출발_1분_전_포인트가_추가된다(self):
        points = compute_poll_points(stop_infos(), board_idx=0, alight_idx=5)
        assert at(8, 14) in points  # 평택 출발 08:15 - 1분 — 도착 기준으로는 안 나오는 시각
        assert at(8, 40) in points  # 안양 출발 08:41 - 1분

    def test_부분_구간_구독(self):
        points = compute_poll_points(stop_infos(), board_idx=2, alight_idx=4)
        # 수원 08:16/08:22(도착)·08:28(출발-1) + 안양 08:28/08:34(도착)·08:40(출발-1)
        assert points == [at(8, 16), at(8, 22), at(8, 28), at(8, 34), at(8, 40)]

    def test_출발_offset은_설정값이다(self):
        config = TimelineConfig(depart_poll_offsets_min=())
        points = compute_poll_points(stop_infos(), 2, 4, config=config)
        assert points == [at(8, 16), at(8, 22), at(8, 28), at(8, 34)]  # D-57 이전과 동일

    def test_출발시각이_없으면_도착시각으로_폴백(self):
        stops = stop_infos()
        bare = stops[2].model_copy(update={"departure": None})  # 수원 출발 결측 → 도착 08:26 폴백
        patched = stops[:2] + [bare] + stops[3:]
        points = compute_poll_points(patched, board_idx=2, alight_idx=4)
        assert at(8, 25) in points  # 수원 '출발'(폴백 = 도착 08:26) - 1분
        assert at(8, 28) in points  # 안양 도착 -10분은 그대로

    def test_지연이_폴_포인트를_뒤로_민다(self):
        points = compute_poll_points(stop_infos(), 0, 5, delay_min=7)
        assert points[0] == at(7, 57)

    def test_잘못된_구간은_거부(self):
        with pytest.raises(ValueError):
            compute_poll_points(stop_infos(), board_idx=3, alight_idx=3)

    def test_첫_포인터는_아직_유효한_가장_이른_포인트(self):
        points = compute_poll_points(stop_infos(), 0, 5)
        # 08:00 시점: 07:50/07:56은 grace(2분)도 지났다 → 08:02(평택 -10분)
        assert first_poll_at(points, at(8, 0)) == at(8, 2)

    def test_모든_포인트가_지났으면_None(self):
        points = compute_poll_points(stop_infos(), 0, 5)
        assert first_poll_at(points, at(9, 0)) is None

    def test_다음_조회_안내(self):
        # 08:14 = 평택 출발(08:15) 1분 전 — 출발 기준 포인트가 먼저 온다 (D-57)
        hint = next_poll_hint(stop_infos(), 0, 5, 0, at(8, 14))
        assert (hint.station, hint.offset_min, hint.basis) == ("평택", 1, "departure")

    def test_다음_조회_안내_도착_기준(self):
        hint = next_poll_hint(stop_infos(), 0, 5, 0, at(8, 15))
        assert (hint.station, hint.offset_min, hint.basis) == ("수원", 10, "arrival")


class TestResolvePoll:
    @pytest.fixture
    def points(self):
        return compute_poll_points(stop_infos(), 0, 5)

    def test_아직_시간이_안_됐으면_대기(self, points):
        d = resolve_poll(next_poll_at=at(8, 16), poll_points=points, now=at(8, 10))
        assert d.fire is False
        assert d.next_poll_at == at(8, 16)

    def test_정각에_실행하고_포인터_전진(self, points):
        d = resolve_poll(next_poll_at=at(8, 16), poll_points=points, now=at(8, 16))
        assert d.fire is True
        assert d.next_poll_at == at(8, 22)  # 수원 08:26 - 4분

    def test_grace_2분_이내_지각은_실행한다(self, points):
        d = resolve_poll(next_poll_at=at(8, 16), poll_points=points, now=at(8, 17, 59))
        assert d.fire is True
        assert d.next_poll_at == at(8, 22)

    def test_grace_초과는_스킵하고_전진한다(self, points):
        # 재시작 등으로 08:16 포인트를 3분 놓쳤다 → 낡은 시점 조회는 버린다
        d = resolve_poll(next_poll_at=at(8, 16), poll_points=points, now=at(8, 19))
        assert d.fire is False
        assert d.skipped == [at(8, 16)]
        assert d.next_poll_at == at(8, 22)

    def test_재시작_후_여러_포인트를_한꺼번에_건너뛴다(self, points):
        # 컨테이너가 08:00~08:30 동안 죽어 있었다: DB 포인터는 08:02에 멈춰 있다 (D-19)
        d = resolve_poll(next_poll_at=at(8, 2), poll_points=points, now=at(8, 29))
        assert d.fire is True  # 08:28(안양 -10분 = 수원 출발 -1분)은 grace 이내라 살아난다
        assert d.skipped == [at(8, 2), at(8, 8), at(8, 14), at(8, 16), at(8, 22)]
        assert d.next_poll_at == at(8, 34)

    def test_남은_포인트가_없으면_포인터를_비운다(self, points):
        d = resolve_poll(next_poll_at=at(8, 38), poll_points=points, now=at(9, 0))
        assert d.fire is False
        assert d.next_poll_at is None

    def test_포인터가_없으면_아무것도_하지_않는다(self, points):
        d = resolve_poll(next_poll_at=None, poll_points=points, now=at(8, 30))
        assert d.fire is False and d.next_poll_at is None

    def test_grace는_설정값이다(self, points):
        config = TimelineConfig(grace_min=5)
        d = resolve_poll(
            next_poll_at=at(8, 16), poll_points=points, now=at(8, 20), config=config
        )
        assert d.fire is True


def test_하차역_도착_경과시_구독_만료():
    stops = stop_infos()
    assert is_ride_over(stops, 5, 0, at(8, 55)) is False
    assert is_ride_over(stops, 5, 0, at(8, 56)) is True
    # 지연되면 만료도 늦춰진다
    assert is_ride_over(stops, 5, 10, at(8, 56)) is False
    assert is_ride_over(stops, 5, 10, at(9, 6)) is True
