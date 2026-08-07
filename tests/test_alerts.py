"""알림 변화 감지 — PLAN 13절의 7개 케이스 (D-16/D-20).

**침묵해야 할 때 침묵하는지가 핵심이다.** 중복 발송도 미발송도 조용히 틀린다.
"""

from __future__ import annotations

from app.domain.alerts import (
    AlertConfig,
    AlertContext,
    count_extensions,
    evaluate,
    fetch_failed_alert,
    verdict_hash,
)
from app.domain.models import AlertKind, SubscriptionStatus
from app.domain.verdict import build_verdict
from tests.conftest import STOPS, make_matrix

SEATED = SubscriptionStatus.SEATED
STANDING = SubscriptionStatus.STANDING
F, T = False, True

MY_CAR, MY_SEAT = 3, "7A"
MY_KEY = "3-7A"


def ctx(*, seated: bool = True, alight_idx: int = 5) -> AlertContext:
    return AlertContext(
        subscription_id=1,
        stops=STOPS,
        alight_idx=alight_idx,
        my_car=MY_CAR if seated else None,
        my_seat_no=MY_SEAT if seated else None,
    )


def verdict_of(seats: dict[str, list[bool]], *, status, sellable_seg_idx: int, alight_idx: int = 5):
    return build_verdict(
        matrix=make_matrix(seats),
        status=status,
        board_idx=0,
        alight_idx=alight_idx,
        sellable_seg_idx=sellable_seg_idx,
        my_car=MY_CAR if status is SEATED else None,
        my_seat_no=MY_SEAT if status is SEATED else None,
    )


# ── ① 구간만 진행됐을 때(SEATED) 알림이 나가지 않는다 ─────────────────
def test_구간만_진행되면_침묵한다():
    seats = {MY_KEY: [F, F, F, T, T], "4-1B": [F, F, F, F, F]}
    before = verdict_of(seats, status=SEATED, sellable_seg_idx=0)
    after = verdict_of(seats, status=SEATED, sellable_seg_idx=1)

    first = evaluate(
        verdict=before, ctx=ctx(), my_seat_cells=seats[MY_KEY],
        prev_cells=None, prev_hash="baseline-already-sent",
    )
    second = evaluate(
        verdict=after, ctx=ctx(), my_seat_cells=seats[MY_KEY],
        prev_cells=seats[MY_KEY], prev_hash=first.verdict_hash,
    )
    assert second.verdict_hash == first.verdict_hash
    assert second.alert is None


# ── ② 하위 추천 순서/내용만 바뀌었을 때 침묵한다 ──────────────────────
def test_하위_추천만_바뀌면_침묵한다():
    mine = [F, F, T, T, T]  # 수원부터 판매 (SOLD_FROM 유지)
    before = verdict_of(
        {MY_KEY: mine, "4-1B": [F, F, F, F, F], "8-2A": [F, F, T, T, T]},
        status=SEATED, sellable_seg_idx=0,
    )
    after = verdict_of(
        # 8-2A가 하차역까지 비었다 — 최상위 추천(4-1B)은 그대로다
        {MY_KEY: mine, "4-1B": [F, F, F, F, F], "8-2A": [F, F, F, F, F]},
        status=SEATED, sellable_seg_idx=0,
    )
    assert [r.key for r in before.move_to] == ["4-1B"]
    assert [r.key for r in after.move_to] == ["4-1B", "8-2A"]

    decision = evaluate(
        verdict=after, ctx=ctx(), my_seat_cells=mine,
        prev_cells=mine, prev_hash=verdict_hash(before),
    )
    assert decision.alert is None  # move_to 전체 리스트는 해시 대상이 아니다


