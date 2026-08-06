"""프리셋 CRUD (PLAN.md 7절, 원칙 3).

자주 쓰는 구간/열차. **새 구간 지원 = 행 추가**이지 코드 수정이 아니다 (원칙 1·3).
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
