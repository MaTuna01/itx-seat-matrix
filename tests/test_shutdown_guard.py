"""자동 정지 가드 규칙 (#58).

가드가 조용히 틀리는 두 방향을 잠근다:

- **꺼야 할 때 켜둔다** → 절감이 0이 된다. 요금서에만 나타나서 알아채기까지 한 달 걸린다
- **끄지 말아야 할 때 끈다** → 다음 기동 전에 도래하는 폴이 통째로 사라진다 (D-19의
  grace 초과 스킵). 이쪽이 훨씬 비싸다 — 그래서 판단 불능은 전부 "켜둔다"로 간다

`scripts/`는 패키지가 아니므로 파일 경로로 적재한다 — `tests/test_deploy_guard.py`와 같다.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "shutdown_guard.py"
_spec = importlib.util.spec_from_file_location("shutdown_guard", _PATH)
assert _spec and _spec.loader
shutdown_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shutdown_guard)

KST = ZoneInfo("Asia/Seoul")

# 2026-08-10 은 월요일이다 (08-07 금 / 08-08 토 / 08-09 일).
MON_NIGHT = datetime(2026, 8, 10, 23, 50, tzinfo=KST)
FRI_NIGHT = datetime(2026, 8, 14, 23, 50, tzinfo=KST)

# 실제 스키마의 부분집합이다 — 가드는 이 네 칸만 읽는다
_DDL = """
CREATE TABLE subscription (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    train_no     TEXT NOT NULL,
    date         TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1,
    next_poll_at TEXT
)
"""


def _conn(rows: list[tuple[str, int, str | None]]) -> sqlite3.Connection:
    """(train_no, active, next_poll_at) 목록으로 메모리 DB를 만든다."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL)
    conn.executemany(
        "INSERT INTO subscription (train_no, date, active, next_poll_at)"
        " VALUES (?, '2026-08-11', ?, ?)",
        rows,
    )
    return conn


