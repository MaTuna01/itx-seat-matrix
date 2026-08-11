"""프리셋 CRUD (PLAN.md 7절, 원칙 3).

자주 쓰는 구간/열차. **새 구간 지원 = 행 추가**이지 코드 수정이 아니다 (원칙 1·3).
프론트에는 "즐겨찾기 노선"으로 노출되고 계정당 상한이 있다 (D-56).
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import now_kst
from app.auth.session import current_user
from app.domain.models import User
from app.storage.db import db_session, to_db

router = APIRouter(prefix="/api/presets", tags=["presets"])

# 계정당 즐겨찾기 노선 상한 (D-56). 조정 예정 값 — 로직에 인라인하지 않는다 (D-17).
MAX_PRESETS_PER_USER = 5


def can_add_preset(current_count: int, *, limit: int = MAX_PRESETS_PER_USER) -> bool:
    """즐겨찾기 노선을 더 저장할 수 있는가. 최종 방어선은 서버의 이 판정이다 —
    프론트가 저장 버튼을 감추더라도 초과 요청은 여기서 409로 거절된다."""
    return current_count < limit


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    from_station: str
    to_station: str
    usual_train_nos: list[str] = Field(default_factory=list)
    poll_offsets_min: list[int] = Field(default_factory=lambda: [10, 4])


class PresetOut(PresetIn):
    id: int


def _row_to_out(row: sqlite3.Row) -> PresetOut:
    return PresetOut(
        id=row["id"],
        name=row["name"],
        from_station=row["from_station"],
        to_station=row["to_station"],
        usual_train_nos=json.loads(row["usual_train_nos"]),
        poll_offsets_min=json.loads(row["poll_offsets_min"]),
    )


@router.get("", response_model=list[PresetOut])
def list_presets(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> list[PresetOut]:
    rows = conn.execute(
        "SELECT * FROM preset WHERE user_id = ? ORDER BY id", (user.id,)
    ).fetchall()
    return [_row_to_out(row) for row in rows]


@router.post("", response_model=PresetOut, status_code=status.HTTP_201_CREATED)
def create_preset(
    payload: PresetIn,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> PresetOut:
    count = conn.execute(
        "SELECT COUNT(*) FROM preset WHERE user_id = ?", (user.id,)
    ).fetchone()[0]
    if not can_add_preset(count):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"즐겨찾기 노선은 계정당 최대 {MAX_PRESETS_PER_USER}개까지 저장할 수 있습니다",
        )
    cur = conn.execute(
        "INSERT INTO preset"
        " (user_id, name, from_station, to_station, usual_train_nos, poll_offsets_min, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            user.id,
            payload.name,
            payload.from_station,
            payload.to_station,
            json.dumps(payload.usual_train_nos, ensure_ascii=False),
            json.dumps(payload.poll_offsets_min),
            to_db(now_kst()),
        ),
    )
    row = conn.execute("SELECT * FROM preset WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_out(row)


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(
    preset_id: int,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> Response:
    cur = conn.execute(
        "DELETE FROM preset WHERE id = ? AND user_id = ?", (preset_id, user.id)
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
