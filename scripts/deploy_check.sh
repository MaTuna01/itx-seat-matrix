#!/usr/bin/env bash
# 배포 상태를 한 번에 확인한다 (PLAN.md 12절, DEPLOY.md).
#
# EC2 호스트의 배포 디렉터리(docker-compose.yml이 있는 곳)에서 실행한다:
#
#     ./scripts/deploy_check.sh
#
# 출근길에 폰으로 SSH해서 "왜 알림이 안 오지"를 볼 때를 위한 것이다 — 12절의
# 조용히 틀리는 항목들(스왑 / --workers 1 / 바인딩 주소 / serve)을 한 화면에 모은다.
# **시크릿은 출력하지 않는다** — .env의 값을 읽지 않고 키가 있는지만 본다.

set -u

C_NAME="${C_NAME:-itx}"
OK="✓"
NG="✗"
WARN="!"

hdr() { printf '\n\033[1m── %s\033[0m\n' "$1"; }
say() { printf '  %s %s\n' "$1" "$2"; }

# ── 1. 컨테이너 ──────────────────────────────────────────────────────
hdr "컨테이너"
if ! command -v docker >/dev/null 2>&1; then
  say "$NG" "docker가 없다"
  exit 1
fi

state=$(docker inspect --format '{{.State.Status}}' "$C_NAME" 2>/dev/null || echo "absent")
health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$C_NAME" 2>/dev/null || echo "none")
restarts=$(docker inspect --format '{{.RestartCount}}' "$C_NAME" 2>/dev/null || echo "?")

if [ "$state" = "running" ]; then
  say "$OK" "상태: running (health=$health, 재시작 $restarts회)"
else
  say "$NG" "상태: $state — 컨테이너가 돌지 않는다. docker compose logs app 을 봐라"
fi

# 재시작이 잦으면 OOM이다. nano는 0.5GB — 스왑 없이는 새벽에 잡아먹힌다 (12절)
if [ "$restarts" != "?" ] && [ "$restarts" -gt 3 ] 2>/dev/null; then
  # 우분투는 dmesg_restrict가 기본이라 일반 사용자로는 dmesg가 비어 보인다 — sudo 로 봐야 한다
  say "$WARN" "재시작 $restarts회 — OOM 의심. 아래 스왑 항목과 'sudo dmesg | grep -i oom'을 확인해라"
fi

oom=$(docker inspect --format '{{.State.OOMKilled}}' "$C_NAME" 2>/dev/null || echo "?")
[ "$oom" = "true" ] && say "$NG" "직전 종료가 OOMKilled다 — 스왑을 먼저 확인해라"

# ── 2. 조용히 틀리는 3개 (12절) ──────────────────────────────────────
hdr "12절 체크 (조용히 틀리는 것들)"

# (a) arm64 이미지인가. x86 이미지는 애초에 뜨지 않으니 여기까지 왔으면 통과지만,
#     이미지를 갈아끼운 뒤 확인용으로 남긴다
img_arch=$(docker inspect --format '{{.Architecture}}' "$(docker inspect --format '{{.Image}}' "$C_NAME" 2>/dev/null)" 2>/dev/null || echo "?")
host_arch=$(uname -m)
if [ "$img_arch" = "arm64" ]; then
  say "$OK" "이미지 아키텍처: $img_arch (호스트 $host_arch)"
else
  say "$WARN" "이미지 아키텍처: $img_arch (호스트 $host_arch)"
fi

# (b) uvicorn --workers 1. 2개면 알림이 중복 발사된다 (D-17)
cmd=$(docker inspect --format '{{range .Config.Cmd}}{{.}} {{end}}' "$C_NAME" 2>/dev/null || echo "")
case "$cmd" in
  *"--workers 1"*) say "$OK" "uvicorn --workers 1" ;;
  *) say "$NG" "워커 설정을 확인해라 (2개면 폴링·알림이 중복 발사된다, D-17): $cmd" ;;
esac

# (c) 스왑 2GB
swap_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
swap_mb=$((swap_kb / 1024))
if [ "$swap_mb" -ge 1900 ]; then
  say "$OK" "스왑 ${swap_mb}MB"
else
  say "$NG" "스왑 ${swap_mb}MB — 2GB를 만들어라 (DEPLOY.md '스왑'). 없으면 새벽에 OOM이 컨테이너를 잡는다"
fi

