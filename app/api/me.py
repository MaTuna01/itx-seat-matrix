"""GET /api/me + 코레일 계정 연결 + 디스코드 웹훅 (PLAN.md 7절, 8절).

자격증명·웹훅 URL은 **절대 응답에 넣지 않는다.** "등록됨/미등록"만 노출한다
(CLAUDE.md 절대규칙 9).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.adapters.discord_notifier import DiscordNotifier
from app.auth.session import current_user
from app.domain.models import KorailCred, User
from app.storage.creds import (
    clear_discord_webhook,
    clear_korail_cred,
    discord_linked,
    korail_linked,
    save_discord_webhook,
    save_korail_cred,
    set_discord_enabled,
)
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


class DiscordIn(BaseModel):
    """웹훅 URL. **응답으로 되돌려주지 않는다** — 사실상 자격증명이다 (8절)."""

    webhook_url: str = Field(min_length=1)


class DiscordToggleIn(BaseModel):
    enabled: bool


@router.put("/discord", response_model=MeOut)
async def put_discord(
    body: DiscordIn,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> MeOut:
    """웹훅 연동. **저장 시 즉시 테스트 메시지를 발송해 URL 유효성을 그 자리에서 검증한다** (8절).

    코레일 자격증명과 정반대 방침인데, 이유가 있다: 웹훅 POST는 사용자 소유 채널에
    글 한 줄을 쓰는 것이라 호출 예절(CLAUDE.md 10)이 걸리는 대상이 아니고,
    URL 오타를 여기서 못 잡으면 **알림이 필요한 순간에 조용히 아무 데도 안 간다.**

    검증 실패 시 저장하지 않는다 — "연동됨"이라고 표시된 채 발송이 안 되는 상태가
    가장 나쁘다. 토글은 건드리지 않는다 (opt-in 2단계, D-11).
    """
    result = await DiscordNotifier().post(
        body.webhook_url, "**ITX 좌석 매트릭스** 연동 완료 · 이 채널로 알림이 옵니다"
    )
    if not result.delivered:
        raise HTTPException(status_code=422, detail=" · ".join(result.errors) or "웹훅 발송 실패")
    save_discord_webhook(conn, user.id, body.webhook_url)
    return _me(conn, user)


@router.patch("/discord", response_model=MeOut)
def patch_discord(
    body: DiscordToggleIn,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> MeOut:
    """알림 on/off 토글. 연동 없이 켤 수 없다 — 켜진 채 보낼 곳이 없으면 상태가 거짓말을 한다."""
    row = conn.execute(
        "SELECT discord_webhook_enc FROM user WHERE id = ?", (user.id,)
    ).fetchone()
    if body.enabled and not row["discord_webhook_enc"]:
        raise HTTPException(status_code=422, detail="웹훅을 먼저 연동해 주세요")
    set_discord_enabled(conn, user.id, body.enabled)
    return _me(conn, user)


@router.delete("/discord", response_model=MeOut)
def delete_discord(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> MeOut:
    clear_discord_webhook(conn, user.id)
    return _me(conn, user)


@router.get("", response_model=MeOut)
def get_me(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> MeOut:
    return _me(conn, user)


def _me(conn: sqlite3.Connection, user: User) -> MeOut:
    """`*_linked`는 **복호화까지 되는지**로 판단한다 (storage/creds.korail_linked).

    행에 암호문이 있다는 것만 보면, `SECRET_KEY`가 어긋난 순간부터 화면은 "연결됨"인데
    조회는 계속 실패하는 상태가 된다 — 사용자가 원인을 짚을 방법이 없다.
    """
    row = conn.execute("SELECT discord_enabled FROM user WHERE id = ?", (user.id,)).fetchone()
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        korail_linked=korail_linked(conn, user.id),
        discord_linked=discord_linked(conn, user.id),
        discord_enabled=bool(row["discord_enabled"]),
    )
