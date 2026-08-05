"""앱 설정 (env). 시크릿은 `.env`로만 — 커밋 금지 (CLAUDE.md)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 저장소
    db_path: str = "data/itx.db"

    # 인증 (PLAN 6절)
    # 가입 허용은 env가 아니라 DB(app_setting.signup_enabled)에 있다 — 관리자가 토글 (D-24)
    session_days: int = 30  # "로그인 유지" 체크 시 (D-23)
    session_transient_hours: int = 12  # 미체크 시 — 브라우저 세션 쿠키 + 짧은 서버 만료
    cookie_secure: bool = False  # 배포(ts.net HTTPS)에서는 true
    cookie_name: str = "itx_session"

    # 어댑터 전환 (PLAN 11절 Phase 2). Phase 1은 mock만 동작한다
    adapter: Literal["mock", "korail2"] = "mock"

    # Fernet 대칭키 — 코레일 비밀번호/디스코드 웹훅 암호화용 (Phase 2·3에서 사용)
    secret_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