# ── ③ 열차 진행만으로 SEAT_EXTENDED가 발화하지 않는다 ─────────────────
def test_열차_진행으로는_연장_알림이_나가지_않는다():
    """`clear_until` 증가를 트리거로 쓰면 여기서 거짓 '연장'이 나간다 (D-16 함정)."""
    mine = [T, F, F, F, F]  # 천안→평택만 판매
    before = verdict_of({MY_KEY: mine}, status=SEATED, sellable_seg_idx=0)
    after = verdict_of({MY_KEY: mine}, status=SEATED, sellable_seg_idx=1)
    # 열차가 판매 구간을 지나쳤을 뿐인데 clear_until은 0 → 5로 점프한다
    assert before.my_seat_clear_until_idx == 0
    assert after.my_seat_clear_until_idx == 5

    decision = evaluate(
        verdict=after, ctx=ctx(), my_seat_cells=mine,
        prev_cells=mine, prev_hash=verdict_hash(before),
    )
    assert decision.alert is None


# ── ④ 셀 true→false 전이 시 발화한다 ────────────────────────────────
def test_셀_전이가_있으면_연장_알림이_나간다():
    before_cells = [F, F, T, T, T]
    after_cells = [F, F, F, F, F]  # 수원 이후가 취소로 전부 비었다
    before = verdict_of({MY_KEY: before_cells}, status=SEATED, sellable_seg_idx=0)
    after = verdict_of({MY_KEY: after_cells}, status=SEATED, sellable_seg_idx=0)

    decision = evaluate(
        verdict=after, ctx=ctx(), my_seat_cells=after_cells,
        prev_cells=before_cells, prev_hash=verdict_hash(before),
    )
    assert decision.alert is not None
    assert decision.alert.kind is AlertKind.SEAT_EXTENDED
    assert "서울까지 확보" in decision.alert.body
    assert "이동 불필요" in decision.alert.body
    assert decision.cells_snapshot == after_cells


def test_부분_연장은_내_자리_판매_알림에_흡수된다():
    # 수원→안양 한 구간만 취소됐다: 여전히 안양부터 판매되므로 상위 종류가 흡수한다 (D-20)
    before_cells = [F, F, T, T, T]
    after_cells = [F, F, F, T, T]
    before = verdict_of({MY_KEY: before_cells}, status=SEATED, sellable_seg_idx=0)
    after = verdict_of({MY_KEY: after_cells}, status=SEATED, sellable_seg_idx=0)

    decision = evaluate(
        verdict=after, ctx=ctx(), my_seat_cells=after_cells,
        prev_cells=before_cells, prev_hash=verdict_hash(before),
    )
    assert decision.alert.kind is AlertKind.MY_SEAT_SOLD
    assert "구간 연장" in decision.alert.body
    assert "안양부터 판매됨" in decision.alert.body


def test_전이가_최소_구간_수에_못_미치면_침묵한다():
    before_cells = [F, F, T, F, F]
    after_cells = [F, F, F, F, F]  # 한 구간만 연장 (전이 1회)
    before = verdict_of({MY_KEY: before_cells}, status=SEATED, sellable_seg_idx=0)
    after = verdict_of({MY_KEY: after_cells}, status=SEATED, sellable_seg_idx=0)

    decision = evaluate(
        verdict=after, ctx=ctx(), my_seat_cells=after_cells,
        prev_cells=before_cells, prev_hash=verdict_hash(before),
        config=AlertConfig(min_extension_segments=2),  # 손잡이 (D-16)
    )
    assert decision.alert is None


def test_잔여_구간_밖의_전이는_무시한다():
    # 이미 지나온 구간(0)에서만 전이가 있었다
    assert count_extensions([T, F, F], [F, F, F], start_idx=1, alight_idx=3) == 0
    assert count_extensions([T, T, F], [F, F, F], start_idx=1, alight_idx=3) == 1


