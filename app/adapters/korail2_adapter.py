"""Korail2Adapter — `KorailPort` 실구현 (Phase 2 항목 B, D-22).

`korail_client`(동기)를 `asyncio.to_thread`로 감싼다. Port 인터페이스는 async를
유지하고, 동기 라이브러리를 격리하는 것은 **어댑터 내부의 책임**이다
(CLAUDE.md 절대규칙 3).

## 호차 범위 (D-27)

좌석맵은 **호차 단위 API**다. 인접 구간 하나를 채우려면 호차마다 한 번씩 불러야 한다.
전 일반실을 조회하면 구간 5개 × 6량 = 30회가 되어 호출 예절 상한을 크게 넘는다.

그래서 `TrainResearch`(호차별 잔여석)로 **먼저 걸러낸다** — 잔여 0인 호차는 좌석맵을
받아봐야 전부 판매됨이므로 조회하지 않는다. 추천 품질에는 손실이 없다 (어차피
추천 대상이 아니다). 매진에 가까운 시간대일수록 절감이 커지는데, 이는 곧
**호출이 가장 아까운 때에 가장 많이 아낀다**는 뜻이다.

빠진 호차의 좌석은 매트릭스에 아예 등장하지 않는다. `domain/verdict.py`의
**내 좌석 부재 규칙**(D-18)이 이 경우를 이미 처리한다 — 내 좌석이 매트릭스에 없으면
잔여 전 구간 판매로 간주한다. 잔여 0인 호차에 앉아 있었다면 그 판정이 정확히 맞다.
"""

from __future__ import annotations

import asyncio
from datetime import date as _date
from datetime import datetime

from app.adapters.korail_client import (
    KorailClient,
    general_cars,
    get_client,
    parse_delay_minutes,
    parse_train_summary,
    same_train_no,
)
from app.domain.models import (
    KST,
    KorailCred,
    SeatMap,
    SeatState,
    StationInfo,
    StopInfo,
    TrainSummary,
)


class CredentialsRequired(RuntimeError):
    """코레일 계정이 연결되지 않았다. `PUT /api/me/korail`로 먼저 등록해야 한다."""


class StopsSourceUnavailable(RuntimeError):
    """정차역 소스가 아직 확정되지 않았다 (Phase 2 항목 A).

    Phase 0 항목 5 = NO — 열차번호로 **전체 정차역**을 주는 코레일 엔드포인트가 없다.
    `ScheduleView`는 조회한 dep→arr 한 쌍과 운행 순번만 준다.
    외부 소스(공공데이터포털 열차운행정보)를 붙이기 전까지 이 경로는 열리지 않는다.
    """


def _require(cred: KorailCred | None) -> KorailClient:
    if cred is None:
        raise CredentialsRequired(
            "코레일 계정이 연결되지 않았습니다. 설정에서 계정을 먼저 등록하세요."
        )
    return get_client(cred)


class TrainObservations:
    """`ScheduleView`를 부를 때 지나가는 부수 정보를 모아둔다 (열차명·지연).

    둘 다 **전용 엔드포인트가 없고** `ScheduleView` 응답에 실려 올 뿐이다. 이 값을
    위해 따로 조회하면 같은 정보에 호출을 한 번 더 쓰게 된다 (CLAUDE.md 10).
    그래서 좌석맵 조회가 이미 부르는 `ScheduleView`에서 **주워 담기만** 한다.

    한계: 첫 화면 로드에는 아직 관측이 없어 지연이 None(=0)이다. 이는 Phase 1의
    `ZeroDelayAdapter` 동작과 같으므로 **퇴행이 아니고**, 이후 조회·폴링에서 실제
    값으로 자동 보정된다. PLAN D-12도 "2회 조회가 보완한다"는 전제를 깔고 있다.
    """

    def __init__(self) -> None:
        self._names: dict[tuple[str, str], str] = {}
        self._delays: dict[tuple[str, str], int] = {}

    @staticmethod
    def _key(train_no: str, d: _date) -> tuple[str, str]:
        return (str(train_no).lstrip("0"), d.isoformat())

    def observe(self, raw: dict, d: _date) -> None:
        key = self._key(str(raw.get("h_trn_no") or ""), d)
        if name := str(raw.get("h_trn_clsf_nm") or "").strip():
            self._names[key] = name
        minutes = parse_delay_minutes(raw.get("h_expct_dlay_hr"))
        if minutes is not None:
            self._delays[key] = minutes

    def name(self, train_no: str, d: _date) -> str | None:
        return self._names.get(self._key(train_no, d))

    def delay(self, train_no: str, d: _date) -> int | None:
        return self._delays.get(self._key(train_no, d))

    def clear(self) -> None:
        self._names.clear()
        self._delays.clear()


