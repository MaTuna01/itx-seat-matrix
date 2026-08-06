# syntax=docker/dockerfile:1
#
# ITX 자유석 좌석 매트릭스 — 단일 컨테이너 (PLAN.md 12절, 15절)
#
# ★ **arm64 이미지여야 한다.** 배포 대상은 t4g.nano(Graviton)이고 x86 이미지는
#   아예 뜨지 않는다 — `exec format error`로 죽는다. Apple Silicon 맥이나 인스턴스
#   자신에서 빌드하면 자동으로 arm64가 된다. Intel 맥에서 빌드할 때만 함정이고,
#   그때는 `--platform linux/arm64`가 필수다 (DEPLOY.md "빌드 호스트" 절).
#
# ★ **uvicorn `--workers 1` 고정.** APScheduler가 인프로세스라 2개면 같은 구독을
#   두 프로세스가 폴링해 알림이 중복 발사된다. `next_poll_at` 포인터는 재시작에는
#   강하지만 동시 실행에는 방어가 없다 (→ D-17, app/scheduler/service.py 상단).

# ── 1단계: 프론트 빌드 ────────────────────────────────────────────────
# `web/dist`는 gitignore 대상이라 저장소에 없다 — 이미지 안에서 만든다.
# FastAPI가 이 산출물을 StaticFiles로 서빙한다 (10절, app/main.py).
FROM node:22-alpine AS web
WORKDIR /web
# 락파일만 먼저 복사한다 — 프론트 소스를 고쳐도 npm ci 레이어는 캐시에서 재사용된다
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ── 2단계: 파이썬 의존성 ──────────────────────────────────────────────
# 런타임 이미지에 uv·빌드 캐시를 남기지 않기 위해 venv만 통째로 넘긴다.
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

# UV_PYTHON: 이미지의 python을 쓴다. 지정하지 않으면 uv가 자기 파이썬을 따로
# 내려받아 이미지가 불필요하게 커진다. DOWNLOADS=never로 그 경로를 아예 막는다.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON=/usr/local/bin/python3.12
ENV UV_PYTHON_DOWNLOADS=never

WORKDIR /build
COPY pyproject.toml uv.lock ./
# --frozen: uv.lock 그대로 (배포 시점에 의존성을 다시 해석하지 않는다)
# --no-dev: pytest·openpyxl 등 dev 그룹 제외
RUN uv sync --frozen --no-dev

# ── 3단계: 런타임 ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# tzdata — **모든 datetime이 KST aware다** (CLAUDE.md 절대규칙 1). 시스템 tzdata가
# 없으면 `ZoneInfo("Asia/Seoul")`이 ZoneInfoNotFoundError로 죽는다. slim 이미지에
# 들어 있는지에 기대지 않고 명시적으로 설치한다.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# TZ를 맞춰두면 로그 타임스탬프도 KST가 되어 출근길 로그 대조가 편하다
# (logging은 aware datetime을 모르고 localtime을 쓴다).
ENV TZ=Asia/Seoul

# PYTHONUNBUFFERED: 끄지 않으면 `docker logs`가 한참 뒤에 뭉쳐 나온다 —
# 출근길에 실시간으로 봐야 하는 로그라 치명적이다.
ENV PATH=/opt/venv/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
COPY app/ ./app/
# 정차역 캐시 재적재(D-29)를 컨테이너 안에서 돌린다 — 서버에 python·uv를 따로 깔지 않는다.
# `docker compose exec app python scripts/load_train_stops.py`
COPY scripts/ ./scripts/
COPY --from=web /web/dist ./web/dist

# 비루트 실행. **uid를 1000으로 고정한다** — 호스트의 ec2-user가 uid 1000이라
# 바인드 마운트한 `data/`의 소유자와 맞아떨어진다. 어긋나면 SQLite가
# "attempt to write a readonly database"로 죽는다 (조용히 틀리진 않고 500으로 드러난다).
RUN groupadd -g 1000 app \
 && useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin app \
 && mkdir -p /app/data \
 && chown -R 1000:1000 /app
USER 1000:1000

EXPOSE 8000

# curl을 깔지 않기 위해 python으로 찍는다. compose의 재시작 정책과 함께
# "떴지만 응답은 못 하는" 상태를 잡아낸다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

# 컨테이너 내부는 0.0.0.0에 바인딩한다. **외부 노출은 여기서 막지 않는다** —
# compose가 `127.0.0.1:8000`으로만 퍼블리시하고, 그 앞은 호스트의 `tailscale serve`다 (12절).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
