"""DynaPath 우회 벤더링 스모크 (PLAN 13절 — 어댑터는 스모크로 충분).

**여기서 검증할 수 없는 것**: 생성된 토큰을 코레일이 실제로 받아주는지.
그건 실호출로만 확인되며 `ADAPTER=korail2` 실연동 검증의 몫이다.
여기서는 이식이 구조적으로 깨지지 않았는지를 본다.

익명 전환(D-60) 이후 이 모듈이 하는 일은 **토큰 헤더 부착 하나**다. `Sid`·로그인
`Version` 덮어쓰기·GET→POST 전환은 전부 로그인 경로 전용이라 함께 사라졌다 —
그래서 그 세 가지를 지키던 테스트도 없다. 대신 **research.* 에 토큰이 붙는지**가
새 관문이다 (익명 경로에서는 토큰이 곧 통행증이다).
"""

from __future__ import annotations

import pytest

from app.adapters.korail_dynapath import (
    DYNAPATH_PATHS,
    DynaPathSession,
    _DynaPathTokenEngine,
)

FIXED_TS = 1_754_300_000_000
FIXED_RAND = "AB12"
FIXED_START = "1754299999000"
DEVICE_ID = "558a4f02041657ea"


@pytest.fixture
def engine() -> _DynaPathTokenEngine:
    return _DynaPathTokenEngine(app_start_ts=FIXED_START)


# ── 토큰 생성 ────────────────────────────────────────────────────────────
def test_token_is_deterministic_for_fixed_inputs(engine: _DynaPathTokenEngine) -> None:
    a = engine.generate_token(DEVICE_ID, FIXED_TS, FIXED_RAND)
    b = engine.generate_token(DEVICE_ID, FIXED_TS, FIXED_RAND)
    assert a == b


def test_token_has_expected_prefix_and_charset(engine: _DynaPathTokenEngine) -> None:
    token = engine.generate_token(DEVICE_ID, FIXED_TS, FIXED_RAND)
    assert token.startswith("bEeEP")
    # 접두사 뒤는 전부 TABLE 문자여야 한다 (인코딩 산출이므로)
    assert set(token[5:]) <= set(_DynaPathTokenEngine.TABLE)


def test_token_varies_with_ts_and_rand(engine: _DynaPathTokenEngine) -> None:
    base = engine.generate_token(DEVICE_ID, FIXED_TS, FIXED_RAND)
    assert engine.generate_token(DEVICE_ID, FIXED_TS + 1, FIXED_RAND) != base
    assert engine.generate_token(DEVICE_ID, FIXED_TS, "ZZ99") != base


def test_custom_table_has_distinct_chars(engine: _DynaPathTokenEngine) -> None:
    """`make_encode_table`은 '아직 안 쓴 문자'만 고르므로 중복이 없어야 한다.

    중복이 나오면 `_internal_i`의 `current_sb` 판정이 깨진 것 — 이식 사고의 신호.
    """
    big_key = engine.make_key(f"v1+{FIXED_RAND}+{FIXED_TS}")
    table = engine.make_encode_table(big_key, engine.I9, engine.TABLE)
    assert len(table) == engine.I9
    assert len(set(table)) == engine.I9
    assert set(table) <= set(engine.TABLE)


def test_encode_normal_be_length_formula(engine: _DynaPathTokenEngine) -> None:
    """i10=2 기준: 2바이트마다 3문자, 나머지 1바이트면 2문자."""
    for text, expected in [("ab", 3), ("abcd", 6), ("abc", 5), ("a", 2)]:
        assert len(engine.encode_normal_be(text, engine.TABLE)) == expected


# ── 세션: 토큰 부착이 HTTP 계층에서 적용되는가 ───────────────────────────
class _Captured(Exception):
    """super().request()까지 도달한 인자를 잡아 네트워크로 나가기 전에 멈춘다."""

    def __init__(self, method: str, url: str, kwargs: dict) -> None:
        self.method, self.url, self.kwargs = method, url, kwargs


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> DynaPathSession:
    import requests

    def fake_request(self, method, url, *args, **kwargs):  # noqa: ANN001, ANN202
        raise _Captured(method, url, kwargs)

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return DynaPathSession()


SCHEDULE_URL = "https://smart.letskorail.com:443/classes/com.korail.mobile.seatMovie.ScheduleView"
CARS_URL = "https://smart.letskorail.com:443/classes/com.korail.mobile.research.TrainResearch"
SEATS_URL = (
    "https://smart.letskorail.com:443/classes/com.korail.mobile.research.ResidualSeatsResearch.do"
)
TICKETS_URL = "https://smart.letskorail.com:443/classes/com.korail.mobile.myTicket.MyTicketList"


def _capture(session: DynaPathSession, method: str, url: str, **kwargs) -> _Captured:
    with pytest.raises(_Captured) as exc:
        session.request(method, url, **kwargs)
    return exc.value


@pytest.mark.parametrize("url", [SCHEDULE_URL, CARS_URL, SEATS_URL])
def test_all_three_queries_get_the_token(session: DynaPathSession, url: str) -> None:
    """익명 경로에서는 토큰이 곧 통행증이다 — 조회 3종 전부에 붙어야 한다 (D-60)."""
    cap = _capture(session, "POST", url, data={"Device": "AD"})
    assert cap.kwargs["headers"]["x-dynapath-m-token"].startswith("bEeEP")


def test_sid_is_never_sent(session: DynaPathSession) -> None:
    """익명 경로는 `Sid`를 요구하지 않는다. 본문에도 쿼리에도 섞이면 안 된다.

    로그인 시절의 잔재가 되살아나면 인증 경로처럼 보여 다시 막힐 수 있다 (D-60).
    """
    cap = _capture(session, "POST", SCHEDULE_URL, params={"Device": "AD"}, data=None)
    assert "Sid" not in (cap.kwargs.get("params") or {})
    assert not (cap.kwargs.get("data") or {})


def test_method_is_passed_through(session: DynaPathSession) -> None:
    """GET→POST 전환은 사라졌다 — 호출부가 명시한 메서드가 그대로 나가야 한다."""
    assert _capture(session, "GET", SCHEDULE_URL).method == "GET"
    assert _capture(session, "POST", SCHEDULE_URL).method == "POST"


def test_non_dynapath_path_gets_no_token(session: DynaPathSession) -> None:
    """목록 밖 경로에는 헤더를 흘리지 않는다."""
    cap = _capture(session, "GET", TICKETS_URL, data={"Device": "AD"})
    assert "x-dynapath-m-token" not in (cap.kwargs.get("headers") or {})


def test_seatmap_endpoints_are_in_dynapath_paths() -> None:
    """D-60 이전에는 반대였다 (`research.*`는 인증 세션으로만 갔다).

    익명 전환으로 뒤집혔다. 이 목록에서 빠지면 2·3단계가 조용히 토큰 없이 나간다.
    """
    assert any("research.TrainResearch" in p for p in DYNAPATH_PATHS)
    assert any("research.ResidualSeatsResearch" in p for p in DYNAPATH_PATHS)


def test_user_agent_is_the_updated_one(session: DynaPathSession) -> None:
    assert "SM-S928N" in session.headers["User-Agent"]
