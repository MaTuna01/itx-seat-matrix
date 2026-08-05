"""인증 엔드포인트 (PLAN.md 6·7절).

가입은 `ALLOW_SIGNUP=true`일 때만 열린다 — 첫 계정 생성 후 env를 false로 되돌린다
(부트스트랩 1회, D-10). 공개 노출을 안 하더라도 열어둘 이유가 없는 엔드포인트는 닫는다.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import now_kst
from app.auth.crypto import hash_password, verify_password
from app.auth.session import create_session, current_user, delete_session
from app.config import get_settings
from app.domain.models import User
from app.storage.db import db_session, to_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=40)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MeOut(BaseModel):
    id: int
    email: str
    display_name: str


def _set_cookie(response: Response, token: str, max_age_days: int) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=max_age_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/signup", response_model=MeOut, status_code=status.HTTP_201_CREATED)
def signup(
    payload: SignupIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(db_session),
) -> MeOut:
    settings = get_settings()
    if not settings.allow_signup:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="가입이 잠겨 있습니다")

    now = now_kst()
    try:
        cur = conn.execute(
            "INSERT INTO user (email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
            (payload.email, hash_password(payload.password), payload.display_name, to_db(now)),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 존재하는 이메일입니다") from exc

    user_id = int(cur.lastrowid)
    token, _ = create_session(
        conn, user_id, now=now, user_agent=request.headers.get("user-agent")
    )
    _set_cookie(response, token, settings.session_days)
    return MeOut(id=user_id, email=payload.email, display_name=payload.display_name)


@router.post("/login", response_model=MeOut)
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(db_session),
) -> MeOut:
    row = conn.execute(
        "SELECT id, email, password_hash, display_name FROM user WHERE email = ?",
        (payload.email,),
    ).fetchone()
    # 존재 여부를 응답으로 구분해주지 않는다
    if row is None or not verify_password(row["password_hash"], payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="이메일 또는 비밀번호가 올바르지 않습니다"
        )

    settings = get_settings()
    token, _ = create_session(
        conn, row["id"], now=now_kst(), user_agent=request.headers.get("user-agent")
    )
    _set_cookie(response, token, settings.session_days)
    return MeOut(id=row["id"], email=row["email"], display_name=row["display_name"])


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
