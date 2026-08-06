"""비밀번호 해시 + 대칭키 암복호화 (PLAN.md 6절).

- 비밀번호: **argon2id**. 직접 구현 금지 — `argon2-cffi`(passlib의 argon2 백엔드와 동일)를 쓴다
- 비밀: **Fernet** 대칭키(env `SECRET_KEY`). 코레일 비밀번호·디스코드 웹훅 URL 저장용.
  Phase 1에서는 사용처가 없고 Phase 2·3에서 쓴다
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet

from app.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _fernet() -> Fernet:
    key = get_settings().secret_key
    if not key:
        raise RuntimeError("SECRET_KEY(Fernet)가 설정되지 않았다 — .env를 확인할 것")
    return Fernet(key.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
