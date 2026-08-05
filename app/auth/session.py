"""세션 쿠키 인증 (PLAN.md 6절, D-10).

- 이메일+비밀번호 → 서버 세션 쿠키 (HttpOnly, SameSite=Lax, 배포 시 Secure)
- 세션은 DB 테이블. 만료 30일, 접근 시 슬라이딩 연장
- JWT를 쓰지 않는 이유: 1~2인용에선 세션 테이블이 더 단순하고 **즉시 무효화**가 된다

모든 `/api/*`는 `Depends(current_user)`를 붙인다. `user_id`를 쿼리·바디로 받지 않는다
(IDOR 방지, CLAUDE.md 절대규칙 9).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request, status

from app.auth.crypto import new_session_token
from app.config import get_settings
from app.domain.models import KST, User
from app.storage.db import db_session, dt_from_db, to_db


def session_lifetime(persistent: bool) -> timedelta:
    """세션 수명 (D-23). "로그인 유지" 체크 여부로 갈린다."""
    settings = get_settings()
    return (
        timedelta(days=settings.session_days)
        if persistent
        else timedelta(hours=settings.session_transient_hours)
    )


def create_session(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    now: datetime,
    persistent: bool = False,
    user_agent: str | None = None,
) -> tuple[str, datetime]:
    token = new_session_token()
    expires_at = now + session_lifetime(persistent)
    conn.execute(
        "INSERT INTO session (token, user_id, created_at, expires_at, user_agent, persistent)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (token, user_id, to_db(now), to_db(expires_at), user_agent, int(persistent)),
    )
    return token, expires_at


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM session WHERE token = ?", (token,))


def resolve_session(conn: sqlite3.Connection, token: str, *, now: datetime) -> User | None:
    """토큰 → 사용자. 만료 세션은 즉시 삭제한다. 유효하면 슬라이딩 연장."""
    row = conn.execute(
        "SELECT s.token, s.expires_at, s.persistent,"
        " u.id, u.email, u.display_name, u.created_at, u.is_admin"
        " FROM session s JOIN user u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None

    expires_at = dt_from_db(row["expires_at"])
    if expires_at is None or expires_at <= now:
        delete_session(conn, token)
        return None

    # 슬라이딩 연장은 **원래 갈래의 수명으로만** 한다 —
    # 임시 세션이 접속할 때마다 30일로 승격되면 D-23이 무의미해진다
    conn.execute(
        "UPDATE session SET expires_at = ? WHERE token = ?",
        (to_db(now + session_lifetime(bool(row["persistent"]))), token),
    )
    return User(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        created_at=dt_from_db(row["created_at"]),
        is_admin=bool(row["is_admin"]),
    )


def current_user(
    request: Request, conn: sqlite3.Connection = Depends(db_session)
) -> User:
    """인증 의존성. 세션이 없거나 만료면 401 (프론트는 401에서 로그인 화면으로 라우팅)."""
    token = request.cookies.get(get_settings().cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다")
    user = resolve_session(conn, token, now=datetime.now(KST))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="세션이 만료되었습니다")
    return user


def current_admin(user: User = Depends(current_user)) -> User:
    """관리자 전용 의존성 (D-24). 관리자는 첫 계정 자동 부여뿐이다."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자만 사용할 수 있습니다")
    return user
