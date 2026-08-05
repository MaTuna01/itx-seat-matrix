"""SQLite 접근 (PLAN.md 5절). 1~2인용 · 행 수십 개 수준이라 stdlib `sqlite3`로 충분하다.

datetime은 전부 **KST aware ISO8601 문자열**로 저장/복원한다 (D-21).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.config import get_settings
from app.domain.models import KST

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def db_path() -> Path:
    return Path(get_settings().db_path)


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI는 동기 의존성을 스레드풀에서 실행하므로
    # 커넥션 생성 스레드와 사용 스레드가 다를 수 있다. 요청당 1커넥션이고
    # 한 요청 안에서 동시 사용은 없다 (worker=1 + 인프로세스 스케줄러 전제, D-17).
    conn = sqlite3.connect(target, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def db_session() -> Iterator[sqlite3.Connection]:
    """FastAPI 의존성. 요청당 커넥션 1개 (1~2인용 규모라 풀링 불필요)."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    """migrations/*.sql을 파일명 순으로 적용한다 (`PRAGMA user_version`이 적용 카운터)."""
    with get_conn(path) as conn:
        applied = conn.execute("PRAGMA user_version").fetchone()[0]
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for version, sql_file in enumerate(files, start=1):
            if version <= applied:
                continue
            conn.executescript(sql_file.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {version}")


# ── 런타임 설정 (app_setting) ────────────────────────────────────────
# 관리자가 재배포 없이 바꾸는 값만 여기 둔다 (현재: signup_enabled, D-24).
# env(config.Settings)는 배포 시점에 고정되는 값 담당이다.
def get_flag(conn: sqlite3.Connection, key: str, default: bool = False) -> bool:
    row = conn.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
    return default if row is None else row["value"] == "true"


def set_flag(
    conn: sqlite3.Connection, key: str, value: bool, *, now: datetime, user_id: int | None = None
) -> None:
    conn.execute(
        "INSERT INTO app_setting (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
        " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
        (key, "true" if value else "false", to_db(now), user_id),
    )


# ── 직렬화 헬퍼 ──────────────────────────────────────────────────────
def to_db(value: datetime | _date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime은 저장하지 않는다 (KST aware 필수)")
        return value.astimezone(KST).isoformat()
    return value.isoformat()


def dt_from_db(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"DB에 naive datetime이 저장돼 있다: {value}")
    return parsed.astimezone(KST)


def date_from_db(value: str) -> _date:
    return _date.fromisoformat(value)
