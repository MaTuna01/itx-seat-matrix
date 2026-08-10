"""DB 백업 규칙 (#60).

백업이 조용히 틀리는 방향은 하나뿐이지만 치명적이다 — **빈 파일을 올리고 성공했다고
기록하는 것.** 그러면 "백업이 있다"는 잘못된 안심을 얻고, 정작 필요할 때 아무것도 없다.
그래서 검증과 기록 순서를 테스트가 잠근다.

`scripts/`는 패키지가 아니므로 파일 경로로 적재한다 — `tests/test_deploy_guard.py`와 같다.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backup_db.py"
_spec = importlib.util.spec_from_file_location("backup_db", _PATH)
assert _spec and _spec.loader
backup_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup_db)

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 8, 10, 23, 40, tzinfo=KST)

# 실제 스키마의 부분집합이다. 백업 검증은 행 수만 본다
_DDL = """
CREATE TABLE user (id INTEGER PRIMARY KEY, email TEXT);
CREATE TABLE subscription (id INTEGER PRIMARY KEY, train_no TEXT);
CREATE TABLE station (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE train_stop (id INTEGER PRIMARY KEY, train_no TEXT);
CREATE TABLE push_device (id INTEGER PRIMARY KEY, endpoint TEXT);
"""


def _db(path: Path, *, users: int = 1, stations: int = 3, wal: bool = True) -> Path:
    conn = sqlite3.connect(path)
    if wal:
        # 실제 DB는 WAL이다 — 파일 복사가 안 되는 이유 (D-41)
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_DDL)
    conn.executemany(
        "INSERT INTO user (email) VALUES (?)", [(f"a{i}@b.c",) for i in range(users)]
    )
    conn.executemany(
        "INSERT INTO station (name) VALUES (?)", [(f"역{i}",) for i in range(stations)]
    )
    conn.commit()
    conn.close()
    return path


class TestS3Key:
    def test_one_per_day(self) -> None:
        """하루 1개 — 시각을 넣지 않는다. '하루 1개, 30일' 약속과 이름이 일치해야 한다."""
        assert backup_db.s3_key(NOW) == "itx-2026-08-10.db"

    def test_same_day_same_key(self) -> None:
        later = NOW.replace(hour=6, minute=5)
        assert backup_db.s3_key(later) == backup_db.s3_key(NOW)


class TestProblems:
    """비어 있으면 백업으로 인정하지 않는다."""

    def test_healthy(self) -> None:
        counts = {"user": 1, "station": 282, "subscription": 0, "push_device": 0}
        assert backup_db.problems(counts) == []

    def test_zero_subscriptions_is_fine(self) -> None:
        """구독·푸시 기기가 0인 것은 정상이다 — 막으면 안 된다."""
        assert backup_db.problems({"user": 1, "station": 5}) == []

    def test_empty_user_blocks(self) -> None:
        assert backup_db.problems({"user": 0, "station": 5}) != []

    def test_empty_station_blocks(self) -> None:
        assert backup_db.problems({"user": 1, "station": 0}) != []

    def test_missing_table_blocks(self) -> None:
        """스키마가 없는 DB — 앱이 뜬 적이 없다는 뜻이다."""
        assert backup_db.problems({"user": -1, "station": -1}) != []


class TestSnapshot:
    def test_wal_data_survives(self, tmp_path: Path) -> None:
        """★ `.backup`이 WAL에 있는 최신 커밋을 가져오는지 (D-41이 경고한 지점)."""
        src = _db(tmp_path / "itx.db")
        # 체크포인트 없이 추가 커밋 — 아직 -wal 쪽에 있을 수 있다
        conn = sqlite3.connect(src)
        conn.execute("INSERT INTO user (email) VALUES ('late@b.c')")
        conn.commit()
        conn.close()

        dest = tmp_path / "snap.db"
        backup_db.snapshot(src, dest)

        got = sqlite3.connect(dest)
        try:
            emails = [r[0] for r in got.execute("SELECT email FROM user")]
        finally:
            got.close()
        assert "late@b.c" in emails


class TestMain:
    """CLI — systemd 유닛이 보는 것은 종료 코드뿐이다."""

    def test_missing_db(self, tmp_path: Path) -> None:
        assert backup_db.main([str(tmp_path / "없다.db"), "--no-upload"]) == 1

    def test_no_s3_uri_fails(self, tmp_path: Path, monkeypatch) -> None:
        """업로드할 곳을 모르면 실패다 — 조용히 로컬에만 두고 성공하지 않는다."""
        monkeypatch.delenv("ITX_BACKUP_S3_URI", raising=False)
        db = _db(tmp_path / "itx.db")
        assert backup_db.main([str(db)]) == 1

    def test_verify_only_passes(self, tmp_path: Path) -> None:
        db = _db(tmp_path / "itx.db")
        assert backup_db.main([str(db), "--no-upload"]) == 0

    def test_empty_db_fails_verify(self, tmp_path: Path) -> None:
        db = _db(tmp_path / "itx.db", users=0)
        assert backup_db.main([str(db), "--no-upload"]) == 1

    def test_no_upload_does_not_stamp(self, tmp_path: Path) -> None:
        """★ 검증만 돌린 것이 '마지막 성공'으로 기록되면 안 된다.

        기록되면 `deploy_check.sh`가 낡음을 못 잡는다 — 손으로 예행 연습한 것이
        진짜 백업으로 위장된다.
        """
        db = _db(tmp_path / "itx.db")
        stamp = tmp_path / "last_success"
        assert backup_db.main([str(db), "--no-upload", "--stamp", str(stamp)]) == 0
        assert not stamp.exists()

    def test_stamp_written_on_success(self, tmp_path: Path, monkeypatch) -> None:
        """업로드가 성공한 뒤에만 기록한다."""
        db = _db(tmp_path / "itx.db")
        stamp = tmp_path / "last_success"
        monkeypatch.setattr(backup_db, "upload", lambda *a, **k: None)
        rc = backup_db.main(
            [str(db), "--s3-uri", "s3://b/p", "--stamp", str(stamp), "--now", NOW.isoformat()]
        )
        assert rc == 0
        assert stamp.read_text().strip() == NOW.isoformat()

    def test_upload_failure_leaves_no_stamp(self, tmp_path: Path, monkeypatch) -> None:
        """★ 업로드 실패가 성공으로 기록되면 백업이 없는 채로 안심하게 된다."""
        db = _db(tmp_path / "itx.db")
        stamp = tmp_path / "last_success"

        def boom(*a, **k):
            raise RuntimeError("네트워크 없음")

        monkeypatch.setattr(backup_db, "upload", boom)
        rc = backup_db.main([str(db), "--s3-uri", "s3://b/p", "--stamp", str(stamp)])
        assert rc == 1
        assert not stamp.exists()

    def test_temp_file_is_cleaned_up(self, tmp_path: Path, monkeypatch) -> None:
        """스냅샷 임시 파일이 남으면 평문에 가까운 사본이 디스크에 쌓인다."""
        db = _db(tmp_path / "itx.db")
        seen: list[Path] = []

        def capture(local, s3_uri, key):
            seen.append(Path(local))

        monkeypatch.setattr(backup_db, "upload", capture)
        backup_db.main(
            [str(db), "--s3-uri", "s3://b/p", "--stamp", str(tmp_path / "s")]
        )
        assert seen and not seen[0].exists()
