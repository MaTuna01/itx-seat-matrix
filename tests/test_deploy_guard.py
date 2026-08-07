"""재배포 가드 규칙 (#22, D-51).

가드가 조용히 틀리는 두 방향을 잠근다:

- **막아야 할 때 통과시킨다** → 폴 포인트 직전에 컨테이너가 재시작되고 그 폴을 놓친다
- **막지 말아야 할 때 막는다** → CD가 영영 안 도는 쪽으로 고장 난다. 이쪽이 더 흔하다

`scripts/`는 패키지가 아니므로(`app/`과 달리 import 대상이 아니다) 파일 경로로 적재한다 —
`tests/test_secret_scan.py`와 같은 방식이다.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "deploy_guard.py"
_spec = importlib.util.spec_from_file_location("deploy_guard", _PATH)
assert _spec and _spec.loader
deploy_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy_guard)

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 8, 10, 8, 5, tzinfo=KST)
WINDOW = timedelta(minutes=10)

# 실제 스키마의 부분집합이다. 가드는 이 네 칸만 읽는다 —
# 전체 DDL을 복사해 오면 스키마가 바뀔 때마다 이 테스트가 같이 낡는다
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
        " VALUES (?, '2026-08-10', ?, ?)",
        rows,
    )
    return conn


def _at(minutes: float) -> str:
    """`NOW` 기준 상대 시각을 DB 저장 형식(KST aware ISO8601)으로."""
    return (NOW + timedelta(minutes=minutes)).isoformat()


def _polls(conn: sqlite3.Connection) -> list[dict]:
    return deploy_guard.imminent_polls(conn, now=NOW, window=WINDOW)


class TestBlocks:
    """막아야 하는 경우."""

    def test_poll_inside_window(self) -> None:
        hits = _polls(_conn([("4202", 1, _at(4))]))
        assert [h["train_no"] for h in hits] == ["4202"]

    def test_boundaries_are_inclusive(self) -> None:
        """경계는 양쪽 다 포함이다 — 정확히 10분 뒤 폴도 재시작에 걸린다."""
        hits = _polls(_conn([("4202", 1, _at(0)), ("4204", 1, _at(10))]))
        assert len(hits) == 2

    def test_sorted_by_time(self) -> None:
        hits = _polls(_conn([("4204", 1, _at(9)), ("4202", 1, _at(2))]))
        assert [h["train_no"] for h in hits] == ["4202", "4204"]


class TestPasses:
    """통과시켜야 하는 경우 — 여기가 무너지면 CD가 영영 안 돈다."""

    def test_poll_after_window(self) -> None:
        assert _polls(_conn([("4202", 1, _at(11))])) == []

    def test_poll_already_past(self) -> None:
        """지나간 폴은 막을 이유가 없다 — grace 2분 안이면 재시작 뒤 바로 실행된다 (D-19)."""
        assert _polls(_conn([("4202", 1, _at(-1))])) == []

    def test_inactive_subscription(self) -> None:
        assert _polls(_conn([("4202", 0, _at(3))])) == []

    def test_null_pointer(self) -> None:
        """`next_poll_at IS NULL`은 만료 판정 대기다 — 재시작을 넘겨도 다음 틱에 난다."""
        assert _polls(_conn([("4202", 1, None)])) == []

    def test_no_subscriptions(self) -> None:
        assert _polls(_conn([])) == []

    def test_unparseable_pointer_does_not_block(self) -> None:
        """읽을 수 없는 값은 막을 근거가 못 된다 (naive datetime 포함)."""
        rows = [("4202", 1, "쓰레기"), ("4204", 1, "2026-08-10T08:07:00")]
        assert _polls(_conn(rows)) == []


class TestMain:
    """CLI — CD 워크플로가 보는 것은 종료 코드뿐이다."""

    def test_missing_db_passes(self, tmp_path: Path) -> None:
        assert deploy_guard.main([str(tmp_path / "없다.db")]) == 0

    def test_blocks_with_exit_1(self, tmp_path: Path) -> None:
        db = tmp_path / "itx.db"
        conn = sqlite3.connect(db)
        conn.execute(_DDL)
        conn.execute(
            "INSERT INTO subscription (train_no, date, active, next_poll_at)"
            " VALUES ('4202', '2026-08-10', 1, ?)",
            (_at(3),),
        )
        conn.commit()
        conn.close()
        assert deploy_guard.main([str(db), "--now", NOW.isoformat()]) == 1
        assert deploy_guard.main([str(db), "--now", (NOW - timedelta(hours=1)).isoformat()]) == 0

    def test_schema_missing_passes(self, tmp_path: Path) -> None:
        """빈 DB 파일 — 앱이 아직 뜬 적이 없다. 막을 근거가 없다."""
        db = tmp_path / "itx.db"
        sqlite3.connect(db).close()
        assert deploy_guard.main([str(db)]) == 0
