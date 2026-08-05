"""역 목록 (PLAN.md 7절, D-25).

출발/도착역 드롭다운의 소스. 역 이름을 타이핑시키면 오타가 곧 404다.

소스는 **`station` 테이블**(공공데이터 CSV 적재, `scripts/load_stations.py`)이다.
비어 있으면 Mock 어댑터 노선으로 폴백한다 — 테이블을 아직 적재하지 않은 개발
환경에서 화면이 통째로 죽지 않게 하기 위한 것이고, `ADAPTER=mock` 개발 흐름도
그대로 유지된다 (CLAUDE.md 10: 개발 중에는 실 API를 쓰지 않는다).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from app.adapters.korail_port import KorailPort
from app.api.deps import get_korail_port
from app.auth.session import current_user
from app.domain.models import StationInfo, User
from app.storage import stations as station_repo
from app.storage.db import db_session

router = APIRouter(prefix="/api/stations", tags=["stations"])


@router.get("", response_model=list[StationInfo])
async def list_stations(
    user: User = Depends(current_user),
    port: KorailPort = Depends(get_korail_port),
    conn: sqlite3.Connection = Depends(db_session),
) -> list[StationInfo]:
    if rows := station_repo.list_all(conn):
        return rows
    return await port.list_stations()