# ── ⑤ 상태 전이 직후 스냅샷 무효화 ──────────────────────────────────
def test_상태_전이_직후에는_스냅샷만_쌓고_전이_판정을_하지_않는다():
    """PATCH로 자리를 옮기면 `last_cells_snapshot`이 NULL이 된다 (api/subscriptions.py).

    옛 좌석 스냅샷과 새 좌석 셀을 비교하면 거짓 SEAT_EXTENDED가 나간다.
    """
    # 옛 자리의 스냅샷은 [T, T, T, T, T]였다 — 그대로 비교하면 전이 5회로 읽힌다.
    # PATCH가 스냅샷을 NULL로 지웠으므로 이번 조회는 스냅샷만 쌓는다.
    new_cells = [F, F, F, F, F]
    v = verdict_of({MY_KEY: new_cells}, status=SEATED, sellable_seg_idx=0)

    decision = evaluate(
        verdict=v, ctx=ctx(), my_seat_cells=new_cells,
        prev_cells=None, prev_hash="hash-of-previous-seat",
    )
    assert decision.alert is None
    assert decision.cells_snapshot == new_cells  # 다음 조회부터 전이 판정이 산다


# ── ⑥ 복수 종류 동시 성립 시 우선순위 합성 1건 ───────────────────────
def test_복수_종류는_우선순위로_합성해_한_건만_보낸다():
    """'이동하라'와 '이동할 곳 없다'가 각각 오면 모순 푸시 2건이 된다 (D-20)."""
    seats = {MY_KEY: [F, T, T, T, T], "4-1B": [F, T, T, T, T]}
    before = verdict_of(
        {MY_KEY: [F, F, F, F, F], "4-1B": [F, F, F, F, F]}, status=SEATED, sellable_seg_idx=1
    )
    after = verdict_of(seats, status=SEATED, sellable_seg_idx=1)
    assert after.my_seat_status == "SOLD_FROM"
    assert after.all_sold_after_current is True

    decision = evaluate(
        verdict=after, ctx=ctx(), my_seat_cells=seats[MY_KEY],
        prev_cells=[F, F, F, F, F], prev_hash=verdict_hash(before),
    )
    assert decision.alert is not None
    alert = decision.alert
    assert alert.kind is AlertKind.ALL_SOLD  # 우선순위 최상위
    assert "3-7A" in alert.body and "판매됨" in alert.body  # 하위 종류를 본문에 흡수
    assert "환승" in alert.body


# ── ⑦ 해시 NULL 첫 조회는 항상 베이스라인 1건 ────────────────────────
def test_첫_조회는_안전한_상태라도_베이스라인을_보낸다():
    """알림 파이프라인이 오늘 살아있다는 생존 확인 (D-20)."""
    cells = [F, F, F, F, F]
    v = verdict_of({MY_KEY: cells, "4-1B": [T, T, T, T, T]}, status=SEATED, sellable_seg_idx=0)
    assert v.my_seat_status == "CLEAR_ALL"

    decision = evaluate(
        verdict=v, ctx=ctx(), my_seat_cells=cells, prev_cells=None, prev_hash=None
    )
    assert decision.alert is not None
    assert "서울까지" in decision.alert.body


def test_입석_첫_조회는_착석_가능_다이제스트다():
    v = verdict_of(
        {"4-1B": [F, F, F, F, F], "5-2A": [F, F, F, F, F], "6-3A": [F, F, T, T, T]},
        status=STANDING, sellable_seg_idx=1,
    )
    decision = evaluate(
        verdict=v, ctx=ctx(seated=False), my_seat_cells=None, prev_cells=None, prev_hash=None
    )
    assert decision.alert is not None
    assert decision.alert.kind is AlertKind.SEATS_AVAILABLE
    assert decision.alert.title == "수원부터 착석 가능"
    assert "4-1B(서울까지)" in decision.alert.body


def test_다이제스트_상한은_설정값이다():
    seats = {f"{car}-1A": [F, F, F, F, F] for car in range(1, 6)}
    v = verdict_of(seats, status=STANDING, sellable_seg_idx=0)
    decision = evaluate(
        verdict=v, ctx=ctx(seated=False), my_seat_cells=None, prev_cells=None, prev_hash=None,
        config=AlertConfig(digest_limit=2),
    )
    assert "외 1석" in decision.alert.body  # move_to 상한 3 중 2석만 노출