def _decide(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    """유닛이 실제로 쓰는 경로 그대로 — 다음 기동 + 부팅 마진까지를 본다."""
    deadline = shutdown_guard.next_start_at(now) + shutdown_guard.BOOT_MARGIN
    return shutdown_guard.polls_before(conn, now=now, deadline=deadline)


class TestNextStartAt:
    """주말 정지는 전부 이 함수 하나에서 나온다."""

    def test_weeknight_wakes_next_morning(self) -> None:
        assert shutdown_guard.next_start_at(MON_NIGHT) == datetime(
            2026, 8, 11, 6, 0, tzinfo=KST
        )

    def test_friday_night_wakes_monday(self) -> None:
        """★ 금요일 밤의 다음 기동은 토요일이 아니라 월요일이다."""
        assert shutdown_guard.next_start_at(FRI_NIGHT) == datetime(
            2026, 8, 17, 6, 0, tzinfo=KST
        )

    def test_weekend_wakes_monday(self) -> None:
        """손으로 켜둔 주말에도 답은 월요일이다."""
        sat = datetime(2026, 8, 15, 10, 0, tzinfo=KST)
        assert shutdown_guard.next_start_at(sat) == datetime(2026, 8, 17, 6, 0, tzinfo=KST)

    def test_before_start_same_day(self) -> None:
        """새벽에 손으로 켠 경우 — 오늘 06:00이 다음 기동이다."""
        dawn = datetime(2026, 8, 11, 5, 0, tzinfo=KST)
        assert shutdown_guard.next_start_at(dawn) == datetime(2026, 8, 11, 6, 0, tzinfo=KST)

    def test_exactly_at_start_moves_on(self) -> None:
        """정확히 기동 시각이면 이미 켜져 있다는 뜻이므로 다음 평일을 본다."""
        assert shutdown_guard.next_start_at(
            datetime(2026, 8, 11, 6, 0, tzinfo=KST)
        ) == datetime(2026, 8, 12, 6, 0, tzinfo=KST)

    def test_naive_input_is_treated_as_kst(self) -> None:
        """호스트 타임존이 어긋나도 KST로 해석한다 (절대규칙 1)."""
        aware = shutdown_guard.next_start_at(MON_NIGHT)
        assert aware.tzinfo is not None


class TestHolds:
    """끄면 안 되는 경우 — 여기가 무너지면 알림이 조용히 사라진다."""

    def test_poll_before_next_start(self) -> None:
        """05:30 열차 → 폴이 06:10(기동+마진)보다 앞이다. 켜둬야 한다."""
        early = datetime(2026, 8, 11, 5, 30, tzinfo=KST).isoformat()
        assert [h["train_no"] for h in _decide(_conn([("4202", 1, early)]), MON_NIGHT)] == [
            "4202"
        ]

    def test_poll_inside_boot_margin(self) -> None:
        """기동 직후 06:05 폴 — 아직 스케줄러가 안 떴을 수 있다. 마진이 이걸 잡는다."""
        at = datetime(2026, 8, 11, 6, 5, tzinfo=KST).isoformat()
        assert len(_decide(_conn([("4202", 1, at)]), MON_NIGHT)) == 1

    def test_weekend_ride_holds_from_friday(self) -> None:
        """★ 토요일 열차가 있으면 금요일 밤부터 정지를 거부한다."""
        sat = datetime(2026, 8, 15, 9, 0, tzinfo=KST).isoformat()
        assert len(_decide(_conn([("4202", 1, sat)]), FRI_NIGHT)) == 1

    def test_sorted_by_time(self) -> None:
        a = datetime(2026, 8, 11, 5, 50, tzinfo=KST).isoformat()
        b = datetime(2026, 8, 11, 5, 10, tzinfo=KST).isoformat()
        hits = _decide(_conn([("4204", 1, a), ("4202", 1, b)]), MON_NIGHT)
        assert [h["train_no"] for h in hits] == ["4202", "4204"]


class TestAllowsShutdown:
    """꺼도 되는 경우 — 여기가 무너지면 절감이 0이 된다."""

    def test_normal_morning_commute(self) -> None:
        """08:00 열차의 폴은 07:50 — 06:10 기동을 한참 지나서다. 꺼도 된다."""
        normal = datetime(2026, 8, 11, 7, 50, tzinfo=KST).isoformat()
        assert _decide(_conn([("4202", 1, normal)]), MON_NIGHT) == []

    def test_inactive_subscription(self) -> None:
        early = datetime(2026, 8, 11, 5, 30, tzinfo=KST).isoformat()
        assert _decide(_conn([("4202", 0, early)]), MON_NIGHT) == []

    def test_null_pointer(self) -> None:
        """만료 판정 대기다 — 다음 기동 뒤 첫 틱에 그대로 난다. 알림과 무관하다."""
        assert _decide(_conn([("4202", 1, None)]), MON_NIGHT) == []

    def test_no_subscriptions(self) -> None:
        assert _decide(_conn([]), MON_NIGHT) == []

    def test_past_pointer(self) -> None:
        """이미 지난 포인터는 정지를 막을 이유가 못 된다."""
        past = datetime(2026, 8, 10, 20, 0, tzinfo=KST).isoformat()
        assert _decide(_conn([("4202", 1, past)]), MON_NIGHT) == []

    def test_unparseable_pointer_is_skipped(self) -> None:
        """읽을 수 없는 행 하나가 정지를 영영 막지는 않는다 (naive datetime 포함)."""
        rows = [("4202", 1, "쓰레기"), ("4204", 1, "2026-08-11T05:30:00")]
        assert _decide(_conn(rows), MON_NIGHT) == []


class TestMain:
    """CLI — systemd 유닛이 보는 것은 종료 코드뿐이다.

    ★ `deploy_guard`와 반대다. 판단 불능은 전부 1(켜둔다)로 간다.
    """

    def test_missing_db_holds(self, tmp_path: Path) -> None:
        assert shutdown_guard.main([str(tmp_path / "없다.db")]) == 1

    def test_schema_missing_holds(self, tmp_path: Path) -> None:
        """빈 DB 파일 — 앱이 뜬 적이 없다는 뜻이다. 끄지 말고 사람이 보게 둔다."""
        db = tmp_path / "itx.db"
        sqlite3.connect(db).close()
        assert shutdown_guard.main([str(db)]) == 1

    def test_exit_codes(self, tmp_path: Path) -> None:
        db = tmp_path / "itx.db"
        conn = sqlite3.connect(db)
        conn.execute(_DDL)
        conn.execute(
            "INSERT INTO subscription (train_no, date, active, next_poll_at)"
            " VALUES ('4202', '2026-08-11', 1, ?)",
            (datetime(2026, 8, 11, 5, 30, tzinfo=KST).isoformat(),),
        )
        conn.commit()
        conn.close()

        # 월요일 밤: 내일 05:30 폴이 기동보다 앞이다 → 켜둔다
        assert shutdown_guard.main([str(db), "--now", MON_NIGHT.isoformat()]) == 1
        # 그 폴이 지난 뒤(화요일 밤)라면 막을 것이 없다 → 끈다
        tue_night = MON_NIGHT + timedelta(days=1)
        assert shutdown_guard.main([str(db), "--now", tue_night.isoformat()]) == 0
