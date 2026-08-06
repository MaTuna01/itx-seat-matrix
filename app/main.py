"""FastAPI 앱 조립 (PLAN.md 4절).

컨테이너 1개, **uvicorn `--workers 1` 고정** — APScheduler가 인프로세스라
2개면 폴링·알림이 중복 발사된다 (D-17).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, me, presets, push, stations, subscriptions, trains
from app.config import Settings, get_settings
from app.scheduler.service import PollerService
from app.storage.db import init_db

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def configure_logging(settings: Settings) -> None:
    """앱 로거에 핸들러를 붙인다 (→ D-39).

    **uvicorn은 `uvicorn`/`uvicorn.error`/`uvicorn.access` 로거만 설정하고 root는
    비워둔다.** 그 상태에서 `logging.getLogger("app.…")`의 INFO는 어디에도 나오지
    않고, WARNING 이상만 `logging.lastResort`를 타고 포맷 없이 stderr로 새어나온다.

    그래서 `scheduler/service.py`의 "폴링 스케줄러 시작"·"폴링 틱: 조회 N · 알림 …"이
    한 줄도 보이지 않았다 — **스케줄러가 도는지 눈으로 확인할 방법이 없었다.**
    맥에서는 화면으로 대신 확인할 수 있었지만, 배포 후에는 `docker compose logs`가
    관측 수단의 전부다 (12절).

    `force=True`는 uvicorn이 root를 비워둔 채로 남긴 상태를 확정적으로 덮기 위한 것이고,
    두 번 호출돼도 핸들러가 겹치지 않게 한다.
    """
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        force=True,
    )
    # APScheduler는 틱마다 "Running job"/"executed successfully" 두 줄을 INFO로 찍는다.
    # 30초 틱이면 하루 5천 줄이 쌓여 **정작 봐야 할 "폴링 틱: …"을 덮는다** — 출근길에
    # 로그를 읽어야 하는 용도와 정면으로 어긋난다. 잡이 죽는 경우는 WARNING 이상으로 남는다.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # uvicorn이 로깅을 세팅한 뒤(앱 임포트보다 먼저다) 여기서 덮어쓴다.
    configure_logging(get_settings())
    init_db()
    poller = PollerService()
    poller.start()
    try:
        yield
    finally:
        poller.shutdown()


app = FastAPI(title="ITX 자유석 좌석 매트릭스", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(me.router)
app.include_router(stations.router)
app.include_router(trains.router)
app.include_router(subscriptions.router)
app.include_router(presets.router)
app.include_router(push.router)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# 프론트(Vite 빌드 산출물)를 같은 앱에서 서빙한다. 개발 중에는 vite dev server를 쓴다.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
