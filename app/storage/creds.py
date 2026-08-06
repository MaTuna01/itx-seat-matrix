"""코레일 자격증명 저장/복원 (PLAN.md 6절, D-22).

`user.korail_pw_enc`는 **Fernet 암호문**이다 (env `SECRET_KEY`). 평문은 DB에 없고,
복호화는 코레일 호출 직전에만 한다.

CLAUDE.md 절대규칙 9: 자격증명은 **API 응답에 절대 노출하지 않는다.**
이 모듈이 반환하는 `KorailCred`는 어댑터로만 흘러가야 하며 응답 모델에 담지 마라.
"""

from __future__ import annotations

import sqlite3

from app.auth.crypto import decrypt_secret, encrypt_secret
from app.domain.models import KorailCred


def load_korail_cred(conn: sqlite3.Connection, user_id: int) -> KorailCred | None:
    """미등록이면 None. 호출부가 "계정 먼저 연결하라"로 안내한다."""
    row = conn.execute(
        "SELECT korail_id, korail_pw_enc FROM user WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None or not row["korail_id"] or not row["korail_pw_enc"]:
        return None
    return KorailCred(
        korail_id=row["korail_id"], korail_pw=decrypt_secret(row["korail_pw_enc"])
    )


def save_korail_cred(conn: sqlite3.Connection, user_id: int, cred: KorailCred) -> None:
    conn.execute(
        "UPDATE user SET korail_id = ?, korail_pw_enc = ? WHERE id = ?",
        (cred.korail_id, encrypt_secret(cred.korail_pw), user_id),
    )


def clear_korail_cred(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute(
        "UPDATE user SET korail_id = NULL, korail_pw_enc = NULL WHERE id = ?", (user_id,)
    )