class Korail2Adapter:
    """`KorailPort` 구현 (실연동). `ADAPTER=korail2`일 때 쓰인다."""

    def __init__(self, observations: TrainObservations | None = None) -> None:
        self.observations = observations or TrainObservations()

    # ── 열차 검색 ────────────────────────────────────────────────────
    async def search_trains(
        self,
        cred: KorailCred | None,
        d: _date,
        frm: str,
        to: str,
        at: datetime | None = None,
    ) -> list[TrainSummary]:
        client = _require(cred)
        raws = await asyncio.to_thread(client.schedule_view, d, frm, to, at)
        for raw in raws:
            self.observations.observe(raw, d)
        summaries = [s for s in (parse_train_summary(r, d) for r in raws) if s is not None]
        return sorted(summaries, key=lambda t: t.dep_time)

    async def get_train_name(self, train_no: str, d: _date) -> str | None:
        """화면 배지 전용이라 없으면 None을 허용한다 (Port 계약).

        열차명만을 위해 실 API를 부르지 않는다 — 이미 부른 `ScheduleView`에서
        주워 담아 둔 값을 읽는다 (호출 예절, CLAUDE.md 10).
        """
        return self.observations.name(train_no, d)

    # ── 정차역 — 항목 A 확정 전까지 열리지 않는다 ─────────────────────
    async def get_stops(self, cred: KorailCred | None, train_no: str, d: _date) -> list[StopInfo]:
        raise StopsSourceUnavailable(
            "정차역 소스가 미확정이다 (Phase 2 항목 A). "
            "열차번호로 전체 정차역을 주는 코레일 엔드포인트는 없다 (Phase 0 항목 5 = NO). "
            "공공데이터포털 열차운행정보 연동 후 열린다."
        )

    async def list_stations(self) -> list[StationInfo]:
        raise StopsSourceUnavailable(
            "역 목록 소스가 미확정이다 (Phase 2 항목 A/G). station 테이블 적재 후 열린다."
        )

    # ── ★ 좌석맵 ─────────────────────────────────────────────────────
    async def get_seat_map(
        self, cred: KorailCred | None, train_no: str, d: _date, frm: str, to: str
    ) -> SeatMap:
        client = _require(cred)
        seats = await asyncio.to_thread(
            self._seat_map_sync, client, train_no, d, frm, to, self.observations
        )
        return SeatMap(
            train_no=train_no,
            date=d,
            frm=frm,
            to=to,
            seats=seats,
            fetched_at=datetime.now(KST),
        )

    @staticmethod
    def _seat_map_sync(
        client: KorailClient,
        train_no: str,
        d: _date,
        frm: str,
        to: str,
        observations: TrainObservations,
    ) -> list[SeatState]:
        """동기 구간. 스레드에서 돈다.

        호출 수 = 1(ScheduleView) + 1(TrainResearch) + **잔여석 있는 일반실 호차 수**.
        """
        train = client.find_train(d, frm, to, train_no)
        if train is not None:
            observations.observe(train, d)  # 열차명·지연을 공짜로 줍는다
        if train is None:
            # ValueError는 재시도 대상이 아니다 — 다시 불러도 같은 답이다
            # (seatmap_fetcher._with_retry 참고).
            raise ValueError(f"{frm}→{to} 구간에 열차 {train_no}가 없다")

        seats: list[SeatState] = []
        for car in general_cars(client.car_list(train)):
            if _rest_seats(car) <= 0:
                continue  # 잔여 0 → 좌석맵을 받아봐야 전부 판매됨이다 (D-27)
            car_no = _car_no(car)
            if car_no is None:
                continue
            seats.extend(client.seat_states(train, car_no))
        return seats


def _rest_seats(car: dict) -> int:
    """`h_rest_seat_cnt` → int. 읽을 수 없으면 **조회 대상으로 남긴다**.

    모르는 값을 0으로 보고 건너뛰면 좌석이 조용히 사라진다. 안전한 방향은
    "모르면 조회한다"이다 — 호출 한 번을 더 쓰는 대신 데이터가 비지 않는다.
    """
    raw = str(car.get("h_rest_seat_cnt") or "").strip()
    return int(raw) if raw.isdigit() else 1


def _car_no(car: dict) -> int | None:
    raw = str(car.get("h_srcar_no") or "").strip()
    return int(raw) if raw.isdigit() else None


class Korail2DelayAdapter:
    """`DelayPort` 실구현 (D-12, 항목 F).

    지연은 `ScheduleView` 응답의 `h_expct_dlay_hr`에 실려 온다 — **지연만을 위한
    엔드포인트는 없다.** 따라서 구간을 알아야 조회되는데 `DelayPort`의 시그니처
    `(train_no, date)`에는 구간이 없다. 전용 조회를 넣으면 호출이 늘고, 시그니처를
    바꾸면 Port 계약이 흔들린다.

    타협: 좌석맵 조회가 이미 부르는 `ScheduleView`에서 관측해 둔 값을 **읽기만** 한다.
    값이 없으면 None(=지연 0)이고, 그래도 시스템은 그대로 동작한다 (우아한 성능 저하).
    """

    def __init__(self, observations: TrainObservations) -> None:
        self._observations = observations

    async def get_delay_minutes(self, train_no: str, d: _date) -> int | None:
        return self._observations.delay(train_no, d)


_observations = TrainObservations()
_adapter = Korail2Adapter(_observations)
_delay_adapter = Korail2DelayAdapter(_observations)


def get_korail2_adapter() -> Korail2Adapter:
    return _adapter


def get_korail2_delay_adapter() -> Korail2DelayAdapter:
    return _delay_adapter


__all__ = [
    "CredentialsRequired",
    "Korail2Adapter",
    "Korail2DelayAdapter",
    "StopsSourceUnavailable",
    "get_korail2_adapter",
    "get_korail2_delay_adapter",
    "same_train_no",
]
