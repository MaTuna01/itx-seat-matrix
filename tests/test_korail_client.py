"""코레일 응답 정규화 (Phase 2 항목 E/F) — 순수 파서 단위 테스트.

네트워크는 타지 않는다. 픽스처는 Phase 0에서 실측한 응답 모양을 따른다
(`scripts/phase0_feasibility.py`의 summarize_* 참고).
"""

from __future__ import annotations

from datetime import date as _date

import pytest

from app.adapters.korail_client import (
    general_cars,
    parse_delay_minutes,
    parse_seat_states,
    parse_train_summary,
    same_train_no,
)
from app.domain.models import KST

RIDE_DATE = _date(2026, 8, 6)


# ── F. 지연 파싱 — 6자리 포맷 ────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("000000", 0),  # Phase 0 실측값 (무지연)
        ("001500", 15),
        ("000500", 5),
        ("010000", 60),
        ("012500", 85),
        ("000030", 1),  # 30초 이상은 올림
        ("000029", 0),
    ],
)
def test_parse_delay_minutes_six_digit(raw: str, expected: int) -> None:
    assert parse_delay_minutes(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "abc", "12ab56"])
def test_parse_delay_minutes_returns_none_for_junk(raw: str | None) -> None:
    """지연은 있으면 좋은 정보다 — 못 읽으면 예외가 아니라 None(지연 0)이다 (D-12)."""
    assert parse_delay_minutes(raw) is None


@pytest.mark.parametrize("raw", ["0015", "00150", "0001500"])
def test_parse_delay_minutes_rejects_non_six_digit(raw: str) -> None:
    """★ 4자리 hhmm으로 읽으면 조용히 틀린다 (korail2 주석이 그렇게 적혀 있다).

    포맷이 6자리가 아니면 스킴이 바뀐 것이므로, 추측해서 틀린 지연을 쓰느니
    모른다고 답한다.
    """
    assert parse_delay_minutes(raw) is None


# ── E. 좌석맵 정규화 ─────────────────────────────────────────────────────
def test_parse_seat_states_maps_sale_flag() -> None:
    """`h_sale_psb_flg='Y'`(판매가능) == 비어 있음 → sold=False."""
    seats = parse_seat_states(
        3,
        [
            {"h_con_seat_no": "5A", "h_sale_psb_flg": "Y"},
            {"h_con_seat_no": "5B", "h_sale_psb_flg": "N"},
        ],
    )
    assert [(s.car, s.seat_no, s.sold) for s in seats] == [
        (3, "5A", False),
        (3, "5B", True),
    ]


def test_parse_seat_states_drops_sentinel() -> None:
    """`'0A'`는 좌석이 아니라 자리표시자다 (Phase 0에서 걸러냈다)."""
    seats = parse_seat_states(
        1, [{"h_con_seat_no": "0A", "h_sale_psb_flg": "N"}, {"h_con_seat_no": "1A", "h_sale_psb_flg": "Y"}]
    )
    assert [s.seat_no for s in seats] == ["1A"]


def test_parse_seat_states_drops_blank_seat_no() -> None:
    seats = parse_seat_states(1, [{"h_con_seat_no": "", "h_sale_psb_flg": "Y"}, {}])
    assert seats == []


def test_parse_seat_states_treats_missing_flag_as_sold() -> None:
    """플래그가 없으면 **판매됨**으로 본다.

    안전한 방향은 이쪽이다 — 빈 자리라고 잘못 추천해 사람을 세워두는 것보다
    보수적으로 빼는 편이 낫다.
    """
    seats = parse_seat_states(2, [{"h_con_seat_no": "3A"}])
    assert seats[0].sold is True


def test_parse_seat_states_uses_given_car_number() -> None:
    seats = parse_seat_states(7, [{"h_con_seat_no": "1A", "h_sale_psb_flg": "Y"}])
    assert seats[0].car == 7
    assert seats[0].key == "7-1A"