# ── 그 밖의 잠금 ────────────────────────────────────────────────────
def test_입석_상태에서_구간_진행은_새_다이제스트다():
    """입석은 **현재 구간도 상태의 일부**다 — 정차역당 1회 다이제스트가 원칙 위반이 아니다 (D-16)."""
    seats = {"4-1B": [F, F, F, F, F]}
    before = verdict_of(seats, status=STANDING, sellable_seg_idx=0)
    after = verdict_of(seats, status=STANDING, sellable_seg_idx=1)
    assert verdict_hash(before) != verdict_hash(after)

    decision = evaluate(
        verdict=after, ctx=ctx(seated=False), my_seat_cells=None,
        prev_cells=None, prev_hash=verdict_hash(before),
    )
    assert decision.alert is not None
    assert decision.alert.kind is AlertKind.SEATS_AVAILABLE


def test_내_자리_판매_알림에는_다음_행동이_들어간다():
    seats = {MY_KEY: [F, T, T, T, T], "4-1B": [F, F, F, F, F]}
    before = verdict_of({MY_KEY: [F, F, F, F, F], "4-1B": [F, F, F, F, F]},
                        status=SEATED, sellable_seg_idx=0)
    after = verdict_of(seats, status=SEATED, sellable_seg_idx=0)

    decision = evaluate(
        verdict=after, ctx=ctx(), my_seat_cells=seats[MY_KEY],
        prev_cells=[F, F, F, F, F], prev_hash=verdict_hash(before),
    )
    alert = decision.alert
    assert alert.kind is AlertKind.MY_SEAT_SOLD
    assert "평택부터 판매됨" in alert.body
    assert "4-1B로 이동" in alert.body
    assert "갱신" in alert.body  # 옮겼으면 앱에서 내 자리 갱신 (D-15)


def test_조회_실패_알림은_합성_대상이_아니다():
    alert = fetch_failed_alert(ctx())
    assert alert.kind is AlertKind.FETCH_FAILED
    assert alert.subscription_id == 1


# ── 지연 착석 (→ D-46) ───────────────────────────────────────────────
# 목업 노선: 천안(0) 평택(1) 수원(2) 안양(3) 영등포(4) 서울(5)


def test_지연_착석만_있어도_알림이_나간다():
    """퇴근길 모양 — 탑승 구간만 매진이고 그 뒤는 비어 있다.

    이걸 침묵시키면 **퇴근길에는 알림이 영원히 안 온다.** 폴링은 정차역 도착 10분/4분
    전이라 "평택부터 4호차"를 미리 알면 그 호차로 걸어가 대기할 수 있다.
    """
    seats = {"4-1B": [T, F, F, F, F], "3-9A": [T, T, T, T, T]}
    v = verdict_of(seats, status=STANDING, sellable_seg_idx=0)
    assert v.move_to == []  # 지금 앉을 좌석은 없다
    assert v.all_sold_after_current is False

    decision = evaluate(
        verdict=v, ctx=ctx(seated=False), my_seat_cells=None,
        prev_cells=None, prev_hash="something-else",
    )
    assert decision.alert is not None
    assert decision.alert.kind is AlertKind.SEATS_AVAILABLE


def test_지연_착석_문구는_언제부터인지를_반드시_말한다():
    """이게 빠지면 **지금 앉을 수 있다고 오해한다** — 추천을 안 하느니만 못하다."""
    seats = {"4-1B": [T, F, F, F, F]}
    v = verdict_of(seats, status=STANDING, sellable_seg_idx=0)
    decision = evaluate(
        verdict=v, ctx=ctx(seated=False), my_seat_cells=None,
        prev_cells=None, prev_hash="something-else",
    )
    alert = decision.alert
    assert alert is not None
    # 제목은 "다음 역"이 아니라 실제로 앉을 수 있는 역이다
    assert alert.title == "평택부터 착석 가능"
    assert "4-1B(평택부터 서울까지)" in alert.body


