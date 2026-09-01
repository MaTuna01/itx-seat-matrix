"""정차역 캐시 자동 재적재 (D-58, 이슈 #76).

시간은 전부 now 주입 — sleep/실 시계 금지 (CLAUDE.md 테스트 규칙).
네트워크는 fetch를 stub해 격리한다 (실 API 루프 금지, 규칙 10).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.adapters.train_run_info import (
    NoDataForDay,
    apply_day,
    reload_needed,
    reload_train_stops,
)
from app.domain.models import KST
from app.storage import train_stops as stop_repo
from app.storage.db import get_conn, init_db
from app.storage.train_stops import (
    count_trains,
    freshness,
    latest_source_run_ymd,
)


NOW = datetime(2026, 9, 2, 6, 5, tzinfo=KST)
YESTERDAY = NOW.date() - timedelta(days=1)  # 2026-09-01


# ──────────────────────────────────────────────────────────────
# reload_needed — 게이트 (06:05/12:05/기동 3회 호출 멱등의 근거)
# ──────────────────────────────────────────────────────────────


class TestReloadNeeded:
    def test_캐시가_비면_필요하다(self):
        assert reload_needed(None, NOW) is True

    def test_D_1보다_오래됐으면_필요하다(self):
        # 2026-08-30 실적은 NOW(9/2)에서 D-3 → 재적재 필요
        assert reload_needed(date(2026, 8, 30), NOW) is True

    def test_D_1은_스킵한다(self):
        # 어제 실적이면 이미 최신 (다음 스케줄이 D-1 실적을 노린다)
        assert reload_needed(YESTERDAY, NOW) is False

    def test_오늘_실적이면_스킵(self):
        # 이론상 없는 경우지만 게이트는 안전 방향으로 스킵
        assert reload_needed(NOW.date(), NOW) is False


# ──────────────────────────────────────────────────────────────
# apply_day — 트랜잭션 + 퍼지 (이슈 #75 원인 재발 방지)
# ──────────────────────────────────────────────────────────────


def _row(seq: int, name: str, run_ymd: date, dep_hour: int) -> stop_repo.StopRow:
    dep = datetime(run_ymd.year, run_ymd.month, run_ymd.day, dep_hour, 0, tzinfo=KST)
    return stop_repo.StopRow(
        seq=seq,
        station_name=name,
        station_code=None,
        stop_type="시발" if seq == 1 else "여객승하차",
        arrival=None if seq == 1 else dep - timedelta(minutes=1),
        departure=dep,
        run_ymd=run_ymd,
    )


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """빈 DB에 마이그레이션만 적용해서 준다. mark_usable이 없는 역은 자동 생성한다."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "reload.db"))
    init_db()
    with get_conn() as c:
        yield c


class TestApplyDay:
    def test_저장_후_새_열차가_보인다(self, conn):
        by_train = {
            "4202": [_row(1, "천안", YESTERDAY, 7), _row(2, "서울", YESTERDAY, 8)],
        }
        stats = apply_day(conn, by_train, run_ymd=YESTERDAY, now=NOW, max_age_days=7)
        assert stats.trains == 1
        assert count_trains(conn) == 1
        assert freshness(conn, "4202") == YESTERDAY

    def test_퍼지가_컷오프보다_오래된_열차만_지운다(self, conn):
        old_ymd = date(2026, 8, 20)  # NOW(9/2)에서 13일 전 — 컷오프 8/26보다 오래됨
        keep_ymd = date(2026, 8, 26)  # 정확히 컷오프 = 유지 (엄격 부등호)
        # 오래된 데이터 두 편을 미리 심는다
        stop_repo.save_stops(conn, "OLD1", [_row(1, "천안", old_ymd, 7)], now=NOW)
        stop_repo.save_stops(conn, "OLD2", [_row(1, "천안", old_ymd, 7)], now=NOW)
        stop_repo.save_stops(conn, "BOUND", [_row(1, "천안", keep_ymd, 7)], now=NOW)

        by_train = {"NEW": [_row(1, "천안", YESTERDAY, 7), _row(2, "서울", YESTERDAY, 8)]}
        stats = apply_day(conn, by_train, run_ymd=YESTERDAY, now=NOW, max_age_days=7)

        remaining = stop_repo.known_train_numbers(conn)
        assert "OLD1" not in remaining and "OLD2" not in remaining
        assert "BOUND" in remaining  # 컷오프 정확일은 유지
        assert "NEW" in remaining
        # 각 오래된 열차 = 1행씩 → 총 2행 퍼지
        assert stats.purged == 2

    def test_중간_오류시_옛_캐시가_유지된다(self, conn, monkeypatch):
        """`apply_day`의 명시적 트랜잭션 롤백 검증.

        저장 도중 예외가 나면 이전 캐시가 그대로 남아 폴 틱이 '정차역 없음'을 보지
        않아야 한다 (이 문제가 정확히 자동커밋의 위험이었다).
        """
        # 기존 캐시를 심는다
        stop_repo.save_stops(
            conn, "EXIST",
            [_row(1, "천안", YESTERDAY, 7), _row(2, "서울", YESTERDAY, 8)],
            now=NOW,
        )
        assert count_trains(conn) == 1

        # save_stops를 두 번째 열차에서 폭발시킨다
        real_save = stop_repo.save_stops
        calls = {"n": 0}

        def flaky(c, tno, rows, *, now):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated failure")
            real_save(c, tno, rows, now=now)

        monkeypatch.setattr(
            "app.adapters.train_run_info.stop_repo.save_stops", flaky
        )

        by_train = {
            "A": [_row(1, "천안", YESTERDAY, 7)],
            "B": [_row(1, "천안", YESTERDAY, 7)],
        }
        with pytest.raises(RuntimeError):
            apply_day(conn, by_train, run_ymd=YESTERDAY, now=NOW, max_age_days=7)

        # 롤백 후: 기존 EXIST 열차는 그대로, A/B 어느 것도 남지 않았어야 한다
        remaining = stop_repo.known_train_numbers(conn)
        assert "EXIST" in remaining
        assert "A" not in remaining and "B" not in remaining
        assert count_trains(conn) == 1


