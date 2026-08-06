"""매진 판정 (D-36 / D-36 후속).

코레일 FAIL 응답을 '조회 실패'가 아니라 '전 좌석 판매됨'으로 흡수하는 판정이다.
놓치면 앞 구간에서 이미 받아온 좌석표까지 통째로 버려진다 (이슈 #9).
"""

from app.adapters.korail_client import (
    SOLD_OUT_CODES,
    looks_sold_out,
)


def test_실측_코드로_매진을_판정한다() -> None:
    """배포 첫날 EC2 로그에서 확보한 실측값 (수원→영등포, 2026-08-06)."""
    assert "ERI411321" in SOLD_OUT_CODES
    assert looks_sold_out("ERI411321", "잔여석이 없습니다.")


def test_코드가_등재되면_문구가_바뀌어도_잡는다() -> None:
    """코드 등재의 목적이 이것이다 — 코레일이 문구를 바꿔도 견딘다."""
    assert looks_sold_out("ERI411321", "예상치 못한 다른 안내 문구")


def test_코드를_모르면_문구로_판정한다() -> None:
    """표본이 좁아 문구 매칭을 남겨둔다 (D-36)."""
    assert looks_sold_out("UNKNOWN9999", "잔여석이 없습니다.")
    assert looks_sold_out("UNKNOWN9999", "해당 열차는 매진되었습니다")


def test_매진이_아닌_실패는_매진으로_보지_않는다() -> None:
    """세션 만료·안티봇 차단이 매진으로 흡수되면 조용히 틀린다."""
    assert not looks_sold_out("MACRO ERROR", "비정상적인 접근입니다")
    assert not looks_sold_out("P058", "로그인 후 이용하세요")
