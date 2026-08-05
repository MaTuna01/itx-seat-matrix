"""Korail2Adapter 스모크 (PLAN 13절 — 어댑터는 스모크로 충분).

네트워크는 타지 않는다. `KorailClient`를 가짜로 갈아끼워 **호출 수와 분기**를 본다.
검증 대상은 D-27에서 정한 호차 정책이다:

    호출 수 = 1(ScheduleView) + 1(TrainResearch) + 잔여석 있는 일반실 호차 수

'실제 코레일이 이 페이로드를 받아주는지'는 여기서 확인할 수 없다 — 실호출의 몫이다.
"""

from __future__ import annotations

from datetime import date as _date

import pytest

from app.adapters.korail2_adapter import (
    CredentialsRequired,
    Korail2Adapter,
    Korail2DelayAdapter,
    StopsSourceUnavailable,
    TrainObservations,
)
from app.domain.models import KorailCred, SeatState

RIDE_DATE = _date(2026, 8, 6)
CRED = KorailCred(korail_id="id", korail_pw="pw")

RAW_TRAIN = {
    "h_trn_no": "01472",
    "h_trn_clsf_nm": "무궁화호",
    "h_expct_dlay_hr": "001500",  # 15분 지연
    "h_dpt_rs_stn_nm": "천안",
    "h_arv_rs_stn_nm": "수원",
    "h_dpt_dt": "20260806",
    "h_dpt_tm": "180500",
    "h_arv_dt": "20260806",
    "h_arv_tm": "183100",
}


class FakeClient:
    """호출을 기록하는 가짜 KorailClient."""

    def __init__(self, cars: list[dict], train: dict | None = RAW_TRAIN) -> None:
        self._cars = cars
        self._train = train
        self.schedule_calls = 0
        self.car_list_calls = 0
        self.seat_calls: list[int] = []

    def find_train(self, d, frm, to, train_no):  # noqa: ANN001, ANN201
        self.schedule_calls += 1
        return self._train

    def car_list(self, train):  # noqa: ANN001, ANN201
        self.car_list_calls += 1
        return self._cars

    def seat_states(self, train, car_no):  # noqa: ANN001, ANN201
        self.seat_calls.append(car_no)
        return [SeatState(car=car_no, seat_no="1A", sold=False)]


def car(no: int, *, rest: int | str = 5, cls: str = "1") -> dict:
    return {"h_srcar_no": str(no), "h_rest_seat_cnt": str(rest), "h_psrm_cl_cd": cls}


@pytest.fixture
def adapter_with(monkeypatch):
    def _make(client: FakeClient) -> Korail2Adapter:
        import app.adapters.korail2_adapter as mod

        monkeypatch.setattr(mod, "get_client", lambda cred: client)
        return Korail2Adapter(TrainObservations())

    return _make


# ── D-27 호차 정책 ───────────────────────────────────────────────────────
async def test_skips_cars_without_remaining_seats(adapter_with) -> None:
    """잔여 0인 호차는 좌석맵을 부르지 않는다 — 받아봐야 전부 판매됨이다."""
    client = FakeClient([car(1, rest=5), car(2, rest=0), car(3, rest=2)])
    result = await adapter_with(client).get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")

    assert client.seat_calls == [1, 3]
    assert {s.car for s in result.seats} == {1, 3}


async def test_excludes_special_class_cars(adapter_with) -> None:
    client = FakeClient([car(1, cls="1"), car(2, cls="2"), car(3, cls="1")])
    await adapter_with(client).get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")
    assert client.seat_calls == [1, 3]


async def test_unreadable_remaining_count_is_still_fetched(adapter_with) -> None:
    """모르는 값을 0으로 보고 건너뛰면 좌석이 조용히 사라진다 — 모르면 조회한다."""
    client = FakeClient([car(1, rest="")])
    await adapter_with(client).get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")
    assert client.seat_calls == [1]


async def test_call_count_matches_policy(adapter_with) -> None:
    """1(ScheduleView) + 1(TrainResearch) + 잔여 있는 호차 수."""
    client = FakeClient([car(1), car(2, rest=0), car(3), car(4, cls="2")])
    await adapter_with(client).get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")
    assert (client.schedule_calls, client.car_list_calls, len(client.seat_calls)) == (1, 1, 2)


async def test_missing_train_raises_value_error(adapter_with) -> None:
    """ValueError는 재시도 대상이 아니다 — 다시 불러도 같은 답이다."""
    client = FakeClient([car(1)], train=None)
    with pytest.raises(ValueError):
        await adapter_with(client).get_seat_map(CRED, "9999", RIDE_DATE, "천안", "수원")
    assert client.seat_calls == []


async def test_seat_map_metadata(adapter_with) -> None:
    client = FakeClient([car(1)])
    result = await adapter_with(client).get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")
    assert (result.train_no, result.frm, result.to) == ("1472", "천안", "수원")
    assert result.date == RIDE_DATE
    assert result.fetched_at.tzinfo is not None  # KST aware (절대규칙 1)


# ── 관측 캐시: 열차명·지연을 공짜로 줍는가 ───────────────────────────────
async def test_seat_map_observes_name_and_delay(adapter_with) -> None:
    """지연·열차명 전용 호출은 하지 않는다 — ScheduleView에서 주워 담는다."""
    client = FakeClient([car(1)])
    adapter = adapter_with(client)

    assert await adapter.get_train_name("1472", RIDE_DATE) is None  # 관측 전
    await adapter.get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")

    assert await adapter.get_train_name("1472", RIDE_DATE) == "무궁화호"
    delay = Korail2DelayAdapter(adapter.observations)
    assert await delay.get_delay_minutes("1472", RIDE_DATE) == 15
    assert client.schedule_calls == 1  # 추가 호출 없음


async def test_delay_is_none_before_observation() -> None:
    """첫 로드에는 관측이 없다 — ZeroDelay와 같은 동작이라 퇴행이 아니다."""
    delay = Korail2DelayAdapter(TrainObservations())
    assert await delay.get_delay_minutes("1472", RIDE_DATE) is None


async def test_observation_matches_train_no_without_leading_zeros() -> None:
    obs = TrainObservations()
    obs.observe(RAW_TRAIN, RIDE_DATE)  # h_trn_no = '01472'
    assert obs.name("1472", RIDE_DATE) == "무궁화호"
    assert obs.delay("1472", RIDE_DATE) == 15


# ── 미확정 경로 ──────────────────────────────────────────────────────────
async def test_get_stops_is_blocked_pending_source() -> None:
    """항목 A 확정 전까지는 명확히 막아둔다 — 조용히 빈 값을 주면 안 된다."""
    with pytest.raises(StopsSourceUnavailable):
        await Korail2Adapter().get_stops(CRED, "1472", RIDE_DATE)


async def test_list_stations_is_blocked_pending_source() -> None:
    with pytest.raises(StopsSourceUnavailable):
        await Korail2Adapter().list_stations()


async def test_missing_credentials_raise_clear_error() -> None:
    with pytest.raises(CredentialsRequired):
        await Korail2Adapter().get_seat_map(None, "1472", RIDE_DATE, "천안", "수원")

    with pytest.raises(CredentialsRequired):
        await Korail2Adapter().search_trains(None, RIDE_DATE, "천안", "수원")
