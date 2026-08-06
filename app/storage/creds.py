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

import logging
import sqlite3

from cryptography.fernet import InvalidToken

from app.auth.crypto import decrypt_secret, encrypt_secret
from app.domain.models import KorailCred

log = logging.getLogger(__name__)


def _decrypt_or_none(token: str, *, what: str, user_id: int) -> str | None:
    """복호화 실패를 예외로 올리지 않고 None으로 답한다 (Phase 4 배포 대비).

    `SECRET_KEY`가 암호화 당시와 다르면 `InvalidToken`이 난다 — **DB 파일만 옮기고
    키는 새로 만든 배포**에서 반드시 발생한다. 예외로 두면 스케줄러의 구독별
    `except Exception`에 잡혀 서버 로그 한 줄만 남고 **알림이 조용히 끊긴다.**
    None으로 떨어뜨리면 기존 "미연동" 경로를 타서 `FETCH_FAILED`가 1회라도 나간다.

    로그는 반드시 남긴다 — 사용자에게는 "미연동"으로 보이므로, 진짜 원인이
    키 불일치라는 사실은 여기서만 알 수 있다.
    """
    try:
        return decrypt_secret(token)
    except InvalidToken:
        log.error(
            "user %s의 %s 복호화 실패 — SECRET_KEY가 암호화 당시와 다르다."
            " DB만 옮기고 키를 새로 만들었다면 .env의 SECRET_KEY를 원래 값으로 되돌리거나,"
            " 화면에서 다시 등록해야 한다.",
            user_id,
            what,
        )
        return None


def load_korail_cred(conn: sqlite3.Connection, user_id: int) -> KorailCred | None:
    """미등록이면 None. 호출부가 "계정 먼저 연결하라"로 안내한다.

    **복호화 실패도 None이다** — 이유는 `_decrypt_or_none` 참고.
    """
    row = conn.execute(
        "SELECT korail_id, korail_pw_enc FROM user WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None or not row["korail_id"] or not row["korail_pw_enc"]:
        return None
    password = _decrypt_or_none(row["korail_pw_enc"], what="코레일 비밀번호", user_id=user_id)
    if password is None:
        return None
    return KorailCred(korail_id=row["korail_id"], korail_pw=password)


def korail_linked(conn: sqlite3.Connection, user_id: int) -> bool:
    """화면 표시용 — **복호화까지 되어야 "연결됨"이다.**

    행에 값이 있다는 것만으로 "연결됨"이라고 하면, 키가 어긋난 순간부터
    화면은 연결됐다고 하는데 조회는 계속 실패하는 상태가 된다. 디스코드 웹훅에서
    이미 같은 판단을 했다 — "연동됨으로 표시된 채 발송이 안 되는 상태가 가장 나쁘다".
    """
    try:
        return load_korail_cred(conn, user_id) is not None
    except RuntimeError:  # SECRET_KEY 자체가 없다
        log.error("SECRET_KEY가 설정되지 않아 user %s의 코레일 연결 상태를 확인할 수 없다", user_id)
        return False


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
    return _decrypt_or_none(row["discord_webhook_enc"], what="디스코드 웹훅", user_id=user_id)


def discord_linked(conn: sqlite3.Connection, user_id: int) -> bool:
    """화면 표시용. 코레일과 같은 이유로 복호화까지 확인한다."""
    try:
        return load_discord_webhook(conn, user_id) is not None
    except RuntimeError:
        return False


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
