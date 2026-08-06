"""DelayPort — 열차 지연 정보 (PLAN.md 5절, D-12).

소스가 미확정이므로 기본 구현은 "지연 0"이다. Phase 0 항목 4에서 korail2 응답에
지연 필드(`h_expct_dlay_hr`, **6자리 포맷** — 4자리 hhmm 아님)가 실재함을 확인했으므로
Phase 2에서 실구현으로 교체한다.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Protocol, runtime_checkable


@runtime_checkable
class DelayPort(Protocol):
    async def get_delay_minutes(self, train_no: str, d: _date) -> int | None:
        """현재 지연 분. None = 정보 없음(지연 0으로 간주)."""
        ...