# ──────────────────────────────────────────────────────────────
# reload_train_stops — fetch 스텁으로 격리 (실 API 금지)
# ──────────────────────────────────────────────────────────────


class TestReloadTrainStops:
    def test_빈_실적이면_NoDataForDay(self, monkeypatch, conn):
        monkeypatch.setattr(
            "app.adapters.train_run_info.fetch_day", lambda run_ymd, key: []
        )
        with pytest.raises(NoDataForDay):
            reload_train_stops(
                run_ymd=YESTERDAY, key="stub", now=NOW, max_age_days=7,
            )

    def test_fetch_결과가_적재된다(self, monkeypatch, conn):
        raw = [
            {
                "trn_no": "4202", "trn_run_sn": "1",
                "stn_nm": "천안", "stn_cd": "3900061", "stop_se_nm": "시발",
                "trn_arvl_dt": None, "trn_dptre_dt": "2026-09-01 06:36:00.0",
            },
            {
                "trn_no": "4202", "trn_run_sn": "2",
                "stn_nm": "서울", "stn_cd": None, "stop_se_nm": "종착",
                "trn_arvl_dt": "2026-09-01 08:00:00.0", "trn_dptre_dt": None,
            },
        ]
        monkeypatch.setattr(
            "app.adapters.train_run_info.fetch_day", lambda run_ymd, key: raw
        )
        stats = reload_train_stops(
            run_ymd=YESTERDAY, key="stub", now=NOW, max_age_days=7,
        )
        assert stats.trains == 1
        with get_conn() as c:
            assert latest_source_run_ymd(c) == YESTERDAY


# ──────────────────────────────────────────────────────────────
# 스케줄러 잡 등록 — 키 유무 스모크
# ──────────────────────────────────────────────────────────────


class TestSchedulerJobRegistration:
    async def test_키_없으면_재적재_잡은_등록되지_않는다(self, monkeypatch, tmp_path):
        # scheduler_enabled=True로 두고 재적재 키만 비운다
        monkeypatch.setenv("DB_PATH", str(tmp_path / "sched.db"))
        monkeypatch.setenv("SCHEDULER_ENABLED", "true")
        monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "")
        # get_settings는 conftest autouse가 매 테스트 캐시를 지운다
        from app.config import get_settings
        get_settings.cache_clear()
        init_db()

        from app.scheduler.service import PollerService
        svc = PollerService()
        try:
            svc.start()
            ids = {j.id for j in svc._scheduler.get_jobs()}
            assert "poll_subscriptions" in ids
            assert "reload_train_stops" not in ids
            assert "reload_train_stops_catchup" not in ids
        finally:
            svc.shutdown()

    async def test_키가_있으면_재적재_잡과_캐치업이_등록된다(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "sched.db"))
        monkeypatch.setenv("SCHEDULER_ENABLED", "true")
        monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "test-key-value")
        from app.config import get_settings
        get_settings.cache_clear()
        init_db()

        from app.scheduler.service import PollerService
        svc = PollerService()
        try:
            svc.start()
            ids = {j.id for j in svc._scheduler.get_jobs()}
            assert {"poll_subscriptions", "reload_train_stops", "reload_train_stops_catchup"} <= ids
        finally:
            svc.shutdown()
