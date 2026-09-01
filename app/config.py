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

    # ── 정차역 캐시 자동 재적재 (D-58, 이슈 #76) ─────────────────────
    # 공공데이터 '한국철도공사_열차운행정보' 인증키 — 시크릿, .env로만 넣는다.
    # scripts/load_train_stops.py 도 같은 값을 읽는다 (.env fallback).
    data_go_kr_service_key: str = ""
    # cron 시각: 06:05 = EC2 평일 06:00 기동(D-54) 직후, 12:05 = 낮 복구 창구.
    # 콤마 구분 문자열 — APScheduler `cron` 트리거가 그대로 해석한다
    stops_reload_hours: str = "6,12"
    stops_reload_minute: int = 5
    # 스테일 번호 퍼지 임계. 7일 = 주말 공백(월요일 적재=일요일 실적)까지 커버.
    # `<` 부등호로 컷오프 정확일은 유지 (adapters/train_run_info.apply_day)
    train_stop_max_age_days: int = 7

    # ── 로깅 (PLAN 12절, → D-39) ────────────────────────────────────
    # 배포에서 스케줄러가 도는지 확인할 유일한 수단이다 (`docker compose logs`).
    # uvicorn은 자기 로거만 설정하고 root는 비워두므로 앱이 직접 붙여야 한다
    # (`main.configure_logging`). 시끄러우면 WARNING으로 올린다.
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        """`info` 같은 소문자를 허용한다. `logging`은 대문자 이름만 안다."""
        return value.strip().upper() or "INFO"

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