def test_다이제스트는_지금_앉을_좌석을_먼저_넣는다():
    seats = {"4-1B": [F, T, T, T, T], "4-2B": [T, F, F, F, F]}
    v = verdict_of(seats, status=STANDING, sellable_seg_idx=0)
    assert [r.seat_no for r in v.move_to] == ["1B"]
    assert [r.seat_no for r in v.move_to_later] == ["2B"]

    decision = evaluate(
        verdict=v, ctx=ctx(seated=False), my_seat_cells=None,
        prev_cells=None, prev_hash="something-else",
    )
    body = decision.alert.body
    assert body.index("4-1B") < body.index("4-2B")
    assert "4-1B(평택까지)" in body  # 지금 앉을 수 있는 좌석에는 "부터"가 없다
    assert "4-2B(평택부터 서울까지)" in body


def test_지금_앉을_자리가_있으면_지연_목록_변동은_침묵한다():
    """지연 착석은 **지금 앉을 자리가 없을 때만** 의사결정에 관여한다.

    무조건 해시에 넣으면 앉을 수 있는데도 하위 변동으로 알림이 나간다 (D-16).
    """
    keep = {"4-1B": [F, F, F, F, F]}  # 하차역까지 빈 좌석 — 1순위는 고정
    before = verdict_of({**keep, "4-2B": [T, F, F, F, F]}, status=STANDING, sellable_seg_idx=0)
    after = verdict_of({**keep, "4-2B": [T, T, F, F, F]}, status=STANDING, sellable_seg_idx=0)

    # 지연 착석 1순위의 "언제부터"가 평택 → 수원으로 밀렸다
    assert before.move_to_later[0].clear_from_idx == 1
    assert after.move_to_later[0].clear_from_idx == 2
    assert verdict_hash(before) == verdict_hash(after), "지연 목록 변동으로 해시가 바뀌었다"


def test_지연_착석_1순위가_바뀌면_알림이_나간다():
    """반대로, 지금 앉을 자리가 없을 때는 이 변화가 유일하게 쓸모 있는 정보다."""
    before = verdict_of({"4-2B": [T, T, F, F, F]}, status=STANDING, sellable_seg_idx=0)
    after = verdict_of({"4-2B": [T, F, F, F, F]}, status=STANDING, sellable_seg_idx=0)
    assert before.move_to == [] and after.move_to == []
    assert verdict_hash(before) != verdict_hash(after)


def test_전량_매진이면_여전히_ALL_SOLD다():
    seats = {"4-1B": [T, T, T, T, T], "3-9A": [T, T, T, T, T]}
    v = verdict_of(seats, status=STANDING, sellable_seg_idx=0)
    assert v.move_to_later == []
    decision = evaluate(
        verdict=v, ctx=ctx(seated=False), my_seat_cells=None,
        prev_cells=None, prev_hash="something-else",
    )
    assert decision.alert.kind is AlertKind.ALL_SOLD


# ── 판단할 것이 없을 때는 베이스라인까지 침묵한다 (→ D-47) ────────────
def test_마지막_구간을_달리는_중에는_알림이_나가지_않는다():
    """★ 회귀 방어. 팔 수 있는 구간이 없으면 취할 행동도 없다 (→ D-47).

    특히 **베이스라인(D-20)도 예외가 아니다** — 첫 폴링이 하필 이 시점이면
    "잔여 좌석 없음 · 지하철 환승 고려"가 하차 직전에 나간다. 생존 확인이라는
    베이스라인의 목적이 오히려 오정보를 만드는 유일한 구간이다.
    """
    v = build_verdict(
        matrix=make_matrix({}, queried_from_idx=5, queried_to_idx=5),
        status=SEATED,
        board_idx=0,
        alight_idx=5,
        sellable_seg_idx=5,
        my_car=MY_CAR,
        my_seat_no=MY_SEAT,
    )
    assert v.decision_needed is False

    for prev_hash in (None, "something-else"):
        decision = evaluate(
            verdict=v, ctx=ctx(), my_seat_cells=None,
            prev_cells=[F, F, F, F, F], prev_hash=prev_hash,
        )
        assert decision.alert is None, f"판단할 것이 없는데 알림이 나갔다 (prev_hash={prev_hash})"
        assert decision.verdict_hash, "해시는 기록해야 다음 조회가 변화로 오해하지 않는다"
