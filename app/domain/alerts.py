"""알림 변화 감지 + 합성 (PLAN.md 8절, D-16/D-20). 순수 함수.

중복 발송·미발송 **둘 다 조용히 틀린다.** 13절의 7개 케이스를 test_alerts.py가 잠근다.

감지는 이중이다:
- **해시** (`last_verdict_hash`) — "상태가 달라졌나"만 답한다. 방향을 모른다
- **셀 스냅샷** (`last_cells_snapshot`) — 내 좌석 셀의 `true→false` 전이.
  실제 취소/환불과 1:1 대응하며, 열차 진행만으로는 절대 발화하지 않는다

Phase 1은 여기까지(감지·합성)다. 실제 발송(NotifierPort)은 Phase 3.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.domain.models import (
    Alert,
    AlertKind,
    SeatRecommendation,
    SubscriptionStatus,
    Verdict,
    seat_key,
)

# 합성 우선순위 — 상위가 하위를 본문에 흡수해 폴링 시점당 푸시 1건 (D-20)
PRIORITY: tuple[AlertKind, ...] = (
    AlertKind.ALL_SOLD,
    AlertKind.MY_SEAT_SOLD,
    AlertKind.SEATS_AVAILABLE,
    AlertKind.SEAT_EXTENDED,
)


@dataclass(frozen=True)
class AlertConfig:
    """조정 예정 손잡이 (D-17/D-20). 매직 넘버를 로직에 인라인하지 않는다."""

    digest_limit: int = 3  # SEATS_AVAILABLE 다이제스트 상위 N석
    min_extension_segments: int = 1  # 1 = 한 구간 연장도 전부 발송 (D-16 사용자 결정)


DEFAULT_ALERTS = AlertConfig()


@dataclass(frozen=True)
class AlertContext:
    """알림 문구 생성에 필요한 구독 컨텍스트."""

    subscription_id: int
    stops: list[str]
    alight_idx: int
    my_car: int | None = None
    my_seat_no: str | None = None

    @property
    def my_label(self) -> str | None:
        if self.my_car is None or not self.my_seat_no:
            return None
        return seat_key(self.my_car, self.my_seat_no)

    @property
    def alight_station(self) -> str:
        return self.stops[self.alight_idx]

    def station(self, idx: int) -> str:
        return self.stops[min(max(idx, 0), len(self.stops) - 1)]


@dataclass(frozen=True)
class AlertDecision:
    """감지 결과. 스케줄러는 이 값을 그대로 DB에 기록한다 (기록은 스케줄러만, D-13/D-17)."""

    alert: Alert | None
    verdict_hash: str
    cells_snapshot: list[bool] | None


def verdict_hash(verdict: Verdict) -> str:
    """상태 해시 (PLAN 8절 표). 상태별 **최소 튜플**만 해시한다.

    `move_to` 전체 리스트와 정렬 순서는 제외한다 — 하위 추천의 미세 변동으로
    알림이 나가면 안 된다 (스퍼리어스 발송 방지, D-16).

    **지연 착석 1순위(`later_top`)는 `move_to`가 비었을 때만 넣는다** (→ D-46).

    - 넣지 않으면: "지금은 못 앉지만 수원부터 앉을 수 있는 자리가 생겼다"가 상태 변화로
      잡히지 않아 **영원히 침묵한다.** 퇴근길에는 그게 유일하게 쓸모 있는 정보다
    - 무조건 넣으면: **지금 앉을 자리가 있는데도** 지연 착석 목록의 변동만으로 알림이
      나간다. 앉을 수 있으면 그냥 가서 앉으면 되므로 그 변동은 의사결정과 무관하다 —
      D-16이 막으려던 스퍼리어스 발송 그 자체다 (실제로 `test_하위_추천만_바뀌면_침묵한다`와
      `test_열차_진행만으로는_연장_알림이_나가지_않는다`가 잡아냈다)

    즉 **지연 착석은 지금 앉을 자리가 없을 때만 의사결정에 관여한다.**
    """
    top = verdict.move_to[0].key if verdict.move_to else None
    later = verdict.move_to_later[0] if verdict.move_to_later and not verdict.move_to else None
    # 좌석이 같아도 "언제부터"가 당겨지면 사용자에게는 다른 정보다
    later_top = f"{later.key}@{later.clear_from_idx}" if later else None
    if verdict.sub_status is SubscriptionStatus.STANDING:
        payload = [verdict.current_seg_idx, top, later_top, verdict.all_sold_after_current]
    else:
        payload = [
            verdict.my_seat_status,
            verdict.my_seat_sold_from,
            verdict.my_seat_clear_until_idx,
            top,
            later_top,
            verdict.all_sold_after_current,
        ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def count_extensions(
    prev_cells: list[bool] | None,
    cur_cells: list[bool] | None,
    start_idx: int,
    alight_idx: int,
) -> int:
    """잔여 이용구간 내 `true→false`(판매→빈자리) 전이 개수 (D-16).

    `clear_until` 증가를 트리거로 쓰면 **열차가 판매 구간을 지나치기만 해도** 값이
    점프해 취소 없이 "연장" 알림이 나간다. 그래서 셀 단위 비교만 쓴다.
    스냅샷이 없으면(상태 전이 직후 무효화) 0 — 이번 조회는 스냅샷만 쌓는다.
    """
    if prev_cells is None or cur_cells is None:
        return 0
    if len(prev_cells) != len(cur_cells):
        return 0
    return sum(
        1
        for i in range(start_idx, min(alight_idx, len(cur_cells)))
        if prev_cells[i] and not cur_cells[i]
    )


def evaluate(
    *,
    verdict: Verdict,
    ctx: AlertContext,
    my_seat_cells: list[bool] | None,
    prev_cells: list[bool] | None,
    prev_hash: str | None,
    config: AlertConfig = DEFAULT_ALERTS,
) -> AlertDecision:
    """한 조회 시점의 알림 결정 (PLAN 8·9절).

    - `prev_hash`가 NULL이면 **베이스라인 1건**을 반드시 발송한다 (D-20)
    - 해시가 같으면 해시 기반 종류는 침묵한다 (원칙 6: 동일 상태 중복 발송 금지)
    - `SEAT_EXTENDED`는 해시와 무관하게 셀 전이로만 발화한다
    - 여러 종류가 동시 성립하면 **우선순위 합성으로 1건**
    """
    cur_hash = verdict_hash(verdict)
    start_idx = verdict.current_seg_idx
    baseline = prev_hash is None
    changed = prev_hash != cur_hash

    extensions = count_extensions(prev_cells, my_seat_cells, start_idx, ctx.alight_idx)
    extended = extensions >= config.min_extension_segments and extensions > 0

    kinds: list[AlertKind] = []
    if baseline or changed:
        if verdict.all_sold_after_current:
            kinds.append(AlertKind.ALL_SOLD)
        if verdict.sub_status is SubscriptionStatus.SEATED and verdict.my_seat_status == "SOLD_FROM":
            kinds.append(AlertKind.MY_SEAT_SOLD)
        # 지연 착석만 있어도 보낸다 (→ D-46). 폴링은 정차역 도착 10분/4분 전이라
        # "수원부터 4호차"를 미리 알면 그 호차로 걸어가 대기할 수 있다 — 행동 가능한 정보다.
        # 알림 종류는 늘리지 않는다(8절). 다이제스트 문구만 "수원부터"가 붙는다
        if verdict.sub_status is SubscriptionStatus.STANDING and (
            verdict.move_to or verdict.move_to_later
        ):
            kinds.append(AlertKind.SEATS_AVAILABLE)
    if extended:
        kinds.append(AlertKind.SEAT_EXTENDED)

    if baseline and not kinds:
        # 베이스라인은 무조건 1건 — 알림 파이프라인이 오늘 살아있다는 생존 확인 (D-20).
        # 남는 경우는 "SEATED이고 하차역까지 안전" 뿐이라 이동 불필요 문구로 보낸다.
        kinds.append(
            AlertKind.SEAT_EXTENDED
            if verdict.sub_status is SubscriptionStatus.SEATED
            else AlertKind.SEATS_AVAILABLE
        )

    alert = _compose(kinds, verdict=verdict, ctx=ctx, config=config) if kinds else None
    return AlertDecision(alert=alert, verdict_hash=cur_hash, cells_snapshot=my_seat_cells)


def fetch_failed_alert(ctx: AlertContext, *, reason: str | None = None) -> Alert:
    """조회 실패 (D-17). 합성 대상이 아니다 — 다른 종류가 애초에 계산 불가다.

    `reason`은 진단 문구다. 5종을 늘리지 않으면서(8절) "왜 실패했는지"를 알려주려면
    본문에 담는 수밖에 없다 — 자격증명 미연동과 코레일 장애는 사용자가 취할 행동이
    전혀 다른데 둘 다 "갱신 실패"로만 오면 앱을 열어봐도 알 수 없다 (D-34).
    """
    tail = f" ({reason})" if reason else ""
    return Alert(
        kind=AlertKind.FETCH_FAILED,
        title="좌석 정보 갱신 실패",
        body=f"화면 데이터가 낡았습니다 · 앱에서 수동 갱신해 주세요{tail}",
        subscription_id=ctx.subscription_id,
    )


# ── 문구 생성 ────────────────────────────────────────────────────────
def _compose(
    kinds: list[AlertKind], *, verdict: Verdict, ctx: AlertContext, config: AlertConfig
) -> Alert:
    """우선순위 합성 — 상위 종류가 하위를 본문에 흡수해 1건으로 만든다 (D-20)."""
    ordered = sorted(set(kinds), key=PRIORITY.index)
    primary = ordered[0]
    absorbed = list(reversed(ordered[1:]))  # 낮은 우선순위(세부)부터 → 결론 순

    parts = [_short(k, verdict=verdict, ctx=ctx) for k in absorbed]
    parts.append(_body(primary, verdict=verdict, ctx=ctx, config=config))
    return Alert(
        kind=primary,
        title=_title(primary, verdict=verdict, ctx=ctx),
        body=" · ".join(p for p in parts if p),
        subscription_id=ctx.subscription_id,
    )


def _next_station(verdict: Verdict, ctx: AlertContext) -> str:
    return ctx.station(verdict.current_seg_idx + 1)


def _seat_phrase(r: SeatRecommendation, verdict: Verdict, ctx: AlertContext) -> str:
    """좌석 하나의 문구. **"언제부터"를 빠뜨리면 지금 앉을 수 있다고 오해한다** (→ D-46)."""
    until = ctx.alight_station if r.clear_all else ctx.station(r.clear_until_idx)
    if r.clear_from_idx > verdict.current_seg_idx:
        return f"{r.car}-{r.seat_no}({ctx.station(r.clear_from_idx)}부터 {until}까지)"
    return f"{r.car}-{r.seat_no}({until}까지)"


def _digest(verdict: Verdict, ctx: AlertContext, config: AlertConfig) -> str:
    """착석 가능 좌석 다이제스트 — 상위 N석 + "외 M석" (D-20).

    지금 앉을 수 있는 좌석을 먼저 채우고, 남는 자리에 지연 착석을 넣는다 (→ D-46).
    퇴근길처럼 `move_to`가 비면 지연 착석만으로 채워진다.
    """
    pool = list(verdict.move_to) + list(verdict.move_to_later)
    recs = pool[: config.digest_limit]
    if not recs:
        return "앉을 좌석 없음"
    head = ", ".join(_seat_phrase(r, verdict, ctx) for r in recs)
    rest = len(pool) - len(recs)
    return f"{head} 외 {rest}석" if rest > 0 else head


def _title(kind: AlertKind, *, verdict: Verdict, ctx: AlertContext) -> str:
    match kind:
        case AlertKind.ALL_SOLD:
            return "잔여 좌석 없음"
        case AlertKind.MY_SEAT_SOLD:
            return f"내 자리 {ctx.my_label} 판매됨"
        case AlertKind.SEATS_AVAILABLE:
            # 지연 착석만 있으면 "다음 역부터"가 아니라 **실제로 앉을 수 있는 역**을 쓴다.
            # 제목이 틀리면 알림 목록에서 그것만 보고 잘못 판단한다 (→ D-46)
            if not verdict.move_to and verdict.move_to_later:
                first = min(r.clear_from_idx for r in verdict.move_to_later)
                return f"{ctx.station(first)}부터 착석 가능"
            return f"{_next_station(verdict, ctx)}부터 착석 가능"
        case AlertKind.SEAT_EXTENDED:
            return f"내 자리 {ctx.my_label} 이용 구간 연장"
        case _:  # pragma: no cover - FETCH_FAILED는 합성 대상이 아니다
            return "알림"


def _body(kind: AlertKind, *, verdict: Verdict, ctx: AlertContext, config: AlertConfig) -> str:
    match kind:
        case AlertKind.ALL_SOLD:
            return f"{_next_station(verdict, ctx)} 이후 잔여 없음 → 지하철 환승 고려"
        case AlertKind.MY_SEAT_SOLD:
            sold_from = verdict.my_seat_sold_from or _next_station(verdict, ctx)
            top = verdict.move_to[0] if verdict.move_to else None
            if top is None:
                return f"{ctx.my_label} {sold_from}부터 판매됨 · 옮길 좌석 없음"
            return (
                f"{ctx.my_label} {sold_from}부터 판매됨 → {top.car}-{top.seat_no}로 이동 "
                f"(옮겼으면 앱에서 내 자리 갱신)"
            )
        case AlertKind.SEATS_AVAILABLE:
            return f"{_digest(verdict, ctx, config)} (앉으면 앱에서 내 자리 갱신)"
        case AlertKind.SEAT_EXTENDED:
            until = verdict.my_seat_clear_until_idx
            where = ctx.station(until) if until is not None else ctx.alight_station
            return f"{ctx.my_label} {where}까지 확보 — 이동 불필요"
        case _:  # pragma: no cover
            return ""


def _short(kind: AlertKind, *, verdict: Verdict, ctx: AlertContext) -> str:
    """상위 종류에 흡수될 때의 축약 문구."""
    match kind:
        case AlertKind.ALL_SOLD:
            return "잔여 없음"
        case AlertKind.MY_SEAT_SOLD:
            sold_from = verdict.my_seat_sold_from or _next_station(verdict, ctx)
            return f"{ctx.my_label} {sold_from}부터 판매됨"
        case AlertKind.SEATS_AVAILABLE:
            if verdict.move_to:
                top = verdict.move_to[0]
                return f"착석 가능 {top.car}-{top.seat_no}"
            if verdict.move_to_later:
                top = verdict.move_to_later[0]
                return f"{ctx.station(top.clear_from_idx)}부터 {top.car}-{top.seat_no}"
            return ""
        case AlertKind.SEAT_EXTENDED:
            return f"{ctx.my_label} 구간 연장"
        case _:  # pragma: no cover
            return ""
