"""인증 엔드포인트 (PLAN.md 6·7절).

가입 잠금 (D-24): 허용 여부는 env가 아니라 DB(`app_setting.signup_enabled`, 기본 잠김)에
있고 관리자가 토글한다. 단 **사용자가 0명이면 부트스트랩으로 항상 허용**하고,
그 첫 계정이 관리자가 된다. "열어둘 이유가 없는 엔드포인트는 닫는다"는 원칙은 그대로다.

세션 수명 (D-23): "로그인 유지"(`remember`)면 지속 쿠키 + 30일,
아니면 브라우저 세션 쿠키 + 12시간. 쿠키와 서버 세션을 함께 가른다.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import now_kst
from app.auth.crypto import hash_password, verify_password
from app.auth.session import create_session, current_user, delete_session, session_lifetime
from app.config import get_settings
from app.domain.models import User
from app.storage.db import db_session, get_flag, to_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=40)
    remember: bool = False


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    remember: bool = False  # 기본값은 해제 — 보안 기본값을 안전한 쪽에 둔다 (D-23)


class MeOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool


def _set_cookie(response: Response, token: str, *, persistent: bool) -> None:
    """`persistent=False`면 `Max-Age`를 붙이지 않는다 = 브라우저 세션 쿠키 (D-23)."""
    settings = get_settings()
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=int(session_lifetime(persistent).total_seconds()) if persistent else None,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def signup_open(conn: sqlite3.Connection) -> bool:
    """가입 가능 여부 = 부트스트랩(사용자 0명) 또는 관리자가 켜둔 상태 (D-24)."""
    if conn.execute("SELECT COUNT(*) AS n FROM user").fetchone()["n"] == 0:
        return True
    return get_flag(conn, "signup_enabled")


@router.post("/signup", response_model=MeOut, status_code=status.HTTP_201_CREATED)
def signup(
    payload: SignupIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(db_session),
) -> MeOut:
    if not signup_open(conn):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="가입이 잠겨 있습니다")

    # 첫 계정이 관리자다 (D-24). 이후 승격 API는 만들지 않는다
    is_admin = conn.execute("SELECT COUNT(*) AS n FROM user").fetchone()["n"] == 0

    now = now_kst()
    try:
        cur = conn.execute(
            "INSERT INTO user (email, password_hash, display_name, is_admin, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                payload.email,
                hash_password(payload.password),
                payload.display_name,
                int(is_admin),
                to_db(now),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 존재하는 이메일입니다") from exc

    user_id = int(cur.lastrowid)
    token, _ = create_session(
        conn,
        user_id,
        now=now,
        persistent=payload.remember,
        user_agent=request.headers.get("user-agent"),
    )
    _set_cookie(response, token, persistent=payload.remember)
    return MeOut(
        id=user_id,
        email=payload.email,
        display_name=payload.display_name,
        is_admin=is_admin,
    )


@router.post("/login", response_model=MeOut)
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(db_session),
) -> MeOut:
    row = conn.execute(
        "SELECT id, email, password_hash, display_name, is_admin FROM user WHERE email = ?",
        (payload.email,),
    ).fetchone()
    # 존재 여부를 응답으로 구분해주지 않는다
    if row is None or not verify_password(row["password_hash"], payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="이메일 또는 비밀번호가 올바르지 않습니다"
        )

    token, _ = create_session(
        conn,
        row["id"],
        now=now_kst(),
        persistent=payload.remember,
        user_agent=request.headers.get("user-agent"),
    )
    _set_cookie(response, token, persistent=payload.remember)
    return MeOut(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        is_admin=bool(row["is_admin"]),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(db_session),
) -> Response:
    token = request.cookies.get(get_settings().cookie_name)
    if token:
        delete_session(conn, token)
    response.delete_cookie(get_settings().cookie_name, path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