# ── 호차 선별 ────────────────────────────────────────────────────────────
def test_general_cars_excludes_special_class() -> None:
    cars = general_cars(
        [
            {"h_srcar_no": "1", "h_psrm_cl_cd": "1"},
            {"h_srcar_no": "2", "h_psrm_cl_cd": "2"},  # 특실
            {"h_srcar_no": "3", "h_psrm_cl_cd": "1"},
        ]
    )
    assert [c["h_srcar_no"] for c in cars] == ["1", "3"]


# ── 열차 요약 ────────────────────────────────────────────────────────────
RAW_TRAIN = {
    "h_trn_no": "01472",
    "h_trn_clsf_nm": "무궁화호",
    "h_dpt_rs_stn_nm": "천안",
    "h_arv_rs_stn_nm": "영등포",
    "h_dpt_dt": "20260806",
    "h_dpt_tm": "180500",
    "h_arv_dt": "20260806",
    "h_arv_tm": "192300",
}


def test_parse_train_summary() -> None:
    summary = parse_train_summary(RAW_TRAIN, RIDE_DATE)
    assert summary is not None
    assert summary.train_no == "1472"  # 선행 0 제거
    assert summary.train_name == "무궁화호"
    assert summary.dep_station == "천안"
    assert summary.dep_time.tzinfo is not None
    assert summary.dep_time == summary.dep_time.astimezone(KST)
    assert (summary.dep_time.hour, summary.dep_time.minute) == (18, 5)
    assert (summary.arr_time.hour, summary.arr_time.minute) == (19, 23)


def test_parse_train_summary_returns_none_without_times() -> None:
    raw = dict(RAW_TRAIN)
    del raw["h_dpt_tm"]
    assert parse_train_summary(raw, RIDE_DATE) is None


def test_parse_train_summary_times_are_kst_aware() -> None:
    """naive datetime을 만들면 안 된다 (절대규칙 1)."""
    summary = parse_train_summary(RAW_TRAIN, RIDE_DATE)
    assert summary is not None
    assert summary.dep_time.utcoffset().total_seconds() == 9 * 3600


# ── 열차번호 비교 ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("01472", "1472", True), ("1472", "1472", True), ("1472", "1473", False), (None, "1", False)],
)
def test_same_train_no_ignores_leading_zeros(a, b, expected) -> None:  # noqa: ANN001
    """`'01472'`를 `'1472'`로 못 찾으면 열차가 조용히 사라진다."""
    assert same_train_no(a, b) is expected


# ── 매진 분류 (D-36) ─────────────────────────────────────────────────
import pytest as _pytest  # noqa: E402

from app.adapters.korail_client import (  # noqa: E402
    KorailApiError,
    KorailSoldOut,
    looks_sold_out,
)


@_pytest.mark.parametrize(
    "msg_cd,msg_txt,expected",
    [
        ("WRX", "잔여석이 없습니다", True),
        ("WRX", "매진되었습니다", True),
        ("WRX", "예약가능한 좌석이 없습니다", True),
        ("WRX", "잔여석 부족", True),
        # 매진과 무관한 실패는 그대로 에러여야 한다 — 삼키면 진짜 장애가 숨는다
        ("WRX", "시스템 점검 중입니다", False),
        ("WRX", "일시적인 오류가 발생했습니다", False),
        ("WRX", "", False),
    ],
)
def test_매진_문구를_분류한다(msg_cd, msg_txt, expected):
    """코드값이 확정되지 않아 문구로 판별한다. 놓치면 조회 전체가 실패한다 (D-36)."""
    assert looks_sold_out(msg_cd, msg_txt) is expected


def test_매진은_KorailApiError의_하위형이다():
    """기존 `except KorailApiError` 처리를 깨지 않으면서 따로 잡을 수 있어야 한다."""
    assert issubclass(KorailSoldOut, KorailApiError)
