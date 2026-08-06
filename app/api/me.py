"""GET /api/me + 코레일 계정 연결 (PLAN.md 7절).

자격증명·웹훅 URL은 **절대 응답에 넣지 않는다.** "등록됨/미등록"만 노출한다
(CLAUDE.md 절대규칙 9). `/api/me/discord`(Phase 3)는 그때 추가한다.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.session import current_user
from app.domain.models import KorailCred, User
from app.storage.creds import clear_korail_cred, save_korail_cred
from app.storage.db import db_session

router = APIRouter(prefix="/api/me", tags=["me"])


class MeOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool
    korail_linked: bool
    discord_linked: bool
    discord_enabled: bool


class KorailCredIn(BaseModel):
    """코레일 계정 연결 입력. **응답으로 되돌려주지 않는다.**"""

    korail_id: str = Field(min_length=1)
    korail_pw: str = Field(min_length=1)


@router.put("/korail", response_model=MeOut)
def put_korail(
    body: KorailCredIn,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> MeOut:
    """코레일 자격증명을 Fernet으로 암호화해 저장한다 (D-22).

    검증(실제 로그인 성공 여부)은 여기서 하지 않는다 — 저장 시점에 코레일을
    호출하면 화면 조작만으로 실 API를 때리게 되고, 호출 예절(CLAUDE.md 10)과
    어긋난다. 자격증명이 틀렸다는 사실은 첫 매트릭스 조회에서 드러난다.
    """
    try:
        save_korail_cred(conn, user.id, KorailCred(**body.model_dump()))
    except RuntimeError as exc:  # SECRET_KEY 미설정
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _me(conn, user)


@router.delete("/korail", response_model=MeOut)
def delete_korail(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> MeOut:
    clear_korail_cred(conn, user.id)
    return _me(conn, user)


@router.get("", response_model=MeOut)
def get_me(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> MeOut:
    return _me(conn, user)


def _me(conn: sqlite3.Connection, user: User) -> MeOut:
    row = conn.execute(
        "SELECT korail_id, korail_pw_enc, discord_webhook_enc, discord_enabled"
        " FROM user WHERE id = ?",
        (user.id,),
    ).fetchone()
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        korail_linked=bool(row["korail_id"] and row["korail_pw_enc"]),
        discord_linked=bool(row["discord_webhook_enc"]),
        discord_enabled=bool(row["discord_enabled"]),
    )
