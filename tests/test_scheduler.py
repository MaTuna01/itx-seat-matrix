"""스케줄러 배선 (PLAN.md 9절, 13절, D-17/D-19/D-20). Phase 3의 핵심 테스트.

**침묵해야 할 때 침묵하는지가 요점이다.** 판정 자체는 test_alerts.py가 잠갔고, 여기서는
그 결정이 조회·발송·DB에 제대로 배선됐는지를 본다:

1. 구간만 진행됐을 때(SEATED) 알림이 나가지 않는다
2. 하위 추천 순서만 바뀌었을 때 침묵한다
3. 첫 폴링은 항상 1건 발송한다 (베이스라인 = 생존 확인)
4. 폴링 시점당 푸시는 최대 1건이다 (우선순위 합성)
5. 스케줄러 재시작 후 포인터에서 이어진다 (멱등)

시간은 전부 `now` 주입이다. sleep/실제 시계를 쓰지 않는다 (CLAUDE.md 테스트 규칙).
실 코레일은 물론 실 발송도 타지 않는다 — 포트와 노티파이어 양쪽에 가짜를 꽂는다.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date as _date
from datetime import datetime, timedelta
from typing import Iterator

import pytest

from app.adapters.notifier_port import (
    CompositeNotifier,
    Notification,
    NotifyResult,
    NotifyTargets,
)
from app.adapters.seatmap_fetcher import RetryPolicy
from app.domain.models import KST, SeatMap, SeatState, StopInfo
from app.scheduler.poller import PollerDeps, run_tick
from app.storage.db import connect, init_db, to_db
from tests.conftest import ARRIVAL_OFFSETS, DEPARTURE_OFFSETS, RIDE_DATE, STOPS, at

TRAIN_NO = "1004"
MY_KEY = (3, "7A")
F, T = False, True

# 폴 포인트는 정차역 실효 도착시각 - [10, 4]분이다. 도착 오프셋이 [0,12,26,38,48,56]분,
# 기준 08:00이므로 수원(08:26) 앞 포인트는 08:16 / 08:22가 된다.
SUWON_POINT_10 = at(8, 16)
SUWON_POINT_4 = at(8, 22)


# ── 가짜 어댑터 ──────────────────────────────────────────────────────
class FakePort:
    """좌석표를 테스트가 직접 정하는 KorailPort. 호출 인자를 전부 기록한다."""

    def __init__(self, cells: dict[tuple[int, str], list[bool]]) -> None:
        self.cells = cells
        self.seat_map_calls: list[tuple[str, str]] = []
        self.stops_error: Exception | None = None
        self.seat_map_error: Exception | None = None
        # 코레일이 **빈 응답**을 주는 구간. 이미 출발한 구간이 여기 들어간다 (→ D-47).
        # 어댑터는 이것을 '전 좌석 판매됨'으로 흡수한다 (D-36).
        self.empty_segments: set[int] = set()
        # 조회가 **실패**하는 구간 (→ D-48). 빈 응답(= 매진)과 전혀 다른 상태다
        self.failing_segments: set[int] = set()

    async def get_stops(self, cred, train_no: str, d: _date) -> list[StopInfo]:
        if self.stops_error is not None:
            raise self.stops_error
        base = datetime(d.year, d.month, d.day, 8, 0, tzinfo=KST)
        return [
            StopInfo(
                name=name,
                arrival=base + timedelta(minutes=arr),
                departure=None if dep is None else base + timedelta(minutes=dep),
            )
            for name, arr, dep in zip(STOPS, ARRIVAL_OFFSETS, DEPARTURE_OFFSETS)
        ]

    async def get_seat_map(self, cred, train_no: str, d: _date, frm: str, to: str) -> SeatMap:
        self.seat_map_calls.append((frm, to))
        if self.seat_map_error is not None:
            raise self.seat_map_error
        seg_idx = STOPS.index(frm)
        if seg_idx in self.failing_segments:
            raise ConnectionError(f"구간 {seg_idx} 조회 실패")
        return SeatMap(
            train_no=train_no,
            date=d,
            frm=frm,
            to=to,
            seats=[]
            if seg_idx in self.empty_segments
            else [
                SeatState(car=car, seat_no=seat_no, sold=cells[seg_idx])
                for (car, seat_no), cells in self.cells.items()
            ],
            fetched_at=at(8, 0),
        )

    async def get_train_name(self, train_no: str, d: _date) -> str | None:
        return "ITX-마음"

    async def list_stations(self):  # pragma: no cover - 스케줄러 경로에서 쓰지 않는다
        return []

    async def search_trains(self, *args, **kwargs):  # pragma: no cover
        return []


class FakeDelay:
    def __init__(self, minutes: int | None = None) -> None:
        self.minutes = minutes

    async def get_delay_minutes(self, train_no: str, d: _date) -> int | None:
        return self.minutes


class SpyNotifier:
    """발송된 Notification을 기록만 한다. 밖으로 아무것도 내보내지 않는다."""

    def __init__(self, *, delivered: bool = True) -> None:
        self.notes: list[Notification] = []
        self.delivered = delivered

    async def send(self, note: Notification, targets: NotifyTargets) -> NotifyResult:
        self.notes.append(note)
        return NotifyResult(sent=1 if self.delivered else 0)

    @property
    def kinds(self) -> list[str]:
        return [n.payload["kind"] for n in self.notes]


# ── 픽스처 ──────────────────────────────────────────────────────────
@pytest.fixture
def db(tmp_path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "sched.db"
    init_db(path)
    conn = connect(path)
    conn.execute(
        "INSERT INTO user (email, password_hash, display_name, created_at)"
        " VALUES ('me@example.com', 'x', '나', ?)",
        (to_db(at(7, 0)),),
    )
    yield conn
    conn.close()


def make_sub(
    conn: sqlite3.Connection,
    *,
    status: str = "STANDING",
    my_car: int | None = None,
    my_seat_no: str | None = None,
    next_poll_at: datetime | None = SUWON_POINT_10,
    board_at: str = "천안",
    alight_at: str = "서울",
    date: _date = RIDE_DATE,
    last_verdict_hash: str | None = None,
    last_cells_snapshot: list[bool] | None = None,
    active: int = 1,
) -> int:
    cur = conn.execute(
        "INSERT INTO subscription (user_id, train_no, date, board_at, alight_at, status,"
        " my_car, my_seat_no, active, created_at, next_poll_at, last_verdict_hash,"
        " last_cells_snapshot)"
        " VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            TRAIN_NO,
            to_db(date),
            board_at,
            alight_at,
            status,
            my_car,
            my_seat_no,
            active,
            to_db(at(7, 30)),
            to_db(next_poll_at),
            last_verdict_hash,
            None if last_cells_snapshot is None else json.dumps(last_cells_snapshot),
        ),
    )
    return int(cur.lastrowid)


def deps_for(
    conn: sqlite3.Connection,
    port: FakePort,
    notifier: SpyNotifier,
    *,
    delay: int | None = None,
) -> PollerDeps:
    @contextmanager
    def factory() -> Iterator[sqlite3.Connection]:
        yield conn  # 테스트는 커넥션 하나를 계속 쓴다 (닫지 않는다)

    return PollerDeps(
        port=port,
        delay_port=FakeDelay(delay),
        notifier=CompositeNotifier((notifier,)),
        conn_factory=factory,
        # 재시도 대기를 0으로. sleep을 실제로 쓰지 않는다
        retry=RetryPolicy(attempts=3, delay_seconds=0.0),
        jitter=None,
    )


def row_of(conn: sqlite3.Connection, sub_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM subscription WHERE id = ?", (sub_id,)).fetchone()


# 프로토타입 목업과 같은 좌석표 (True = 판매됨). 구간 5개.
def cells(**overrides: list[bool]) -> dict[tuple[int, str], list[bool]]:
    base: dict[tuple[int, str], list[bool]] = {
        (3, "7A"): [F, F, F, F, F],  # 내 자리 — 하차역까지 안전
        (4, "1B"): [F, F, F, F, F],
        (4, "2B"): [T, T, F, F, F],
        (3, "9A"): [T, T, T, T, T],
    }
    for key, value in overrides.items():
        car, _, seat_no = key.partition("_")
        base[(int(car), seat_no)] = value
    return base


# ── ① 구간만 진행됐을 때(SEATED) 알림이 나가지 않는다 ─────────────────
async def test_구간만_진행되면_알림이_나가지_않는다(db):
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="SEATED", my_car=3, my_seat_no="7A")

    # 첫 폴링 — 베이스라인 1건 (생존 확인, D-20)
    await run_tick(deps, now=SUWON_POINT_10)
    assert len(spy.notes) == 1

    # 같은 좌석표로 다음 폴 포인트. 열차만 나아갔다 → 침묵해야 한다
    await run_tick(deps, now=SUWON_POINT_4)
    assert len(spy.notes) == 1, "구간 진행만으로 알림이 나갔다"

    # 안양(08:38) 앞 포인트까지 가도 여전히 침묵
    await run_tick(deps, now=at(8, 28))
    await run_tick(deps, now=at(8, 34))
    assert len(spy.notes) == 1
    assert row_of(db, sub_id)["last_verdict_hash"] is not None


# ── ② 하위 추천 순서만 바뀌었을 때 침묵한다 ──────────────────────────
async def test_하위_추천만_바뀌면_침묵한다(db):
    """최상위 추천(4-1B)은 그대로 두고 그 아래만 흔든다.

    해시 튜플에 `move_to` 전체가 들어가면 여기서 알림이 나간다 (D-16).
    """
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="STANDING")

    await run_tick(deps, now=SUWON_POINT_10)
    assert len(spy.notes) == 1  # 베이스라인

    # 하위 후보만 교체 — 4-1B(하차역까지 빈 자리)는 유지
    port.cells = cells(**{"4_2B": [T, T, T, F, F], "3_8B": [F, F, F, F, T]})
    await run_tick(deps, now=SUWON_POINT_4)
    assert len(spy.notes) == 1, "하위 추천 변동으로 알림이 나갔다"


# ── ③ 첫 폴링은 항상 1건 발송한다 (베이스라인) ───────────────────────
@pytest.mark.parametrize(
    "status,my_car,my_seat_no",
    [("STANDING", None, None), ("SEATED", 3, "7A")],
)
async def test_첫_폴링은_항상_1건_발송한다(db, status, my_car, my_seat_no):
    """상태와 무관하게 1건. 목적은 유용한 초기 상태 + **오늘 푸시가 살아있다는 확인**이다.

    매일 타는 열차에서 첫 알림이 안 오면 그날 푸시가 죽은 것이다 (D-9/D-20).
    """
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status=status, my_car=my_car, my_seat_no=my_seat_no, last_verdict_hash=None)

    await run_tick(deps, now=SUWON_POINT_10)
    assert len(spy.notes) == 1


async def test_해시가_있으면_베이스라인을_보내지_않는다(db):
    """`last_verdict_hash`가 이미 현재 상태와 같으면 침묵한다 (원칙 6)."""
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="SEATED", my_car=3, my_seat_no="7A")

    await run_tick(deps, now=SUWON_POINT_10)
    baseline = len(spy.notes)
    await run_tick(deps, now=SUWON_POINT_4)
    assert len(spy.notes) == baseline


# ── ④ 폴링 시점당 푸시는 최대 1건이다 (우선순위 합성) ────────────────
async def test_폴링_시점당_푸시는_최대_1건이다(db):
    """내 자리 판매 + 잔여 없음이 동시에 성립해도 1건이다.

    "이동하라"와 "이동할 곳 없다"가 각각 오면 모순 메시지 2건이 된다 (D-20).
    """
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="SEATED", my_car=3, my_seat_no="7A")

    await run_tick(deps, now=SUWON_POINT_10)
    spy.notes.clear()

    # 실효 시작 구간(평택→수원)부터 내 자리를 포함한 **모든** 좌석이 판매됨
    # → MY_SEAT_SOLD("옮겨라")와 ALL_SOLD("옮길 곳 없다")가 동시에 성립한다
    port.cells = {
        (3, "7A"): [F, T, T, T, T],
        (4, "1B"): [F, T, T, T, T],
        (4, "2B"): [T, T, T, T, T],
        (3, "9A"): [T, T, T, T, T],
    }
    await run_tick(deps, now=SUWON_POINT_4)

    assert len(spy.notes) == 1, f"푸시가 {len(spy.notes)}건 나갔다: {spy.kinds}"
    # 우선순위 ALL_SOLD > MY_SEAT_SOLD — 상위가 하위를 본문에 흡수한다
    assert spy.kinds == ["ALL_SOLD"]
    assert "3-7A" in spy.notes[0].body


# ── ⑤ 재시작 후 포인터에서 이어진다 (멱등) ──────────────────────────
async def test_재시작해도_포인터에서_이어진다(db):
    """포인터가 DB에 있으므로 프로세스가 죽었다 살아나도 같은 지점에서 계속된다 (D-19)."""
    port, spy = FakePort(cells()), SpyNotifier()
    sub_id = make_sub(db, status="STANDING")

    # 프로세스 1
    await run_tick(deps_for(db, port, spy), now=SUWON_POINT_10)
    pointer_after_first = row_of(db, sub_id)["next_poll_at"]
    assert pointer_after_first == to_db(SUWON_POINT_4)

    # 프로세스 재시작 — deps를 새로 만든다 (메모리 상태 없음)
    port2, spy2 = FakePort(cells()), SpyNotifier()
    await run_tick(deps_for(db, port2, spy2), now=SUWON_POINT_4)
    assert port2.seat_map_calls, "재시작 후 포인터를 잃어 조회하지 않았다"
    assert row_of(db, sub_id)["next_poll_at"] == to_db(at(8, 28))  # 안양 -10분


async def test_grace를_넘긴_포인트는_스킵하고_전진한다(db):
    """2분 넘게 지각한 폴 포인트는 실행하지 않는다 — 다음 조회와 겹치기만 한다 (D-19)."""
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING", next_poll_at=SUWON_POINT_10)

    # 08:16 포인트를 08:20에 만난다 (grace 2분 초과) → 스킵, 08:22로 전진
    await run_tick(deps, now=at(8, 20))
    assert port.seat_map_calls == []
    assert row_of(db, sub_id)["next_poll_at"] == to_db(SUWON_POINT_4)
    assert spy.notes == []


async def test_grace_이내_지각은_실행한다(db):
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="STANDING", next_poll_at=SUWON_POINT_10)

    await run_tick(deps, now=at(8, 17, 30))
    assert port.seat_map_calls != []


async def test_포인터가_안_왔으면_아무것도_하지_않는다(db):
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="STANDING", next_poll_at=SUWON_POINT_10)

    report = await run_tick(deps, now=at(8, 10))
    assert port.seat_map_calls == []
    assert not report


# ── 조회 범위·캐시 회피 (D-17/D-18) ─────────────────────────────────
async def test_스케줄러는_캐시를_쓰지_않고_매번_실조회한다(db, monkeypatch):
    """★ 회귀 방어. 캐시된 값으로 판정하면 상태 변화를 놓쳐 알림이 조용히 안 온다 (D-17).

    "두 번 조회되는가"로는 잡히지 않는다 — 폴 포인트 간격이 4~6분이라 60초 TTL이
    어차피 만료된다. 넘긴 인자를 직접 본다.
    """
    import app.scheduler.poller as poller_mod

    captured: list[dict] = []
    real = poller_mod.fetch_matrix

    async def spy_fetch(*args, **kwargs):
        captured.append(kwargs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(poller_mod, "fetch_matrix", spy_fetch)

    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="STANDING")

    await run_tick(deps, now=SUWON_POINT_10)
    assert captured, "조회가 일어나지 않았다"
    assert captured[0]["cache"] is None, "스케줄러가 화면용 캐시를 통해 판정했다"
    assert captured[0]["retry"].attempts == 3  # 30초×3이 상한 (CLAUDE.md 10)


async def test_조회_범위는_실효_시작부터_하차역까지다(db):
    """지나온 구간·탑승 전 구간은 호출하지 않는다 (호출 예절, D-18)."""
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="STANDING", board_at="평택", alight_at="영등포")

    # 08:16 = 평택 **출발**(08:15) 후. 열차는 평택-수원을 달리는 중이고 그 구간은
    # 이미 팔 수 없다 → 실효 시작은 구간 2(수원→안양)다 (→ D-47)
    await run_tick(deps, now=SUWON_POINT_10)
    assert sorted(port.seat_map_calls) == sorted([("수원", "안양"), ("안양", "영등포")])


# ── ★ 이미 출발한 구간은 조회하지 않는다 (이슈 #35 → D-47) ────────────
async def test_출발한_구간은_조회하지_않는다(db):
    """★ 회귀 방어. **출발한 구간은 코레일이 팔 수 없다** — 조회하면 빈 응답이 온다.

    2026-08-07 출근길 실측(EC2 로그). 천안 07:12 출발 직후부터 매 폴링마다:

        천안→평택 구간에 열차 4202 없음 → 전 좌석 판매로 간주

    빈 응답은 D-18의 부재 추론으로 '그 구간 전 좌석 판매됨'이 되고, 그 열이 실효 시작
    구간이라 **판정이 통째로 뒤집힌다** — 하차역까지 안전한 내 자리가 "천안부터 판매됨"이
    되어 MY_SEAT_SOLD가 나간다. 좌석이 팔린 게 아니라 열차가 출발했을 뿐인데도.

    폴 포인트는 항상 *다음 역 도착 10·4분 전* = **주행 중**이므로 출발 이후 모든 폴링이
    이 조건에 걸린다. 한 번의 사고가 아니라 구조적이다.
    """
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(
        db,
        status="SEATED",
        my_car=3,
        my_seat_no="7A",
        board_at="천안",
        alight_at="영등포",
        next_poll_at=at(8, 2),
    )

    # ① 08:02 — 천안 정차 중(도착 08:00 / 출발 08:03). 이 구간은 아직 팔 수 있다
    await run_tick(deps, now=at(8, 2))
    assert ("천안", "평택") in port.seat_map_calls
    assert len(spy.notes) == 1  # 베이스라인 (D-20)
    hash_before = row_of(db, sub_id)["last_verdict_hash"]

    # ② 08:03 출발. 코레일은 이 시점부터 천안→평택에 열차를 주지 않는다
    port.empty_segments = {0}
    port.seat_map_calls.clear()
    spy.notes.clear()

    # ③ 08:08 — 평택 도착 4분 전 폴링. 열차는 천안-평택을 달리는 중이다
    await run_tick(deps, now=at(8, 8))

    assert ("천안", "평택") not in port.seat_map_calls, (
        "이미 출발한 구간을 조회했다 — 코레일은 이 구간을 팔 수 없으므로 빈 응답이 온다"
    )
    assert spy.kinds == [], f"출발했다는 이유만으로 알림이 나갔다: {spy.kinds}"
    assert row_of(db, sub_id)["last_verdict_hash"] == hash_before, (
        "구간을 지나쳤을 뿐인데 판정 상태가 바뀌었다"
    )


# ── FETCH_FAILED 게이트 (D-17/D-34) ─────────────────────────────────
async def test_조회_실패는_1회만_알리고_포인터를_전진시킨다(db):
    port, spy = FakePort(cells()), SpyNotifier()
    port.seat_map_error = RuntimeError("코레일 응답 없음")
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING")

    await run_tick(deps, now=SUWON_POINT_10)
    assert spy.kinds == ["FETCH_FAILED"]
    assert row_of(db, sub_id)["fail_count"] == 1
    # 그 시점을 포기하고 다음 포인트로 전진한다 (D-17)
    assert row_of(db, sub_id)["next_poll_at"] == to_db(SUWON_POINT_4)

    # 계속 실패해도 재발송하지 않는다 (실패 알림 스팸 방지, 8절)
    await run_tick(deps, now=SUWON_POINT_4)
    assert spy.kinds == ["FETCH_FAILED"]
    assert row_of(db, sub_id)["fail_count"] == 2


async def test_복구되면_fail_count가_초기화된다(db):
    """리셋이 없으면 다음 장애 때 FETCH_FAILED가 영구히 침묵한다."""
    port, spy = FakePort(cells()), SpyNotifier()
    port.seat_map_error = RuntimeError("일시 장애")
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING")

    await run_tick(deps, now=SUWON_POINT_10)
    assert row_of(db, sub_id)["fail_count"] == 1

    port.seat_map_error = None
    await run_tick(deps, now=SUWON_POINT_4)
    assert row_of(db, sub_id)["fail_count"] == 0


async def test_재시도는_3회가_상한이다(db):
    """CLAUDE.md 10 — 조회는 정차역당 1~2회 + 실패 재시도(30초×3)가 상한이다."""
    port, spy = FakePort(cells()), SpyNotifier()
    port.seat_map_error = RuntimeError("장애")
    deps = deps_for(db, port, spy)
    make_sub(db, status="STANDING", board_at="영등포", alight_at="서울")  # 구간 1개

    await run_tick(deps, now=at(8, 38))  # 영등포(08:48) -10분
    assert len(port.seat_map_calls) == 3


# ── 구독 자동 만료 (PLAN 9절) ────────────────────────────────────────
async def test_하차역을_지나면_구독이_만료된다(db):
    """★ Phase 2에서 이게 없어 지난 날짜 구독이 계속 살아났다."""
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING", next_poll_at=None)

    report = await run_tick(deps, now=at(9, 0))  # 서울 도착 08:56 경과
    assert report.expired == [sub_id]
    row = row_of(db, sub_id)
    assert row["active"] == 0
    assert row["next_poll_at"] is None
    assert port.seat_map_calls == []


async def test_지연되면_만료도_함께_밀린다(db):
    """실효 도착시각 = 시각표 + 지연분 (D-12). 지연 중에 구독을 죽이면 알림이 끊긴다."""
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy, delay=15)
    sub_id = make_sub(db, status="STANDING", next_poll_at=None)

    report = await run_tick(deps, now=at(9, 0))  # 실효 도착은 09:11
    assert report.expired == []
    assert row_of(db, sub_id)["active"] == 1


async def test_정차역을_모르는_지난_날짜_구독은_만료된다(db):
    """안전망 (D-34). 정차역 캐시가 비면 만료 판정도 못 해 어제 구독이 영원히 남는다."""
    port, spy = FakePort(cells()), SpyNotifier()
    port.stops_error = RuntimeError("train_stop 캐시에 없다")
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, date=RIDE_DATE - timedelta(days=1), next_poll_at=None)

    report = await run_tick(deps, now=at(8, 16))
    assert report.expired == [sub_id]
    assert row_of(db, sub_id)["active"] == 0
    assert spy.notes == [], "지난 구독 만료로 알림을 보내면 안 된다"


async def test_정차역_조회가_복구되면_포인터에서_이어진다(db):
    """★ 회귀 방어. 실패 처리가 포인터를 비우면 복구돼도 그 구독은 영구히 조회되지 않는다.

    캐시 적재 전에 앱이 떠 있는 상황(D-29)이 실제로 이 경로를 탄다.
    """
    port, spy = FakePort(cells()), SpyNotifier()
    port.stops_error = RuntimeError("train_stop 캐시에 없다")
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING", next_poll_at=SUWON_POINT_10)

    await run_tick(deps, now=SUWON_POINT_10)
    assert spy.kinds == ["FETCH_FAILED"]
    assert row_of(db, sub_id)["next_poll_at"] == to_db(SUWON_POINT_10), "포인터를 잃었다"

    # 캐시가 채워졌다 → grace 이내면 그 포인트를 그대로 실행한다
    port.stops_error = None
    await run_tick(deps, now=SUWON_POINT_10 + timedelta(minutes=1))
    assert port.seat_map_calls, "복구 후에도 조회하지 않았다"
    assert row_of(db, sub_id)["fail_count"] == 0


async def test_비활성_구독은_건드리지_않는다(db):
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="STANDING", active=0)

    report = await run_tick(deps, now=SUWON_POINT_10)
    assert not report
    assert port.seat_map_calls == []


# ── SEAT_EXTENDED 셀 전이 (D-16) ────────────────────────────────────
async def test_내_좌석_스냅샷이_기록되고_전이가_감지된다(db):
    port, spy = FakePort(cells(**{"3_7A": [F, F, T, T, T]})), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="SEATED", my_car=3, my_seat_no="7A")

    await run_tick(deps, now=SUWON_POINT_10)
    snapshot = json.loads(row_of(db, sub_id)["last_cells_snapshot"])
    # 조회하지 않은 구간은 UNQUERIED_CELL(True)로 채워져 있다 (D-18/D-31) — 지나온 구간(0)
    # 뿐 아니라 **지금 달리는 중이라 팔 수 없는 구간(1)** 도 여기 들어간다 (→ D-47).
    # 전이 판정 범위가 [실효 시작, 하차역)이라 이 채움값은 비교에 들어오지 않는다 —
    # 실효 시작은 시간이 갈수록 커지므로 두 스냅샷 모두 그 구간에선 실관측값이다
    assert snapshot[2:] == [True, True, True]
    spy.notes.clear()

    # 누가 취소해 잔여 구간의 판매가 풀렸다 → true→false 전이
    port.cells = cells(**{"3_7A": [F, F, F, F, F]})
    await run_tick(deps, now=SUWON_POINT_4)
    assert spy.kinds == ["SEAT_EXTENDED"], f"셀 전이를 놓쳤다: {spy.kinds}"
    assert json.loads(row_of(db, sub_id)["last_cells_snapshot"])[2:] == [F, F, F]


async def test_열차_진행만으로는_연장_알림이_나가지_않는다(db):
    """`clear_until` 증가를 트리거로 쓰면 여기서 스퍼리어스 발송이 난다 (D-16).

    내 자리가 수원부터 판매된 상태 그대로 열차가 나아간다 — 셀은 하나도 바뀌지 않았다.
    """
    port, spy = FakePort(cells(**{"3_7A": [F, F, T, T, T]})), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="SEATED", my_car=3, my_seat_no="7A")

    await run_tick(deps, now=SUWON_POINT_10)  # 베이스라인
    spy.notes.clear()
    await run_tick(deps, now=SUWON_POINT_4)
    await run_tick(deps, now=at(8, 28))
    assert spy.notes == [], f"진행만으로 알림이 나갔다: {spy.kinds}"


# ── 발송 실패와 상태 기록 ────────────────────────────────────────────
async def test_발송_실패해도_상태는_기록된다(db):
    """상태는 "관측한 것", 발송은 "알린 것"이다. 섞으면 발송 실패가 상태 오염으로 번진다."""
    port, spy = FakePort(cells()), SpyNotifier(delivered=False)
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING")

    await run_tick(deps, now=SUWON_POINT_10)
    row = row_of(db, sub_id)
    assert row["last_verdict_hash"] is not None
    assert row["last_notified_at"] is None  # 아무 채널도 받아들이지 않았다


async def test_발송되면_last_notified_at이_기록된다(db):
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING")

    await run_tick(deps, now=SUWON_POINT_10)
    assert row_of(db, sub_id)["last_notified_at"] == to_db(SUWON_POINT_10)


async def test_한_구독의_예외가_나머지를_막지_않는다(db):
    """틱이 죽으면 그 뒤 구독이 전부 조회되지 않는다."""

    class BoomPort(FakePort):
        async def get_stops(self, cred, train_no: str, d: _date):
            if train_no == "boom":
                raise KeyboardInterrupt("치명적")  # noqa: TRY002 - Exception 밖의 예외
            return await super().get_stops(cred, train_no, d)

    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    make_sub(db, status="STANDING")
    make_sub(db, status="STANDING", board_at="평택")

    report = await run_tick(deps, now=SUWON_POINT_10)
    assert len(report.polled) == 2


# ── 딥링크 payload (D-20) ────────────────────────────────────────────
async def test_알림_payload에_매트릭스_딥링크가_있다(db):
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING")

    await run_tick(deps, now=SUWON_POINT_10)
    payload = spy.notes[0].payload
    assert payload["subscription_id"] == sub_id
    assert payload["url"] == f"/?sub={sub_id}"


# ── SECRET_KEY 불일치 시 침묵하지 않는다 (Phase 4 배포 대비) ─────────
async def test_자격증명_복호화_실패는_조용히_끊기지_않는다(db):
    """★ DB만 옮기고 SECRET_KEY를 새로 만든 배포에서 반드시 발생하는 경로.

    복호화가 예외로 올라오면 구독별 `except Exception`에 잡혀 서버 로그 한 줄만 남고
    **폰에서는 알림이 그냥 끊긴 것처럼 보인다.** None으로 떨어뜨려 기존 미연동 경로를
    타게 하면 FETCH_FAILED가 1회라도 나간다.

    구간 1개(영등포→서울)로 좁혀 호출 수를 결정적으로 만든다.
    """
    from app.adapters.korail2_adapter import CredentialsRequired

    class CredRequiringPort(FakePort):
        """자격증명 없이는 좌석맵을 못 주는 실제 korail2 어댑터의 행동."""

        async def get_seat_map(self, cred, train_no, d, frm, to):
            self.seat_map_calls.append((frm, to))
            if cred is None:
                raise CredentialsRequired("코레일 계정을 먼저 연결하세요")
            return await super().get_seat_map(cred, train_no, d, frm, to)

    # 다른 키로 암호화된 것처럼 깨진 암호문을 심는다
    db.execute(
        "UPDATE user SET korail_id = 'someone', korail_pw_enc = 'gAAAAABnot-a-valid-token'"
        " WHERE id = 1"
    )
    port, spy = CredRequiringPort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(
        db, status="STANDING", board_at="영등포", alight_at="서울", next_poll_at=at(8, 38)
    )

    report = await run_tick(deps, now=at(8, 38))

    assert spy.kinds == ["FETCH_FAILED"], f"조용히 끊겼다: {spy.kinds}"
    assert report.polled == []
    # CredentialsRequired는 ValueError 계열이라 재시도하지 않는다 —
    # 30초×3을 기다려도 같은 답이다 (재시도했다면 3회가 찍힌다)
    assert len(port.seat_map_calls) == 1
    # 포인터는 전진한다 (그 시점 포기, D-17)
    assert row_of(db, sub_id)["next_poll_at"] == to_db(at(8, 44))


# ── 구간 단위 부분 실패 (이슈 #40 → D-48) ────────────────────────────
async def test_일부_구간_실패는_알림을_보류하고_해시를_지킨다(db):
    """★ 회귀 방어. **불완전한 관측으로는 알리지 않는다.**

    실패한 관측으로 해시를 덮으면 실패 → 복구가 그 자체로 "상태 변화"가 되어,
    좌석이 하나도 안 팔렸는데 알림이 두 번 나간다. 해시를 그대로 두면 다음 완전한
    조회가 **마지막 완전한 관측**과 비교되므로 그 요동이 애초에 생기지 않는다.
    """
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="SEATED", my_car=3, my_seat_no="7A")

    await run_tick(deps, now=SUWON_POINT_10)  # 완전한 조회 — 베이스라인 1건
    assert len(spy.notes) == 1
    hash_before = row_of(db, sub_id)["last_verdict_hash"]
    snapshot_before = row_of(db, sub_id)["last_cells_snapshot"]
    spy.notes.clear()

    # 한 구간만 실패한다 (매진이 아니라 조회 실패다)
    port.failing_segments = {2}
    report = await run_tick(deps, now=SUWON_POINT_4)

    assert spy.kinds == [], f"불완전한 관측으로 알림이 나갔다: {spy.kinds}"
    assert sub_id in report.polled
    row = row_of(db, sub_id)
    assert row["last_verdict_hash"] == hash_before, "실패한 관측이 해시를 덮었다"
    assert row["last_cells_snapshot"] == snapshot_before
    # FETCH_FAILED는 전 구간 실패의 신호다 — 부분 실패로 fail_count를 올리지 않는다
    assert row["fail_count"] == 0
    # 그 시점은 포기하고 포인터는 전진한다 (D-17)
    assert row["next_poll_at"] == to_db(at(8, 28))


async def test_전_구간_실패는_기존대로_FETCH_FAILED다(db):
    """부분 실패와 전 구간 실패는 다르다 — 보여줄 것이 없으면 실패가 맞다 (D-34)."""
    port, spy = FakePort(cells()), SpyNotifier()
    deps = deps_for(db, port, spy)
    sub_id = make_sub(db, status="STANDING", board_at="영등포", alight_at="서울")
    port.failing_segments = {4}  # 구간 1개짜리 이용구간 → 전 구간 실패

    await run_tick(deps, now=at(8, 38))
    assert spy.kinds == ["FETCH_FAILED"]
    assert row_of(db, sub_id)["fail_count"] == 1
