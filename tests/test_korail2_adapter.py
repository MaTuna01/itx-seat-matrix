"""Korail2Adapter 스모크 (PLAN 13절 — 어댑터는 스모크로 충분).

네트워크는 타지 않는다. `KorailClient`를 가짜로 갈아끼워 **호출 수와 분기**를 본다.
검증 대상은 D-27에서 정한 호차 정책이다:

    호출 수 = 1(ScheduleView) + 1(TrainResearch) + 잔여석 있는 일반실 호차 수

'실제 코레일이 이 페이로드를 받아주는지'는 여기서 확인할 수 없다 — 실호출의 몫이다.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime

import pytest

from app.adapters.korail2_adapter import (
    CredentialsRequired,
    Korail2Adapter,
    Korail2DelayAdapter,
    TrainStopsNotCached,
    TrainObservations,
)
from app.adapters.korail_client import KorailSoldOut
from app.domain.models import KST, KorailCred, SeatState

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


async def test_구간에_열차가_없으면_빈_좌석맵이다_에러가_아니다(adapter_with) -> None:
    """★ D-36. 매진 구간은 ScheduleView가 결과를 주지 않는다.

    그걸 "열차가 없다"로 읽고 예외를 던지면 **앞 구간에서 이미 받아온 좌석표까지
    통째로 버린다** — 중간까지만이라도 앉을 수 있다는 가장 쓸모 있는 정보가 사라진다.
    빈 좌석맵은 `merge_seat_maps`가 전 좌석 판매로 채운다 (D-18).
    """
    client = FakeClient([car(1)], train=None)
    result = await adapter_with(client).get_seat_map(CRED, "9999", RIDE_DATE, "천안", "수원")

    assert result.seats == []
    # 열차를 못 찾았으면 호차·좌석 조회로 넘어가지 않는다 (호출 예절)
    assert client.car_list_calls == 0
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


# ── 정차역 캐시 (D-29) ───────────────────────────────────────────────────
async def test_get_stops_raises_when_not_cached() -> None:
    """캐시에 없는 열차번호는 명확히 실패한다 — 조용히 빈 값을 주면 안 된다."""
    from app.storage.db import init_db

    init_db()  # 격리된 테스트 DB_PATH에 스키마를 만든다 (autouse 픽스처가 경로만 바꾼다)
    with pytest.raises(TrainStopsNotCached):
        await Korail2Adapter().get_stops(CRED, "1472", RIDE_DATE)


async def test_get_stops_reads_from_cache(tmp_path, monkeypatch) -> None:
    from app.storage import train_stops as stop_repo
    from app.storage.db import connect, init_db

    db_path = tmp_path / "stops.db"
    init_db(db_path)
    conn = connect(db_path)
    stop_repo.save_stops(
        conn,
        "1472",
        [
            stop_repo.StopRow(
                seq=1,
                station_name="천안",
                station_code="3900061",
                stop_type="시발",
                arrival=None,
                departure=datetime(2026, 8, 4, 7, 39, tzinfo=KST),
                run_ymd=_date(2026, 8, 4),
            ),
            stop_repo.StopRow(
                seq=2,
                station_name="수원",
                station_code="3900047",
                stop_type="여객승하차",
                arrival=datetime(2026, 8, 4, 8, 16, tzinfo=KST),
                departure=datetime(2026, 8, 4, 8, 19, tzinfo=KST),
                run_ymd=_date(2026, 8, 4),
            ),
        ],
        now=datetime(2026, 8, 4, 12, 0, tzinfo=KST),
    )
    conn.close()

    import app.storage.db as db_mod

    monkeypatch.setattr(db_mod, "db_path", lambda: db_path)

    stops = await Korail2Adapter().get_stops(CRED, "1472", RIDE_DATE)
    assert [s.name for s in stops] == ["천안", "수원"]
    assert stops[0].arrival.date() == RIDE_DATE  # 요청 날짜로 재적용됐다


async def test_list_stations_returns_usable_from_table(tmp_path, monkeypatch) -> None:
    from app.storage.stations import Station, upsert
    from app.storage.db import connect, init_db
    import app.storage.db as db_mod

    db_path = tmp_path / "stations2.db"
    init_db(db_path)
    conn = connect(db_path)
    upsert(conn, Station(name="수원", code="3900047", usable=True), source="t", now=datetime.now(KST))
    conn.close()
    monkeypatch.setattr(db_mod, "db_path", lambda: db_path)

    result = await Korail2Adapter().list_stations()
    assert [s.name for s in result] == ["수원"]


async def test_missing_credentials_raise_clear_error() -> None:
    with pytest.raises(CredentialsRequired):
        await Korail2Adapter().get_seat_map(None, "1472", RIDE_DATE, "천안", "수원")

    with pytest.raises(CredentialsRequired):
        await Korail2Adapter().search_trains(None, RIDE_DATE, "천안", "수원")


# ── 매진을 데이터로 흡수한다 (D-36) ──────────────────────────────────
class SoldOutCarListClient(FakeClient):
    """호차 조회 단계에서 매진을 알리는 코레일."""

    def car_list(self, train):  # noqa: ANN001, ANN201
        self.car_list_calls += 1
        raise KorailSoldOut("WRXXX", "잔여석이 없습니다")


class SoldOutOneCarClient(FakeClient):
    """호차 목록을 받은 사이 특정 호차만 팔린 경우."""

    def __init__(self, cars, sold_out_car: int) -> None:
        super().__init__(cars)
        self._sold_out_car = sold_out_car

    def seat_states(self, train, car_no):  # noqa: ANN001, ANN201
        self.seat_calls.append(car_no)
        if car_no == self._sold_out_car:
            raise KorailSoldOut("WRXXX", "잔여석이 없습니다")
        return [SeatState(car=car_no, seat_no="1A", sold=False)]


async def test_호차_조회가_매진이면_빈_좌석맵이다(adapter_with) -> None:
    client = SoldOutCarListClient([car(1), car(2)])
    result = await adapter_with(client).get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")

    assert result.seats == []
    assert client.seat_calls == []


async def test_한_호차만_매진이면_나머지_호차는_살린다(adapter_with) -> None:
    """여기서 예외를 올리면 **다른 호차의 빈자리까지 함께 사라진다.**"""
    client = SoldOutOneCarClient([car(1), car(2), car(3)], sold_out_car=2)
    result = await adapter_with(client).get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")

    assert client.seat_calls == [1, 2, 3]  # 매진 호차에서 멈추지 않는다
    assert sorted(s.car for s in result.seats) == [1, 3]


async def test_매진이어도_열차명_지연은_주워_담는다(adapter_with) -> None:
    """관측은 find_train 직후다 — 매진이라고 열차명·지연까지 잃을 이유가 없다."""
    adapter = adapter_with(SoldOutCarListClient([car(1)]))
    await adapter.get_seat_map(CRED, "1472", RIDE_DATE, "천안", "수원")

    assert adapter.observations.name("1472", RIDE_DATE) == "무궁화호"
    assert adapter.observations.delay("1472", RIDE_DATE) == 15
