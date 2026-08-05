"""FastAPI 앱 조립 (PLAN.md 4절).

컨테이너 1개, **uvicorn `--workers 1` 고정** — APScheduler가 인프로세스라
2개면 폴링·알림이 중복 발사된다 (D-17). Phase 1에는 아직 스케줄러가 없다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, me, presets, subscriptions, trains
from app.storage.db import init_db

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ITX 자유석 좌석 매트릭스", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(trains.router)
app.include_router(subscriptions.router)
app.include_router(presets.router)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# 프론트(Vite 빌드 산출물)를 같은 앱에서 서빙한다. 개발 중에는 vite dev server를 쓴다.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
