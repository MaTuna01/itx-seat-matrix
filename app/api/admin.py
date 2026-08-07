"""관리자 설정 + 사용자 관리 (PLAN.md 6·7절, D-24, D-53).

가입 허용을 env가 아니라 DB에 두고 **관리자가 재배포 없이** 켜고 끈다.
관리자는 첫 계정에만 자동 부여되며 승격 API는 없다 (1~2인용에 과함).

사용자 관리(D-53)는 가입 잠금의 뒤처리다 — 잠그는 걸 잊어 원치 않는 계정이 생겼을 때
서버에 SSH로 들어가지 않고 앱에서 지운다. 권한이 HTTP로 노출되는 대가를 치르므로
**삭제에는 방어가 네 겹**이다: 관리자 전용 / 비밀번호 재확인 / 자기 자신 금지 /
관리자 계정 금지. 뒤의 둘은 재인증으로 막히지 않는 사고(관리자 소멸 = 앱에서 복구 불가)를
막는 것이라 UI가 아니라 **서버가** 거절한다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import now_kst
from app.auth.crypto import verify_password
from app.auth.session import current_admin
from app.domain.models import User
from app.storage.db import db_session, dt_from_db, get_flag, set_flag

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


# ── 사용자 관리 (D-53) ───────────────────────────────────────────────────────


class AdminUserOut(BaseModel):
    """관리자 목록의 한 줄.

    **자격증명은 한 조각도 나가지 않는다** (CLAUDE.md 절대규칙 9). 연동 여부는
    `*_enc` 컬럼의 NULL 여부로만 판단한다 — 복호화하지 않으므로 값이 메모리에도 뜨지 않는다.
    """

    id: int
    email: str
    display_name: str
    is_admin: bool
    created_at: datetime | None
    korail_linked: bool
    discord_linked: bool
    subscription_count: int  # 활성/종료를 가리지 않은 전체


class DeleteUserIn(BaseModel):
    password: str  # 삭제하는 관리자 **본인의** 비밀번호


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    admin: User = Depends(current_admin), conn: sqlite3.Connection = Depends(db_session)
) -> list[AdminUserOut]:
    rows = conn.execute(
        "SELECT u.id, u.email, u.display_name, u.is_admin, u.created_at,"
        "       u.korail_id IS NOT NULL AND u.korail_pw_enc IS NOT NULL AS korail_linked,"
        "       u.discord_webhook_enc IS NOT NULL AS discord_linked,"
        "       (SELECT COUNT(*) FROM subscription s WHERE s.user_id = u.id) AS subscription_count"
        " FROM user u ORDER BY u.id"
    ).fetchall()
    return [
        AdminUserOut(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            is_admin=bool(row["is_admin"]),
            created_at=dt_from_db(row["created_at"]),
            korail_linked=bool(row["korail_linked"]),
            discord_linked=bool(row["discord_linked"]),
            subscription_count=row["subscription_count"],
        )
        for row in rows
    ]


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    payload: DeleteUserIn,
    admin: User = Depends(current_admin),
    conn: sqlite3.Connection = Depends(db_session),
) -> None:
    """사용자 1명 삭제. 딸린 데이터는 FK CASCADE가 함께 지운다.

    비밀번호 확인을 **가장 먼저** 한다 — 이 엔드포인트는 재인증 없이는 아무것도 하지
    않는다는 것이 읽는 사람에게도 분명해야 한다.
    """
    if not verify_password(_password_hash(conn, admin.id), payload.password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="비밀번호가 일치하지 않습니다"
        )

    row = conn.execute("SELECT id, is_admin FROM user WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="없는 사용자입니다")

    # 아래 둘은 UI에서 버튼을 감추는 것으로 끝내면 안 된다. 관리자가 사라지면 승격 API가
    # 없어 **앱에서 되돌릴 방법이 없고**, DB를 직접 고치는 수밖에 없다 (D-24 후속 미해결 항목)
    if row["id"] == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="자기 자신은 삭제할 수 없습니다"
        )
    if row["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="관리자 계정은 삭제할 수 없습니다"
        )

    # session/preset/subscription/push_device는 ON DELETE CASCADE다 (001_init.sql, 006).
    # `db_session`이 `PRAGMA foreign_keys = ON`을 켠 연결이라야 실제로 지워진다 —
    # 꺼진 연결에서는 **에러 없이** 고아 행이 남는다
    conn.execute("DELETE FROM user WHERE id = ?", (user_id,))


def _password_hash(conn: sqlite3.Connection, user_id: int) -> str:
    """세션이 살아 있는데 계정이 사라진 경우는 CASCADE 때문에 생길 수 없다."""
    row = conn.execute("SELECT password_hash FROM user WHERE id = ?", (user_id,)).fetchone()
    if row is None:  # pragma: no cover - 방어적
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="세션이 만료되었습니다")
    return row["password_hash"]
