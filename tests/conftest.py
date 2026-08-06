"""테스트 공통 픽스처.

시간은 전부 `now` 주입으로 시나리오를 만든다 — sleep/실제 시계 사용 금지 (CLAUDE.md).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.config import get_settings
from app.domain.models import KST, SeatMatrix, SeatRow, StopInfo

# 프로토타입(seat-matrix.jsx)과 동일한 목업 노선
STOPS: list[str] = ["천안", "평택", "수원", "안양", "영등포", "서울"]
ARRIVAL_OFFSETS = [0, 12, 26, 38, 48, 56]
RIDE_DATE = date(2026, 8, 5)


def at(hour: int, minute: int, second: int = 0) -> datetime:
    """운행일 기준 KST aware datetime."""
    return datetime(2026, 8, 5, hour, minute, second, tzinfo=KST)


def stop_infos(delay_free: bool = True) -> list[StopInfo]:
    base = at(8, 0)
    return [
        StopInfo(name=name, arrival=base + timedelta(minutes=offset))
        for name, offset in zip(STOPS, ARRIVAL_OFFSETS)
    ]


def make_matrix(
    seats: dict[str, list[bool]],
    *,
    stops: list[str] | None = None,
    fetched_at: datetime | None = None,
    queried_from_idx: int = 0,
    queried_to_idx: int | None = None,
) -> SeatMatrix:
    """`{"3-7A": [True, False, ...]}` → SeatMatrix."""
    stops = stops or STOPS
    rows = []
    for key, cells in seats.items():
        car, _, seat_no = key.partition("-")
        rows.append(SeatRow(car=int(car), seat_no=seat_no, cells=list(cells)))
    return SeatMatrix(
        train_no="1004",
        date=RIDE_DATE,
        stops=stops,
        seats=rows,
        fetched_at=fetched_at or at(8, 14),
        queried_from_idx=queried_from_idx,
        queried_to_idx=len(stops) - 1 if queried_to_idx is None else queried_to_idx,
    )


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """테스트마다 독립 DB. `.env`의 실제 값이 새어들지 않게 한다.

    첫 계정은 부트스트랩으로 항상 가입 가능하다 (D-24) — 별도 플래그가 필요 없다.
    """
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ADAPTER", "mock")
    # 테스트 전용 Fernet 키 (코레일 자격증명 암호화, Phase 2 C).
    # 고정값이라 결정적이다 — 실 키는 .env에만 있고 여기로 새지 않는다.
    monkeypatch.setenv("SECRET_KEY", "hQ2yA1nQ8vJZ0pQ7cX5rT3uW9sB6dF4gH8kL2mN0oP4=")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    """로그인까지 마친 TestClient (세션 쿠키 보유)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        res = c.post(
            "/api/auth/signup",
            json={"email": "me@example.com", "password": "commute-1234", "display_name": "나"},
        )
        assert res.status_code == 201, res.text
        yield c


def enable_signup(admin_client) -> None:
    """관리자가 가입을 연다 (D-24). 두 번째 계정을 만들려면 반드시 거쳐야 한다."""
    res = admin_client.patch("/api/admin/settings", json={"signup_enabled": True})
    assert res.status_code == 200, res.text


@pytest.fixture
def anon_client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
