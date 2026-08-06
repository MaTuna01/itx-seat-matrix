"""API 공통 의존성 — 어댑터 선택 + 현재 시각.

어댑터 전환은 env `ADAPTER=mock|korail2` (PLAN 11절). Phase 1은 mock만 존재한다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import Depends

from app.adapters.delay_zero import ZeroDelayAdapter
from app.adapters.korail_mock import MockKorailAdapter
from app.adapters.korail_port import KorailPort
from app.auth.session import current_user
from app.config import get_settings
from app.domain.models import KST, KorailCred, User
from app.storage.creds import load_korail_cred
from app.storage.db import db_session

_mock_korail = MockKorailAdapter()
_zero_delay = ZeroDelayAdapter()


def get_korail_port() -> KorailPort:
    settings = get_settings()
    if settings.adapter == "korail2":
        # 지연 import — mock 경로가 korail2 패키지에 의존하지 않게 한다.
        from app.adapters.korail2_adapter import get_korail2_adapter  # noqa: PLC0415

        return get_korail2_adapter()
    return _mock_korail


def get_korail_cred(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> KorailCred | None:
    """저장된 코레일 자격증명. 미등록이면 None (Mock 어댑터는 무시한다).

    복호화 결과이므로 **응답 모델에 절대 담지 마라** (절대규칙 9).
    """
    return load_korail_cred(conn, user.id)


def get_delay_port():  # noqa: ANN201 — DelayPort 구현체 (mock/korail2 분기)
    """지연 정보 (D-12). mock 경로는 항상 지연 0을 유지한다."""
    if get_settings().adapter == "korail2":
        from app.adapters.korail2_adapter import get_korail2_delay_adapter  # noqa: PLC0415

        return get_korail2_delay_adapter()
    return _zero_delay


def now_kst() -> datetime:
    """요청 처리 시각. 도메인 함수에는 항상 인자로 주입해 내려보낸다 (D-21)."""
    return datetime.now(KST)
