"""ZeroDelayAdapter — 기본 DelayPort 구현 (D-12).

항상 None을 반환한다. 지연 정보를 못 얻어도 시스템은 그대로 동작한다(우아한 성능 저하).
정차역당 2회 조회(-10/-4분)가 흔한 지연을 보완한다.
"""

from __future__ import annotations

from datetime import date as _date


class ZeroDelayAdapter:
    async def get_delay_minutes(self, train_no: str, d: _date) -> int | None:
        return None
