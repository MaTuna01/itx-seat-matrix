"""폴링 사이클 (PLAN.md 9절, D-17/D-19/D-20). Phase 3의 중심.

**판정은 여기서 하지 않는다.** `domain/alerts.evaluate()`와 `domain/timeline.resolve_poll()`이
Phase 1에서 이미 끝냈고 테스트도 통과한다. 이 모듈이 하는 일은 그 결정을 조회·발송·DB에
배선하는 것이다. 시각 계산이나 알림 종류 판단을 여기서 새로 짜면 두 곳에 흩어진다.

30초 틱의 일은 **단 하나**다: `next_poll_at <= now`인 활성 구독을 실행하고 포인터를 다음
포인트로 전진 (D-19). 재시작해도 DB의 포인터에서 그대로 이어진다 (멱등).

이 모듈만이 `last_verdict_hash` / `last_cells_snapshot` / `last_notified_at` / `fail_count`를
기록한다 (절대규칙 5, D-13/D-17). 사용자 화면 조회(`/matrix`)는 알림 상태를 건드리지 않는다.

시간은 전부 `now: datetime` 인자로 주입받는다 — 내부에서 `datetime.now()`를 부르지 않는다
(D-21). 실제 시계를 읽는 곳은 `service.py`의 틱 진입점 하나뿐이다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime
from typing import Awaitable, Callable

from app.adapters.delay_port import DelayPort
from app.adapters.korail_port import KorailPort
from app.adapters.notify import deliver
from app.adapters.notifier_port import CompositeNotifier
from app.adapters.seatmap_fetcher import (
    JITTER_RANGE,
    SCHEDULER_RETRY,
    RetryPolicy,
    fetch_matrix,
)
from app.domain.alerts import (
    DEFAULT_ALERTS,
    AlertConfig,
    AlertContext,
    evaluate,
    fetch_failed_alert,
)
from app.domain.matrix import query_range
from app.domain.models import Alert, SeatMatrix, StopInfo, SubscriptionStatus
from app.domain.timeline import (
    DEFAULT_TIMELINE,
    TimelineConfig,
    compute_poll_points,
    is_ride_over,
    resolve_poll,
    sellable_seg_idx,
)
from app.domain.verdict import build_verdict
from app.storage.creds import load_korail_cred
from app.storage.db import date_from_db, dt_from_db, get_conn, to_db

log = logging.getLogger(__name__)

ConnFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


@dataclass(frozen=True)
class PollerDeps:
    """스케줄러가 바깥세상에 닿는 지점 전부. 테스트는 여기에 가짜를 꽂는다.

    조정 예정 손잡이(retry/timeline/alerts)는 전부 설정값으로 격리돼 있다 (D-17).
    """

    port: KorailPort
    delay_port: DelayPort
    notifier: CompositeNotifier
    conn_factory: ConnFactory = get_conn
    retry: RetryPolicy = SCHEDULER_RETRY
    timeline: TimelineConfig = DEFAULT_TIMELINE
    alerts: AlertConfig = DEFAULT_ALERTS
    jitter: tuple[float, float] | None = JITTER_RANGE
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


@dataclass
class TickReport:
    """한 틱의 결과. 로그와 테스트 단언의 대상이다 (알림 이력 테이블은 두지 않는다)."""

    polled: list[int] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    expired: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.polled or self.expired or self.skipped)


async def run_tick(deps: PollerDeps, *, now: datetime) -> TickReport:
    """30초 틱 1회. 포인터가 도래한 구독만 건드린다.

    `next_poll_at IS NULL`도 후보에 넣는 이유는 **만료 판정** 때문이다 — 마지막 폴
    포인트를 지나면 포인터가 비는데, 그 뒤 하차역을 통과했는지 확인할 주체가 없으면
    구독이 영원히 살아남는다 (Phase 2에서 실제로 겪었다).

    한 구독의 예외가 나머지를 막지 않는다. 틱이 죽으면 그 뒤 구독이 전부 조회되지 않는다.
    """
    report = TickReport()
    with deps.conn_factory() as conn:
        rows = conn.execute(
            "SELECT * FROM subscription"
            " WHERE active = 1 AND (next_poll_at IS NULL OR next_poll_at <= ?)"
            " ORDER BY id",
            (to_db(now),),
        ).fetchall()
        for row in rows:
            try:
                await _run_one(deps, conn, row, now=now, report=report)
            except Exception as exc:  # noqa: BLE001 — 한 구독의 사고를 격리한다
                log.exception("구독 %s 폴링 실패", row["id"])
                report.notes.append(f"구독 {row['id']} 예외: {exc}")
    return report


async def _run_one(
    deps: PollerDeps,
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    now: datetime,
    report: TickReport,
) -> None:
    sub_id: int = row["id"]
    ride_date = date_from_db(row["date"])
    # 자격증명은 조회 직전에만 복호화한다. 응답 모델에 담지 마라 (절대규칙 9)
    cred = load_korail_cred(conn, row["user_id"])

    stops = await _resolve_stops(deps, row, ride_date)
    if stops is None:
        # 정차역을 모르면 만료 판정도 폴 포인트 계산도 불가능하다.
        # 안전망: 지난 운행일이면 만료시킨다 — 그러지 않으면 캐시가 채워질 때까지
        # 어제 구독이 영원히 후보로 남아 매 틱 실패한다 (D-34)
        if ride_date < now.date():
            _expire(conn, sub_id)
            report.expired.append(sub_id)
            report.notes.append(f"구독 {sub_id}: 정차역 미확인 + 지난 운행일 → 만료")
            return
        # 포인터는 그대로 둔다 — 캐시가 채워지면 resolve_poll이 지각 포인트를
        # grace 규칙대로 처리한다. 여기서 비우면 복구돼도 다시는 조회되지 않는다
        await _record_failure(
            deps, conn, row, report, now=now, reason="정차역 정보를 얻을 수 없음"
        )
        return

    names = [stop.name for stop in stops]
    if row["board_at"] not in names or row["alight_at"] not in names:
        # 노선이 바뀌어 내 역이 사라졌다. 다시 조회해도 같은 답이므로 만료가 맞다.
        _expire(conn, sub_id)
        report.expired.append(sub_id)
        await _record_failure(
            deps, conn, row, report, now=now, reason="노선에서 내 역을 찾을 수 없음"
        )
        return
    board_idx, alight_idx = names.index(row["board_at"]), names.index(row["alight_at"])

    delay = await _resolve_delay(deps, row["train_no"], ride_date)

    # ── D. 구독 자동 만료 (PLAN 9절) ─────────────────────────────────
    if is_ride_over(stops, alight_idx, delay, now):
        _expire(conn, sub_id)
        report.expired.append(sub_id)
        return

    # ── B. 포인터 해석 + 전진 (D-19) ─────────────────────────────────
    # 지연이 갱신되면 폴 포인트가 통째로 밀린다 — 매 틱 재계산하므로 자동으로 반영된다.
    points = compute_poll_points(stops, board_idx, alight_idx, delay, deps.timeline)
    decision = resolve_poll(
        next_poll_at=dt_from_db(row["next_poll_at"]),
        poll_points=points,
        now=now,
        config=deps.timeline,
    )
    if decision.skipped:
        report.skipped.append(sub_id)
        report.notes.append(f"구독 {sub_id}: grace 초과로 {len(decision.skipped)}개 포인트 스킵")
    if not decision.fire:
        _set_pointer(conn, sub_id, decision.next_poll_at)
        return

    # ── C. 폴링 사이클 ───────────────────────────────────────────────
    # 위치는 시각표+지연 추정만 쓴다. GPS는 화면 전용이다 (D-13).
    # 조회·판정의 시작은 위치가 아니라 **팔 수 있는 첫 구간**이다 — 출발한 구간을 조회하면
    # 빈 응답이 오고 그것이 '전 좌석 판매됨'으로 읽혀 판정이 뒤집힌다 (이슈 #35 → D-47)
    sellable_idx = sellable_seg_idx(stops, delay, now)
    start_idx, end_idx = query_range(sellable_idx, board_idx, alight_idx)
    try:
        matrix = await fetch_matrix(
            deps.port,
            cred,
            row["train_no"],
            ride_date,
            names,
            start_idx,
            end_idx,
            now=now,
            # ★ cache를 넘기지 않는다. 캐시된 값으로 판정하면 상태 변화를 놓쳐
            #   알림이 조용히 안 온다 (D-17). 60초 캐시는 화면 트래픽 전용이다
            cache=None,
            retry=deps.retry,
            jitter=deps.jitter,
            sleep=deps.sleep,
        )
    except Exception as exc:  # noqa: BLE001 — 코레일/네트워크 장애 전반
        # 3회 재시도까지 `fetch_matrix` 안에서 이미 끝났다. 여기 오면 그 시점을 포기하고
        # 포인터를 전진시킨다 — 낡은 시점을 붙잡고 있으면 다음 조회와 겹치기만 한다 (D-17)
        _set_pointer(conn, sub_id, decision.next_poll_at)
        await _record_failure(deps, conn, row, report, now=now, reason=str(exc))
        return

    report.polled.append(sub_id)

    if matrix.failed_seg_idxs:
        # 일부 구간만 조회에 실패했다 (→ D-48). **불완전한 관측으로는 알리지 않는다.**
        #
        # 판정 자체는 실패 구간에서 멈추도록 이미 보수적이지만, 문제는 상태 비교다:
        # 실패한 관측으로 해시를 덮으면 실패 → 복구가 그 자체로 "상태 변화"가 되어
        # 좌석이 하나도 안 팔렸는데 알림이 두 번 나간다. 해시를 그대로 두면 다음 완전한
        # 조회가 **마지막 완전한 관측**과 비교되므로 그 요동이 애초에 생기지 않는다.
        #
        # 화면은 부분 결과를 그대로 보여준다 — 사람이 직접 보고 판단하는 경로이므로
        # "수원까지만 확인됨"이 유용하다. 알림은 그렇지 않다.
        # `fail_count`는 건드리지 않는다. FETCH_FAILED(D-34)는 전 구간 실패의 신호다
        _set_pointer(conn, sub_id, decision.next_poll_at)
        report.notes.append(
            f"구독 {sub_id}: 구간 {matrix.failed_seg_idxs} 조회 실패 → 부분 결과, 알림 보류"
        )
        return

    status = SubscriptionStatus(row["status"])
    my_car, my_seat_no = row["my_car"], row["my_seat_no"]
    verdict = build_verdict(
        matrix=matrix,
        status=status,
        board_idx=board_idx,
        alight_idx=alight_idx,
        sellable_seg_idx=sellable_idx,
        my_car=my_car,
        my_seat_no=my_seat_no,
    )
    ctx = AlertContext(
        subscription_id=sub_id,
        stops=names,
        alight_idx=alight_idx,
        my_car=my_car,
        my_seat_no=my_seat_no,
    )
    outcome = evaluate(
        verdict=verdict,
        ctx=ctx,
        my_seat_cells=_my_seat_cells(matrix, my_car, my_seat_no),
        prev_cells=_load_snapshot(row["last_cells_snapshot"]),
        prev_hash=row["last_verdict_hash"],
        config=deps.alerts,
    )

    notified_at: datetime | None = None
    if outcome.alert is not None:
        result = await deliver(conn, row["user_id"], outcome.alert, notifier=deps.notifier)
        report.alerts.append(outcome.alert)
        report.notes.extend(f"구독 {sub_id}: {err}" for err in result.errors)
        if result.delivered:
            notified_at = now

    # 발송 성공 여부와 무관하게 상태를 기록한다. 상태는 "관측한 것"이고 발송은 "알린 것"이라
    # 섞으면 발송 실패가 상태 오염으로 번진다. 애초에 iOS는 배달 성공을 서버에 알려주지
    # 않으므로 "발송 성공"이 신뢰 가능한 신호가 아니다 (8절의 폴백 거부 논리와 동일).
    # 기기 미등록으로 알림이 새는 구멍은 `/api/push/test`가 막는다 (D-9).
    conn.execute(
        "UPDATE subscription SET last_verdict_hash = ?, last_cells_snapshot = ?,"
        " next_poll_at = ?, fail_count = 0"
        + (", last_notified_at = ?" if notified_at is not None else "")
        + " WHERE id = ?",
        (
            outcome.verdict_hash,
            _dump_snapshot(outcome.cells_snapshot),
            to_db(decision.next_poll_at),
            *([to_db(notified_at)] if notified_at is not None else []),
            sub_id,
        ),
    )


# ── 외부 조회 래핑 ───────────────────────────────────────────────────
async def _resolve_stops(
    deps: PollerDeps, row: sqlite3.Row, ride_date: _date
) -> list[StopInfo] | None:
    """정차역. 실패를 예외로 올리지 않고 None으로 답한다 (호출부가 만료/실패를 가른다).

    korail2 어댑터에서는 `train_stop` 캐시 조회라 네트워크를 타지 않는다 (D-29).
    """
    try:
        return await deps.port.get_stops(None, row["train_no"], ride_date)
    except Exception as exc:  # noqa: BLE001 — TrainStopsNotCached / ValueError 등
        log.warning("구독 %s 정차역 조회 실패: %s", row["id"], exc)
        return None


async def _resolve_delay(deps: PollerDeps, train_no: str, ride_date: _date) -> int:
    """지연 분. 폴링 사이클당 1회. 실패해도 0으로 계속 동작한다 (우아한 성능 저하, D-12)."""
    try:
        return await deps.delay_port.get_delay_minutes(train_no, ride_date) or 0
    except Exception as exc:  # noqa: BLE001
        log.warning("열차 %s 지연 조회 실패: %s", train_no, exc)
        return 0


# ── 상태 기록 ────────────────────────────────────────────────────────
async def _record_failure(
    deps: PollerDeps,
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    report: TickReport,
    *,
    now: datetime,
    reason: str,
) -> None:
    """`FETCH_FAILED`를 **1회만** 발송한다 (8절 "복구까지 재발송 없음", D-34).

    `fail_count`가 그 게이트다: 실패 +1 / 성공 0 리셋 / **0→1 전이에서만** 발송.
    재시도해도 같은 결과인 실패(자격증명 미연동, 정차역 캐시 없음)도 같은 게이트를 쓴다 —
    안 보내면 알림이 조용히 죽은 것을 폰에서 알 방법이 없다 (D-34).

    **포인터는 건드리지 않는다.** 전진 여부는 실패 종류마다 달라서 호출부가 정한다 —
    여기서 일괄로 비우면 일시적 실패 한 번에 포인터를 잃고 그 구독이 영구히 조회되지 않는다.
    """
    fail_count = int(row["fail_count"] or 0) + 1
    conn.execute(
        "UPDATE subscription SET fail_count = ? WHERE id = ?", (fail_count, row["id"])
    )
    report.notes.append(f"구독 {row['id']} 조회 실패({fail_count}회): {reason}")
    if fail_count > 1:
        return

    # FETCH_FAILED는 합성 대상이 아니고 구간 정보를 쓰지 않는다 — 사용자의 이용 구간
    # 두 역만으로 컨텍스트를 만든다 (노선 전체를 모르는 상황에서도 발송해야 한다).
    ctx = AlertContext(
        subscription_id=row["id"],
        stops=[row["board_at"], row["alight_at"]],
        alight_idx=1,
        my_car=row["my_car"],
        my_seat_no=row["my_seat_no"],
    )
    alert = fetch_failed_alert(ctx, reason=reason)
    result = await deliver(conn, row["user_id"], alert, notifier=deps.notifier)
    report.alerts.append(alert)
    report.notes.extend(f"구독 {row['id']}: {err}" for err in result.errors)
    if result.delivered:
        conn.execute(
            "UPDATE subscription SET last_notified_at = ? WHERE id = ?",
            (to_db(now), row["id"]),
        )


def _expire(conn: sqlite3.Connection, sub_id: int) -> None:
    """하차 완료/무효 구독 비활성화 (PLAN 9절). 포인터도 비워 후보에서 빠지게 한다."""
    conn.execute(
        "UPDATE subscription SET active = 0, next_poll_at = NULL WHERE id = ?", (sub_id,)
    )


def _set_pointer(conn: sqlite3.Connection, sub_id: int, next_poll_at: datetime | None) -> None:
    conn.execute(
        "UPDATE subscription SET next_poll_at = ? WHERE id = ?", (to_db(next_poll_at), sub_id)
    )


# ── 스냅샷 직렬화 ────────────────────────────────────────────────────
def _my_seat_cells(matrix: SeatMatrix, my_car: int | None, my_seat_no: str | None) -> list[bool] | None:
    """내 좌석 행. 응답에 없으면 None — 스냅샷을 쌓지 않아 전이 판정이 다음 조회로 밀린다.

    "부재 = 판매됨" 추론으로 셀을 채우면 좌석이 실재하는지와 무관하게 전이가 발화한다.
    """
    if my_car is None or not my_seat_no:
        return None
    for seat in matrix.seats:
        if seat.car == my_car and seat.seat_no == my_seat_no:
            return list(seat.cells)
    return None


def _load_snapshot(raw: str | None) -> list[bool] | None:
    if not raw:
        return None
    try:
        return [bool(v) for v in json.loads(raw)]
    except (ValueError, TypeError):
        return None  # 깨진 스냅샷은 없는 것으로 — 이번 조회에서 다시 쌓인다


def _dump_snapshot(cells: list[bool] | None) -> str | None:
    return None if cells is None else json.dumps(cells, separators=(",", ":"))
