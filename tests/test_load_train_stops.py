"""scripts/load_train_stops.py — 순수 변환 로직만 테스트한다 (네트워크 없음).

`to_stop_rows`가 원시 API 행(dict)을 열차번호별 `StopRow` 목록으로 묶는 부분이
핵심이다. 실제 호출(`fetch_day`)은 스모크 대상이 아니다 — 다른 로더들과 동일하게
여기서는 파싱만 검증한다.
"""

from __future__ import annotations

import importlib.util
from datetime import date as _date

RUN_YMD = _date(2026, 8, 4)


def _loader():
    spec = importlib.util.spec_from_file_location(
        "load_train_stops", "scripts/load_train_stops.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RAW_ROWS = [
    {
        "trn_no": "01472",
        "trn_run_sn": "1",
        "stn_cd": "3900061",
        "stn_nm": "천안",
        "stop_se_nm": "시발",
        "trn_arvl_dt": None,
        "trn_dptre_dt": "2026-08-04 07:39:00.0",
    },
    {
        "trn_no": "01472",
        "trn_run_sn": "3",  # 일부러 순서를 흩어놓는다
        "stn_cd": "3900025",
        "stn_nm": "용산",
        "stop_se_nm": "종착",
        "trn_arvl_dt": "2026-08-04 08:54:00.0",
        "trn_dptre_dt": None,
    },
    {
        "trn_no": "01472",
        "trn_run_sn": "2",
        "stn_cd": "3900057",
        "stn_nm": "평택역",  # '~역' 접미 — 정규화 대상
        "stop_se_nm": "여객승하차",
        "trn_arvl_dt": "2026-08-04 07:51:00.0",
        "trn_dptre_dt": "2026-08-04 07:53:00.0",
    },
    {
        "trn_no": "00476",
        "trn_run_sn": "1",
        "stn_cd": "3900211",
        "stn_nm": "익산",
        "stop_se_nm": "시발",
        "trn_arvl_dt": None,
        "trn_dptre_dt": "2026-08-04 05:30:00.0",
    },
]


def test_parse_dt_handles_fractional_seconds_and_null() -> None:
    mod = _loader()
    dt = mod._parse_dt("2026-08-04 07:39:00.0")
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 8, 4, 7, 39)
    assert dt.tzinfo is not None  # KST aware (절대규칙 1)
    assert mod._parse_dt(None) is None
    assert mod._parse_dt("None") is None


def test_to_stop_rows_groups_by_train_no() -> None:
    mod = _loader()
    grouped = mod.to_stop_rows(RAW_ROWS, RUN_YMD)
    assert set(grouped.keys()) == {"01472", "00476"}
    assert len(grouped["01472"]) == 3
    assert len(grouped["00476"]) == 1


def test_to_stop_rows_sorts_by_sequence() -> None:
    """★ 원본 순서가 흐트러져 있어도 trn_run_sn 기준으로 정렬돼야 한다."""
    mod = _loader()
    grouped = mod.to_stop_rows(RAW_ROWS, RUN_YMD)
    names = [r.station_name for r in grouped["01472"]]
    assert names == ["천안", "평택", "용산"]  # 순번 1,2,3 순서


def test_to_stop_rows_normalizes_station_names() -> None:
    """★ '평택역' → '평택'. station 테이블과 조인하려면 정규화가 맞아야 한다."""
    mod = _loader()
    grouped = mod.to_stop_rows(RAW_ROWS, RUN_YMD)
    assert grouped["01472"][1].station_name == "평택"


def test_to_stop_rows_preserves_origin_and_terminus_semantics() -> None:
    mod = _loader()
    grouped = mod.to_stop_rows(RAW_ROWS, RUN_YMD)
    rows = grouped["01472"]
    assert rows[0].stop_type == "시발" and rows[0].arrival is None
    assert rows[-1].stop_type == "종착" and rows[-1].departure is None


def test_to_stop_rows_carries_run_ymd() -> None:
    mod = _loader()
    grouped = mod.to_stop_rows(RAW_ROWS, RUN_YMD)
    assert all(r.run_ymd == RUN_YMD for r in grouped["01472"])
