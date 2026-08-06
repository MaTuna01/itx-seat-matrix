"""코레일 자격증명 + 디스코드 웹훅 저장/복원 (PLAN.md 6절·8절, D-22/D-11).

`user.korail_pw_enc`와 `user.discord_webhook_enc`는 **Fernet 암호문**이다 (env `SECRET_KEY`).
평문은 DB에 없고, 복호화는 외부 호출 직전에만 한다.

웹훅 URL이 여기 있는 이유: URL 자체가 **그 채널에 글을 쓸 권한**이므로 사실상 자격증명이다
(8절). 비밀번호와 같은 취급을 받아야 한다.

CLAUDE.md 절대규칙 9: 자격증명은 **API 응답에 절대 노출하지 않는다.**
이 모듈이 반환하는 값은 어댑터로만 흘러가야 하며 응답 모델에 담지 마라 —
API는 "연동됨" 여부만 답한다.
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


# ── 디스코드 웹훅 (PLAN 8절, D-11) ───────────────────────────────────
def load_discord_webhook(conn: sqlite3.Connection, user_id: int) -> str | None:
    """**연동만 확인하고 반환한다 — 발송 여부는 호출부가 `discord_enabled`로 판단한다.**

    opt-in 2단계(① 연동 + ② 토글)를 이 함수 하나로 합치지 않는 이유: 토글이 꺼진
    상태에서도 재연동 없이 다시 켤 수 있어야 하고, "저장 시 테스트 발송"(8절)은
    토글과 무관하게 URL을 검증해야 한다.
    """
    row = conn.execute(
        "SELECT discord_webhook_enc FROM user WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None or not row["discord_webhook_enc"]:
        return None
    return decrypt_secret(row["discord_webhook_enc"])


def save_discord_webhook(conn: sqlite3.Connection, user_id: int, webhook_url: str) -> None:
    """연동 저장. **토글은 건드리지 않는다** — 꺼둔 채로 URL만 갱신할 수 있다."""
    conn.execute(
        "UPDATE user SET discord_webhook_enc = ? WHERE id = ?",
        (encrypt_secret(webhook_url), user_id),
    )


def set_discord_enabled(conn: sqlite3.Connection, user_id: int, enabled: bool) -> None:
    conn.execute(
        "UPDATE user SET discord_enabled = ? WHERE id = ?", (1 if enabled else 0, user_id)
    )


def clear_discord_webhook(conn: sqlite3.Connection, user_id: int) -> None:
    """연동 해제 — 토글도 함께 내린다. URL이 없는데 켜져 있으면 상태가 거짓말을 한다."""
    conn.execute(
        "UPDATE user SET discord_webhook_enc = NULL, discord_enabled = 0 WHERE id = ?",
        (user_id,),
    )
