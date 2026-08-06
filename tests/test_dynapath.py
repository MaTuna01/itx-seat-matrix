"""DynaPath 우회 벤더링 스모크 (PLAN 13절 — 어댑터는 스모크로 충분).

**여기서 검증할 수 없는 것**: 생성된 토큰을 코레일이 실제로 받아주는지.
그건 실호출로만 확인되며 `ADAPTER=korail2` 실연동 검증의 몫이다.
여기서는 이식이 구조적으로 깨지지 않았는지와, pycryptodome → cryptography
치환이 **바이트 동일**한지를 본다 (후자는 순환 논리가 아닌 실제 검증이다).
"""

from __future__ import annotations

import base64

import pytest

from app.adapters.korail_dynapath import (
    APP_VERSION,
    DYNAPATH_PATHS,
    DynaPathSession,
    _DynaPathTokenEngine,
    _generate_sid,
)

FIXED_TS = 1_754_300_000_000
FIXED_RAND = "AB12"
FIXED_START = "1754299999000"
DEVICE_ID = "558a4f02041657ea"


@pytest.fixture
def engine() -> _DynaPathTokenEngine:
    return _DynaPathTokenEngine(app_start_ts=FIXED_START)


# ── Sid: 원본(pycryptodome)과 바이트 동일한가 ────────────────────────────
def test_sid_matches_pycryptodome_reference() -> None:
    """원본은 `Crypto.Cipher.AES`를 쓴다. 우리는 `cryptography`로 바꿨다.

    korail2가 pycryptodome을 끌고 오므로 여기서 원본 구현을 직접 돌려 대조할 수 있다.
    두 산출이 다르면 우회가 조용히 깨진다 — 실호출 전에 잡아야 하는 지점.
    """
    from Crypto.Cipher import AES  # noqa: PLC0415 — 대조용 (전이 의존, 런타임 코드는 안 쓴다)
    from Crypto.Util.Padding import pad  # noqa: PLC0415

    key = b"2485dd54d9deaa36"
    plaintext = f"AD{FIXED_TS}".encode()
    cipher = AES.new(key, AES.MODE_CBC, iv=key)
    expected = base64.b64encode(cipher.encrypt(pad(plaintext, 16))).decode() + "\n"

    assert _generate_sid(FIXED_TS) == expected


def test_sid_is_base64_with_trailing_newline() -> None:
    sid = _generate_sid(FIXED_TS)
    assert sid.endswith("\n")
    raw = base64.b64decode(sid.strip())
    assert len(raw) % 16 == 0  # AES 블록 배수


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


# ── 세션: 4가지 변경이 HTTP 계층에서 적용되는가 ──────────────────────────
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


LOGIN_URL = "https://smart.letskorail.com:443/classes/com.korail.mobile.login.Login"
SCHEDULE_URL = "https://smart.letskorail.com:443/classes/com.korail.mobile.seatMovie.ScheduleView"
TICKETS_URL = "https://smart.letskorail.com:443/classes/com.korail.mobile.myTicket.MyTicketList"


def _capture(session: DynaPathSession, method: str, url: str, **kwargs) -> _Captured:
    with pytest.raises(_Captured) as exc:
        session.request(method, url, **kwargs)
    return exc.value


def test_dynapath_path_gets_token_header_and_sid(session: DynaPathSession) -> None:
    cap = _capture(session, "POST", LOGIN_URL, data={"Device": "AD", "Version": "231231001"})
    assert cap.kwargs["headers"]["x-dynapath-m-token"].startswith("bEeEP")
    assert cap.kwargs["data"]["Sid"].endswith("\n")


def test_login_hardcoded_version_is_overridden(session: DynaPathSession) -> None:
    """korail2 login()은 Version='231231001'을 하드코딩한다 (설치본 line 637)."""
    cap = _capture(session, "POST", LOGIN_URL, data={"Version": "231231001"})
    assert cap.kwargs["data"]["Version"] == APP_VERSION


def test_schedule_view_get_is_converted_to_post(session: DynaPathSession) -> None:
    """korail2 search_train()은 GET으로 부른다. 우회 후에는 POST여야 한다."""
    cap = _capture(session, "GET", SCHEDULE_URL, params={"Version": "190617001"})
    assert cap.method == "POST"
    assert cap.kwargs["params"]["Version"] == APP_VERSION  # params 쪽도 최신화


def test_non_dynapath_path_gets_no_token(session: DynaPathSession) -> None:
    """좌석맵(research.*)을 포함한 나머지 경로는 토큰 없이 인증 세션만으로 간다.

    Phase 0 실측 결과이자 DYNAPATH_PATHS 목록의 의미다 — 여기가 틀리면
    불필요한 헤더를 코레일에 흘리게 된다.
    """
    cap = _capture(session, "GET", TICKETS_URL, data={"Device": "AD"})
    assert "x-dynapath-m-token" not in (cap.kwargs.get("headers") or {})
    assert "Sid" not in cap.kwargs["data"]
    assert cap.method == "GET"


def test_seatmap_endpoints_are_not_in_dynapath_paths() -> None:
    for path in DYNAPATH_PATHS:
        assert "research" not in path


def test_user_agent_is_the_updated_one(session: DynaPathSession) -> None:
    assert "SM-S928N" in session.headers["User-Agent"]
