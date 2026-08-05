"""API 공통 의존성 — 어댑터 선택 + 현재 시각.

어댑터 전환은 env `ADAPTER=mock|korail2` (PLAN 11절). Phase 1은 mock만 존재한다.
"""

from __future__ import annotations

from datetime import datetime

from app.adapters.delay_zero import ZeroDelayAdapter
from app.adapters.korail_mock import MockKorailAdapter
from app.adapters.korail_port import KorailPort
from app.config import get_settings
from app.domain.models import KST

_mock_korail = MockKorailAdapter()
_zero_delay = ZeroDelayAdapter()


def get_korail_port() -> KorailPort:
    settings = get_settings()
    if settings.adapter == "korail2":
        # Phase 2에서 Korail2Adapter(+ DynaPath 우회 벤더링, D-22)를 붙인다.
        raise NotImplementedError("korail2 어댑터는 Phase 2에서 구현한다 (ADAPTER=mock을 쓸 것)")
    return _mock_korail


def get_delay_port() -> ZeroDelayAdapter:
    """Phase 2에서 실구현으로 교체 (D-12). 그때까지는 항상 지연 0."""
    return _zero_delay


def now_kst() -> datetime:
    """요청 처리 시각. 도메인 함수에는 항상 인자로 주입해 내려보낸다 (D-21)."""
    return datetime.now(KST)
