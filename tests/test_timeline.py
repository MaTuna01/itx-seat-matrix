"""estimate_seg 경계 + 폴 포인터 전진 + grace 2분 (PLAN 13절, D-18/D-19)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.timeline import (
    TimelineConfig,
    compute_poll_points,
    estimate_seg,
    first_poll_at,
    is_ride_over,
    next_poll_hint,
    resolve_poll,
)
from tests.conftest import STOPS, at, stop_infos

# 시각표: 천안 08:00 / 평택 08:12 / 수원 08:26 / 안양 08:38 / 영등포 08:48 / 서울 08:56


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


class TestPollPoints:
    def test_이용_구간_정차역마다_offset만큼_앞선_포인트(self):
        points = compute_poll_points(stop_infos(), board_idx=0, alight_idx=5)
        # 천안~영등포 5개 역 × 2 offsets. 하차역(서울) 도착 전 조회는 취할 행동이 없어 제외
        assert len(points) == 10
        assert points[0] == at(7, 50)  # 천안 08:00 - 10분 → 탑승 전 다이제스트 (D-18)
        assert points[1] == at(7, 56)
        assert max(points) == at(8, 44)  # 영등포 08:48 - 4분
        assert points == sorted(points)

    def test_부분_구간_구독(self):
        points = compute_poll_points(stop_infos(), board_idx=2, alight_idx=4)
        assert points == [at(8, 16), at(8, 22), at(8, 28), at(8, 34)]

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
        hint = next_poll_hint(stop_infos(), 0, 5, 0, at(8, 14))
        assert (hint.station, hint.offset_min) == ("수원", 10)


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
        assert d.fire is True  # 08:28(안양 -10분)은 grace 이내라 살아난다
        assert d.skipped == [at(8, 2), at(8, 8), at(8, 16), at(8, 22)]
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
