"""GET /api/me (PLAN.md 7절).

자격증명·웹훅 URL은 **절대 응답에 넣지 않는다.** "등록됨/미등록"만 노출한다
(CLAUDE.md 절대규칙 9). `PUT /api/me/korail`(Phase 2)·`/api/me/discord`(Phase 3)는
각 Phase에서 추가한다.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.session import current_user
from app.domain.models import User
from app.storage.db import db_session

router = APIRouter(prefix="/api/me", tags=["me"])


class MeOut(BaseModel):
    id: int
    email: str
    display_name: str
    korail_linked: bool
    discord_linked: bool
    discord_enabled: bool


@router.get("", response_model=MeOut)
def get_me(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> MeOut:
    row = conn.execute(
        "SELECT korail_id, korail_pw_enc, discord_webhook_enc, discord_enabled"
        " FROM user WHERE id = ?",
        (user.id,),
    ).fetchone()
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        korail_linked=bool(row["korail_id"] and row["korail_pw_enc"]),
        discord_linked=bool(row["discord_webhook_enc"]),
        discord_enabled=bool(row["discord_enabled"]),
    )
