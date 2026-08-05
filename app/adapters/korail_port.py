"""KorailPort — 코레일 비공식 API 경계 (PLAN.md 5절, 원칙 2).

**언제 깨져도 이상하지 않은 가장 취약한 지점**이므로 전부 이 인터페이스 뒤에 둔다.
Phase 1은 `MockKorailAdapter`만 사용한다. Phase 2에서 korail2 어댑터
(+ DynaPath 우회 벤더링, D-22)를 같은 인터페이스로 추가한다.

인터페이스는 **async를 유지한다.** korail2는 동기 라이브러리이므로
`asyncio.to_thread`로 감싸는 것은 어댑터 '내부'의 책임이다 (D-21).
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.models import KorailCred, SeatMap, StopInfo, TrainSummary


@runtime_checkable
class KorailPort(Protocol):
    async def search_trains(
        self,
        cred: KorailCred | None,
        d: _date,
        frm: str,
        to: str,
        at: datetime | None = None,
    ) -> list[TrainSummary]:
        """열차 목록 (열차번호 선택용). `GET /api/trains/search` 뒷단."""
        ...

    async def get_stops(self, cred: KorailCred | None, train_no: str, d: _date) -> list[StopInfo]:
        """전체 노선의 정차역 + 역별 도착시각 (순서 보장, D-18).

        주의: Phase 0 항목 5 = **NO** — 열차번호로 전체 정차역을 주는 코레일
        엔드포인트는 없다. Phase 2 실구현에서는 외부 소스(공공데이터포털 등)가
        필요하다. Mock은 이 제약과 무관하게 전체 노선을 반환한다.
        """
        ...

    async def get_seat_map(
        self, cred: KorailCred | None, train_no: str, d: _date, frm: str, to: str
    ) -> SeatMap:
        """특정 **인접 구간**의 좌석별 판매 여부.

        Phase 0 항목 6 = 전체 좌석+상태 → 병합은 단순 조인 (D-22).
        """
        ...
