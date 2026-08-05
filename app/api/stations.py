"""역 목록 (PLAN.md 7절, D-25).

출발/도착역 드롭다운의 소스. 역 이름을 타이핑시키면 오타가 곧 404다.
Phase 1의 소스는 Mock 노선이고, Phase 2에서 `station` 테이블(공공데이터)로 갈아끼운다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.adapters.korail_port import KorailPort
from app.api.deps import get_korail_port
from app.auth.session import current_user
from app.domain.models import StationInfo, User

router = APIRouter(prefix="/api/stations", tags=["stations"])


@router.get("", response_model=list[StationInfo])
async def list_stations(
    user: User = Depends(current_user),
    port: KorailPort = Depends(get_korail_port),
) -> list[StationInfo]:
    return await port.list_stations()