# (d) 퍼블리시가 루프백으로 묶여 있는가. 0.0.0.0이면 보안그룹만 믿는 상태가 된다
binding=$(docker inspect --format '{{range $p, $c := .NetworkSettings.Ports}}{{range $c}}{{$p}}->{{.HostIp}}:{{.HostPort}} {{end}}{{end}}' "$C_NAME" 2>/dev/null || echo "")
case "$binding" in
  *"127.0.0.1"*) say "$OK" "포트 퍼블리시: $binding" ;;
  "") say "$WARN" "퍼블리시된 포트가 없다" ;;
  *) say "$NG" "포트가 루프백 밖으로 열려 있다: $binding" ;;
esac

# ── 3. 앱 응답 ───────────────────────────────────────────────────────
hdr "앱 응답"
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/healthz || echo "000")
  if [ "$code" = "200" ]; then
    say "$OK" "GET /healthz → 200"
  else
    say "$NG" "GET /healthz → $code"
  fi
else
  say "$WARN" "curl이 없어 건너뜀 (sudo apt-get install -y curl)"
fi

# ── 4. Tailscale ─────────────────────────────────────────────────────
hdr "Tailscale"
if command -v tailscale >/dev/null 2>&1; then
  ts_state=$(tailscale status --json 2>/dev/null | grep -o '"BackendState":"[^"]*"' | head -1 | cut -d'"' -f4)
  [ -n "${ts_state:-}" ] && say "$OK" "BackendState: $ts_state" || say "$WARN" "상태를 읽을 수 없다"
  serve=$(tailscale serve status 2>&1 | head -5)
  if printf '%s' "$serve" | grep -q "127.0.0.1:8000"; then
    printf '%s\n' "$serve" | sed 's/^/    /'
  else
    say "$NG" "serve가 8000을 프록시하지 않는다 — sudo tailscale serve --bg 8000"
    printf '%s\n' "$serve" | sed 's/^/    /'
  fi
  # key expiry가 켜져 있으면 반년 뒤 조용히 끊긴다 (12절)
  if tailscale status --json 2>/dev/null | grep -q '"KeyExpiry"'; then
    say "$WARN" "이 노드에 key expiry가 남아 있다 — admin 콘솔에서 비활성화해라 (안 하면 반년 뒤 조용히 끊긴다)"
  fi
else
  say "$NG" "tailscale이 없다"
fi

# ── 5. 스케줄러가 실제로 도는가 (D-39 로그) ──────────────────────────
hdr "스케줄러 (최근 10분 로그)"
logs=$(docker logs --since 10m "$C_NAME" 2>&1 || echo "")
if [ -z "$logs" ]; then
  say "$WARN" "최근 10분 로그가 비어 있다"
else
  ticks=$(printf '%s' "$logs" | grep -c "폴링 틱" || true)
  starts=$(printf '%s' "$logs" | grep -c "폴링 스케줄러 시작" || true)
  fails=$(printf '%s' "$logs" | grep -c "폴링 틱 실패" || true)
  say "·" "폴링 틱 로그 ${ticks}건 / 스케줄러 시작 ${starts}건 / 틱 실패 ${fails}건"
  if [ "$ticks" = "0" ] && [ "$starts" = "0" ]; then
    say "$WARN" "둘 다 0이다. 구독이 없거나(정상) LOG_LEVEL이 INFO가 아니거나 SCHEDULER_ENABLED=false다"
  fi
  [ "$fails" != "0" ] && say "$NG" "틱 실패가 있다 — docker compose logs app | grep -A20 '폴링 틱 실패'"
  printf '%s' "$logs" | grep -E "폴링 틱|매진|FETCH_FAILED|SECRET_KEY|MACRO ERROR" | tail -8 | sed 's/^/    /'
fi

# ── 6. DB 파일 ───────────────────────────────────────────────────────
hdr "DB"
db="./data/itx.db"
if [ -f "$db" ]; then
  # uid 1000이 아니면 컨테이너가 쓰지 못한다 ("readonly database")
  owner=$(stat -c '%u:%g' "$db" 2>/dev/null || stat -f '%u:%g' "$db" 2>/dev/null || echo "?")
  size=$(du -h "$db" | cut -f1)
  if [ "$owner" = "1000:1000" ]; then
    say "$OK" "$db ($size, uid $owner)"
  else
    say "$WARN" "$db 소유자가 $owner다 — 컨테이너는 uid 1000으로 돈다. sudo chown -R 1000:1000 data"
  fi
else
  say "$NG" "$db 가 없다 — 개발 DB를 옮겼는지 확인해라 (DEPLOY.md '데이터 이관')"
fi

# ── 7. 디스크 ────────────────────────────────────────────────────────
hdr "디스크"
df -h / | tail -1 | sed 's/^/  /'
say "·" "찼을 때 먼저 죽는 것은 SQLite 쓰기다. docker image prune -a 로 정리한다"

printf '\n'
