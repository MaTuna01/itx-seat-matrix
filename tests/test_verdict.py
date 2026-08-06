"""판정 로직 (PLAN 13절 — STANDING/SEATED 양쪽 + 내 좌석 부재 규칙 + 실효 시작).

**틀려도 조용히 틀리는 유일한 지점**이라 여기가 가장 촘촘해야 한다.
셀 값은 프로토타입과 같은 의미다: True = 판매됨, False = 빈자리.
구간 인덱스: 0 천안→평택 / 1 평택→수원 / 2 수원→안양 / 3 안양→영등포 / 4 영등포→서울
"""

from __future__ import annotations

from app.domain.models import SubscriptionStatus
from app.domain.verdict import RankingConfig, build_verdict, clear_until
from tests.conftest import make_matrix

SEATED = SubscriptionStatus.SEATED
STANDING = SubscriptionStatus.STANDING

F, T = False, True  # 빈자리 / 판매


class TestClearUntil:
    def test_연속으로_빈_마지막_역_인덱스(self):
        assert clear_until([F, F, F, T, F], 0, 5) == 3

    def test_시작_구간이_판매면_시작_인덱스_그대로(self):
        assert clear_until([T, F, F, F, F], 0, 5) == 0

    def test_하차역까지_비면_하차_인덱스(self):
        assert clear_until([F, F, F, F, F], 0, 5) == 5

    def test_하차역_이후는_보지_않는다(self):
        # 안양(3)에서 내리면 그 뒤 구간의 판매 여부는 무관하다
        assert clear_until([F, F, F, T, T], 0, 3) == 3


class TestSeated:
    def test_하차역까지_안전하면_CLEAR_ALL(self):
        matrix = make_matrix({"3-7A": [F, F, F, F, F], "4-1B": [T, T, T, T, T]})
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=0, alight_idx=5,
            current_seg_idx=0, my_car=3, my_seat_no="7A",
        )
        assert v.my_seat_status == "CLEAR_ALL"
        assert v.my_seat_sold_from is None
        assert v.my_seat_clear_until_idx == 5

    def test_중간부터_판매되면_SOLD_FROM_과_역_이름(self):
        # 수원(idx 2)부터 판매 → "수원부터 판매됨"
        matrix = make_matrix({"3-7A": [F, F, T, T, T]})
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=0, alight_idx=5,
            current_seg_idx=0, my_car=3, my_seat_no="7A",
        )
        assert v.my_seat_status == "SOLD_FROM"
        assert v.my_seat_sold_from == "수원"
        assert v.my_seat_clear_until_idx == 2

    def test_내_좌석이_매트릭스에_없으면_잔여_전_구간_판매로_본다(self):
        """D-18 내 좌석 부재 규칙. 이게 없으면 KeyError 아니면 UNKNOWN으로 조용히 빠진다."""
        matrix = make_matrix({"4-1B": [F, F, F, F, F]})
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=0, alight_idx=5,
            current_seg_idx=1, my_car=3, my_seat_no="7A",
        )
        assert v.my_seat_status == "SOLD_FROM"
        assert v.my_seat_sold_from == "수원"  # 다음 정차역 (실효 시작 1 → stops[2])
        assert v.my_seat_clear_until_idx == 1

    def test_좌석_정보가_없는_SEATED는_UNKNOWN(self):
        matrix = make_matrix({"4-1B": [F, F, F, F, F]})
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=0, alight_idx=5, current_seg_idx=0
        )
        assert v.my_seat_status == "UNKNOWN"

    def test_추천에서_내_자리는_빠진다(self):
        matrix = make_matrix({"3-7A": [F, F, F, F, F], "4-1B": [F, F, F, F, F]})
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=0, alight_idx=5,
            current_seg_idx=0, my_car=3, my_seat_no="7A",
        )
        assert [r.key for r in v.move_to] == ["4-1B"]

    def test_동률이면_내_호차에_가까운_좌석을_먼저_추천한다(self):
        matrix = make_matrix(
            {
                "3-7A": [T, T, T, T, T],  # 내 자리 (전 구간 판매)
                "8-1A": [F, F, F, F, F],
                "4-1A": [F, F, F, F, F],
                "5-1A": [F, F, F, F, F],
            }
        )
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=0, alight_idx=5,
            current_seg_idx=0, my_car=3, my_seat_no="7A",
        )
        assert [r.key for r in v.move_to] == ["4-1A", "5-1A", "8-1A"]


