"""APScheduler 인프로세스 30초 틱 (PLAN.md 9절, D-17/D-19).

**uvicorn `--workers 1` 고정이 전제다.** 워커가 2개면 두 프로세스가 각자 스케줄러를
띄워 같은 구독을 동시에 폴링하고, 알림이 중복 발사된다. `next_poll_at` 포인터는
재시작에는 강하지만 **동시 실행에는 방어가 없다** — 두 틱이 같은 행을 읽고 각각
발송한 뒤 각각 포인터를 전진시키면 DB만 봐서는 아무 이상이 없어 보인다.

이 파일은 **실제 시계를 읽는 유일한 지점**이다 (`datetime.now(KST)`). 그 아래
`poller.run_tick`부터는 시간이 전부 인자로 흐른다 (D-21) — 그래서 테스트가 가능하다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from app.adapters.delay_zero import ZeroDelayAdapter
from app.adapters.notify import build_notifier
from app.adapters.train_run_info import (
    NoDataForDay,
    ReloadStats,
    reload_needed,
    reload_train_stops,
)
from app.config import Settings, get_settings
from app.domain.models import KST
from app.scheduler.poller import PollerDeps, run_tick
from app.storage.db import get_conn
from app.storage.train_stops import latest_source_run_ymd

log = logging.getLogger(__name__)

_JOB_ID = "poll_subscriptions"
_RELOAD_JOB_ID = "reload_train_stops"
_RELOAD_CATCHUP_ID = "reload_train_stops_catchup"


def build_deps(settings: Settings | None = None) -> PollerDeps:
    """어댑터 조립. env `ADAPTER=mock|korail2` 하나로 갈린다.

    개발·디버깅은 mock으로 한다 — 30초 틱이 실 API에 붙으면 호출 예절(CLAUDE.md 10)을
    순식간에 넘긴다. 이번 Phase에서 가장 위험한 지점이다.
    """
    settings = settings or get_settings()
    if settings.adapter == "korail2":
        from app.adapters.korail2_adapter import (  # noqa: PLC0415 — mock 경로를 korail2에 묶지 않는다
            get_korail2_adapter,
            get_korail2_delay_adapter,
        )

        port, delay_port = get_korail2_adapter(), get_korail2_delay_adapter()
    else:
        from app.adapters.korail_mock import MockKorailAdapter  # noqa: PLC0415

        port, delay_port = MockKorailAdapter(), ZeroDelayAdapter()

    return PollerDeps(port=port, delay_port=delay_port, notifier=build_notifier(settings))


class PollerService:
    """앱 수명주기에 매달린 스케줄러. `main.py`의 lifespan이 start/shutdown을 부른다."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._scheduler = AsyncIOScheduler(timezone=KST)
        self._deps = build_deps(self._settings)
        # 틱이 30초보다 오래 걸릴 수 있다 (조회 실패 시 30초×3 재시도). 겹쳐 돌면
        # 같은 구독을 두 번 폴링하므로 락으로 직렬화한다 — 늦는 것이 중복보다 낫다.
        self._lock = asyncio.Lock()

    async def tick(self) -> None:
        """APScheduler가 부르는 진입점. 여기서만 실제 시계를 읽는다."""
        if self._lock.locked():
            log.warning("직전 틱이 아직 돌고 있다 — 이번 틱을 건너뛴다")
            return
        async with self._lock:
            now = datetime.now(KST)
            try:
                report = await run_tick(self._deps, now=now)
            except Exception:  # noqa: BLE001 — 틱이 죽으면 잡이 조용히 멈춘다
                log.exception("폴링 틱 실패")
                return
            if report:
                log.info(
                    "폴링 틱: 조회 %s · 알림 %s · 만료 %s · 스킵 %s",
                    report.polled,
                    [a.kind.value for a in report.alerts],
                    report.expired,
                    report.skipped,
                )
            for note in report.notes:
                log.warning("%s", note)

    def start(self) -> None:
        if not self._settings.scheduler_enabled:
            log.warning("SCHEDULER_ENABLED=false — 자동 폴링을 시작하지 않는다")
            return
        self._scheduler.add_job(
            self.tick,
            "interval",
            seconds=self._settings.scheduler_interval_seconds,
            id=_JOB_ID,
            # 재시작 직후 밀린 틱을 몰아 실행하지 않는다. 지각한 폴 포인트 처리는
            # `resolve_poll`의 grace 2분이 이미 담당한다 (D-19) — 여기서 또 하면 이중이다
            coalesce=True,
            max_instances=1,
            misfire_grace_time=self._settings.scheduler_interval_seconds,
        )
        self._register_stops_reload()
        self._scheduler.start()
        log.info("폴링 스케줄러 시작 (%s초 간격)", self._settings.scheduler_interval_seconds)

    def _register_stops_reload(self) -> None:
        """정차역 캐시 일일 자동 재적재 (D-58, 이슈 #76).

        키가 없으면 조용히 건너뛴다 (mock/dev 환경에서 스케줄러 자체는 그대로 돈다).
        06:05·12:05 두 시각 + 기동 후 60초 캐치업 — 세 호출 모두 `reload_needed`
        게이트로 멱등이라 실제 네트워크는 첫 성공 한 번만.
        """
        if not self._settings.data_go_kr_service_key:
            log.warning(
                "DATA_GO_KR_SERVICE_KEY 미설정 — 정차역 캐시 자동 재적재를 시작하지 않는다 "
                "(mock/dev 환경에서 정상. 실 배포에서는 .env 확인)."
            )
            return
        hours = self._settings.stops_reload_hours
        self._scheduler.add_job(
            self.reload_stops,
            "cron",
            hour=hours,
            minute=self._settings.stops_reload_minute,
            id=_RELOAD_JOB_ID,
            coalesce=True,
            max_instances=1,
        )
        # 기동 캐치업 — 낮 배포/주말 수동 기동을 위한 60초 후 1회 실행
        self._scheduler.add_job(
            self.reload_stops,
            DateTrigger(run_date=datetime.now(KST) + timedelta(seconds=60)),
            id=_RELOAD_CATCHUP_ID,
            coalesce=True,
            max_instances=1,
        )
        log.info(
            "정차역 캐시 재적재 잡 등록 (cron hours=%s minute=%s, 기동 60초 후 캐치업)",
            hours, self._settings.stops_reload_minute,
        )

    async def reload_stops(self) -> None:
        """정차역 캐시 재적재 (D-58). 게이트 → fetch → apply_day.

        시계는 여기서만 읽는다 (service.py가 실 클록의 유일한 지점).
        실패는 로그만 — 알림 5종 불변(CLAUDE.md 규칙 6), FETCH_FAILED는 구독 단위(D-34).
        """
        now = datetime.now(KST)
        latest = await asyncio.to_thread(self._latest_source_ymd)
        if not reload_needed(latest, now):
            log.debug("정차역 캐시 최신(%s) — 재적재 스킵", latest)
            return

        run_ymd = now.date() - timedelta(days=1)
        settings = self._settings
        try:
            stats: ReloadStats = await asyncio.to_thread(
                reload_train_stops,
                run_ymd=run_ymd,
                key=settings.data_go_kr_service_key,
                now=now,
                max_age_days=settings.train_stop_max_age_days,
            )
        except NoDataForDay as exc:
            # 개편 첫날처럼 D-1 실적이 하루 늦게 공개되는 경우 — 다음 게이트 호출을 기다린다
            log.info("정차역 재적재: %s (다음 시각에 재시도)", exc)
            return
        except Exception:  # noqa: BLE001 — 잡이 죽으면 다음 스케줄이 없다
            log.exception("정차역 재적재 실패 (%s 실적)", run_ymd)
            return

        log.info(
            "정차역 캐시 재적재 완료: %s 실적 · 열차 %s편 · 역 %s개 · 퍼지 %s행",
            stats.run_ymd, stats.trains, stats.stations, stats.purged,
        )

    @staticmethod
    def _latest_source_ymd():
        with get_conn() as conn:
            return latest_source_run_ymd(conn)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
