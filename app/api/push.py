"""알림 기기 등록 + 테스트 발송 (PLAN.md 7절, 8절, D-9/D-20).

`POST /api/push/test`가 이 파일의 존재 이유의 절반이다. iOS 웹푸시는 **홈화면 추가가
전제**이고 배달 신뢰성이 네이티브보다 낮아 조용히 실패하는 일이 잦다. 상시 점검 수단이
없으면 "알림이 안 온다"와 "보낼 알림이 없다"를 구분할 방법이 없다 (D-9).

VAPID **공개키**만 나간다 (`GET /api/push/config`). 브라우저가
`pushManager.subscribe({applicationServerKey})`에 넣어야 하는 값이라 공개돼도 무해하다.
비밀키는 env에만 있고 어떤 응답에도 실리지 않는다 (절대규칙 9, D-34).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.adapters.notify import send_note, test_notification
from app.api.deps import now_kst
from app.auth.session import current_user
from app.config import get_settings
from app.domain.models import User
from app.storage import push as push_repo
from app.storage.db import db_session, dt_from_db

router = APIRouter(prefix="/api/push", tags=["push"])


class PushConfigOut(BaseModel):
    """공개키와 "설정됐는지"만. 비밀키는 절대 나가지 않는다."""

    vapid_public_key: str
    configured: bool


class PushKeys(BaseModel):
    """브라우저 `PushSubscription.toJSON().keys` 그대로."""

    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class PushDeviceIn(BaseModel):
    endpoint: str = Field(min_length=1)
    keys: PushKeys
    label: str | None = None


class PushDeviceOut(BaseModel):
    id: int
    label: str | None
    created_at: datetime


class PushTestOut(BaseModel):
    """발송 결과를 그대로 돌려준다 — "몇 대에 보냈는지"가 곧 진단 정보다."""

    sent: int
    devices: int
    errors: list[str]


@router.get("/config", response_model=PushConfigOut)
def get_push_config(user: User = Depends(current_user)) -> PushConfigOut:
    settings = get_settings()
    return PushConfigOut(
        vapid_public_key=settings.vapid_public_key,
        configured=settings.webpush_configured,
    )


@router.get("/devices", response_model=list[PushDeviceOut])
def list_push_devices(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> list[PushDeviceOut]:
    """등록된 기기 목록. `endpoint`/키는 돌려주지 않는다 — 화면은 라벨만 알면 된다."""
    rows = conn.execute(
        "SELECT id, label, created_at FROM push_device WHERE user_id = ? ORDER BY id",
        (user.id,),
    ).fetchall()
    return [
        PushDeviceOut(id=row["id"], label=row["label"], created_at=dt_from_db(row["created_at"]))
        for row in rows
    ]


@router.post("/devices", response_model=PushDeviceOut, status_code=status.HTTP_201_CREATED)
def register_push_device(
    body: PushDeviceIn,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> PushDeviceOut:
    """등록/재등록. 같은 endpoint면 행을 재사용한다 (`storage/push.upsert_device`).

    iOS가 endpoint를 회전시키면 새 행이 생기고, 옛 행은 첫 발송에서 410을 받아 삭제된다
    (D-20) — 사용자가 아무것도 하지 않아도 정리된다.
    """
    device_id = push_repo.upsert_device(
        conn,
        user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        label=body.label,
        now=now_kst(),
    )
    row = conn.execute(
        "SELECT id, label, created_at FROM push_device WHERE id = ?", (device_id,)
    ).fetchone()
    return PushDeviceOut(id=row["id"], label=row["label"], created_at=dt_from_db(row["created_at"]))


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_push_device(
    device_id: int,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> Response:
    if not push_repo.delete_device(conn, user.id, device_id):
        raise HTTPException(status_code=404, detail="기기를 찾을 수 없습니다")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test", response_model=PushTestOut)
async def send_push_test(
    user: User = Depends(current_user), conn: sqlite3.Connection = Depends(db_session)
) -> PushTestOut:
    """생존 확인 핑 ★. 디스코드를 켜뒀으면 그쪽으로도 함께 간다 (8절 "양쪽 모두 발송").

    발송 실패를 500으로 바꾸지 않는다 — 실패 이유(키 미설정, 기기 없음, 410)를
    화면에 그대로 보여주는 것이 이 엔드포인트의 목적이다.
    """
    devices = len(push_repo.list_devices(conn, user.id))
    now = now_kst()
    row = conn.execute(
        "SELECT id FROM subscription WHERE user_id = ? AND active = 1"
        " ORDER BY created_at DESC LIMIT 1",
        (user.id,),
    ).fetchone()
    result = await send_note(
        conn,
        user.id,
        test_notification(now=now, subscription_id=row["id"] if row else None),
    )
    return PushTestOut(sent=result.sent, devices=devices, errors=list(result.errors))