class TestStanding:
    def test_내_좌석_필드는_비어있다(self):
        matrix = make_matrix({"4-1B": [F, F, F, F, F]})
        v = build_verdict(
            matrix=matrix, status=STANDING, board_idx=0, alight_idx=5, current_seg_idx=0
        )
        assert v.my_seat_status is None
        assert v.my_seat_sold_from is None
        assert v.my_seat_clear_until_idx is None

    def test_clear_until_내림차순으로_추천한다(self):
        matrix = make_matrix(
            {
                "3-5A": [F, T, T, T, T],  # 평택까지
                "3-6A": [F, F, F, T, T],  # 안양까지
                "4-1B": [F, F, T, T, T],  # 수원까지
            }
        )
        v = build_verdict(
            matrix=matrix, status=STANDING, board_idx=0, alight_idx=5, current_seg_idx=0
        )
        assert [r.key for r in v.move_to] == ["3-6A", "4-1B", "3-5A"]
        assert all(r.clear_all is False for r in v.move_to)

    def test_clear_all_좌석이_있으면_그것만_추천한다(self):
        matrix = make_matrix({"3-6A": [F, F, F, T, T], "4-1B": [F, F, F, F, F]})
        v = build_verdict(
            matrix=matrix, status=STANDING, board_idx=0, alight_idx=5, current_seg_idx=0
        )
        assert [r.key for r in v.move_to] == ["4-1B"]
        assert v.move_to[0].clear_all is True

    def test_추천_상한은_설정값이다(self):
        matrix = make_matrix({f"3-{i}A": [F, F, F, F, F] for i in range(1, 6)})
        v = build_verdict(
            matrix=matrix, status=STANDING, board_idx=0, alight_idx=5, current_seg_idx=0,
            config=RankingConfig(max_recommendations=2),
        )
        assert len(v.move_to) == 2


class TestEffectiveStart:
    def test_실효_시작은_max_현재구간_탑승역(self):
        """D-18: 탑승역 이전 구간은 열차가 어디를 달리든 관심 밖."""
        # 천안~평택(0)에서 이미 판매됐지만 나는 수원(2)에서 탄다 → 판정에 영향 없음
        matrix = make_matrix({"3-7A": [T, T, F, F, F]})
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=2, alight_idx=5,
            current_seg_idx=0, my_car=3, my_seat_no="7A",
        )
        assert v.current_seg_idx == 2
        assert v.my_seat_status == "CLEAR_ALL"

    def test_열차가_탑승역을_지났으면_현재_구간이_시작(self):
        matrix = make_matrix({"3-7A": [F, F, T, F, F]})
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=0, alight_idx=5,
            current_seg_idx=3, my_car=3, my_seat_no="7A",
        )
        # 이미 지나온 수원→안양(2) 판매는 무관, 안양(3)부터 서울까지 빈자리
        assert v.current_seg_idx == 3
        assert v.my_seat_status == "CLEAR_ALL"

    def test_지나온_구간_추천은_하지_않는다(self):
        matrix = make_matrix({"4-1B": [F, F, T, T, T], "3-7A": [T, T, T, T, T]})
        v = build_verdict(
            matrix=matrix, status=SEATED, board_idx=0, alight_idx=5,
            current_seg_idx=2, my_car=3, my_seat_no="7A",
        )
        # 4-1B는 수원까지만 비어 있었다 → 수원 이후로는 추천 대상이 아니다
        assert v.move_to == []
        assert v.all_sold_after_current is True


def test_남은_전_구간_매진이면_환승_판단_플래그():
    matrix = make_matrix({"3-7A": [F, T, T, T, T], "4-1B": [F, T, T, T, T]})
    v = build_verdict(
        matrix=matrix, status=STANDING, board_idx=0, alight_idx=5, current_seg_idx=1
    )
    assert v.all_sold_after_current is True
    assert v.move_to == []


def test_내_자리가_남아있으면_매진이_아니다():
    matrix = make_matrix({"3-7A": [F, F, F, F, F], "4-1B": [T, T, T, T, T]})
    v = build_verdict(
        matrix=matrix, status=SEATED, board_idx=0, alight_idx=5,
        current_seg_idx=0, my_car=3, my_seat_no="7A",
    )
    assert v.all_sold_after_current is False
    assert v.move_to == []  # 옮길 곳은 없지만 옮길 필요도 없다
