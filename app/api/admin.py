"""관리자 설정 (PLAN.md 6·7절, D-24).

가입 허용을 env가 아니라 DB에 두고 **관리자가 재배포 없이** 켜고 끈다.
관리자는 첫 계정에만 자동 부여되며 승격 API는 없다 (1~2인용에 과함).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import now_kst
from app.auth.session import current_admin
from app.domain.models import User
from app.storage.db import db_session, get_flag, set_flag

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminSettings(BaseModel):
    signup_enabled: bool


@router.get("/settings", response_model=AdminSettings)
def read_settings(
    admin: User = Depends(current_admin), conn: sqlite3.Connection = Depends(db_session)
) -> AdminSettings:
    return AdminSettings(signup_enabled=get_flag(conn, "signup_enabled"))


@router.patch("/settings", response_model=AdminSettings)
def update_settings(
    payload: AdminSettings,
    admin: User = Depends(current_admin),
    conn: sqlite3.Connection = Depends(db_session),
) -> AdminSettings:
    set_flag(conn, "signup_enabled", payload.signup_enabled, now=now_kst(), user_id=admin.id)
    return AdminSettings(signup_enabled=get_flag(conn, "signup_enabled"))
