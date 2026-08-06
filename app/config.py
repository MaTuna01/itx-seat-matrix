"""앱 설정 (env). 시크릿은 `.env`로만 — 커밋 금지 (CLAUDE.md)."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
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

    # ── 웹푸시 VAPID (PLAN 8절, D-34) ────────────────────────────────
    # 공개키만 프론트로 나간다 (`GET /api/push/config`). 비밀키는 DB에도 넣지 않는다.
    # 생성: uv run python scripts/gen_vapid.py  (vapid_subject는 mailto: 연락처 URI)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:itx@localhost"

    # ── 스케줄러 (PLAN 9절) ──────────────────────────────────────────
    # 30초 틱. 틱 자체는 "시계 확인"일 뿐이고 코레일 조회는 next_poll_at 도래 시에만 발생한다.
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 30

    @field_validator("vapid_subject")
    @classmethod
    def _normalize_vapid_subject(cls, value: str) -> str:
        """스킴이 없으면 `mailto:`를 붙인다.

        `py_vapid._check_sub()`는 `mailto:` 또는 `https://` **스킴을 필수로** 요구하고,
        없으면 발송 시점에 "Missing 'sub' from claims"로 죽는다. 그 시점이 하필
        **폰에서 알림 켜기 버튼을 누른 순간**이라 원인이 서버 설정에 있다는 걸 알기 어렵다.
        `.env`에 이메일 주소만 적는 건 충분히 흔한 실수이므로 여기서 흡수한다 (D-34).
        """
        value = value.strip()
        if value and not re.match(r"^\w+:", value):
            return f"mailto:{value}"
        return value

    @property
    def webpush_configured(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
