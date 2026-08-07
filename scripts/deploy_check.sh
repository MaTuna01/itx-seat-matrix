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
#
# ★ **종료 코드가 판정이다** (#22, D-51). `✗`가 하나라도 나오면 1로 끝난다 — CD 워크플로가
#   배포 직후 이걸 돌려 실패하면 직전 이미지로 자동 롤백한다. `!`(경고)는 0을 유지한다:
#   경고까지 배포 실패로 치면 "이미지 아키텍처 ?" 같은 사소한 것에 롤백이 걸린다.
#   기존 항목의 문구·순서는 그대로 두고 **맨 끝에 판정 한 줄만 늘었다** — 출근길에 폰으로
#   보던 화면이 그대로여야 하기 때문이다.

set -u

C_NAME="${C_NAME:-itx}"
OK="✓"
NG="✗"
WARN="!"

# 치명 항목 개수. 아래 `fails`(폴링 틱 실패 건수)와 이름이 겹치지 않게 한다
ng_count=0

hdr() { printf '\n\033[1m── %s\033[0m\n' "$1"; }
say() { printf '  %s %s\n' "$1" "$2"; }
# `ng…` 대신 이걸 쓴다. 찍는 것은 같고 카운터만 오른다
ng() { say "${NG}" "$1"; ng_count=$((ng_count + 1)); }

# ── 1. 컨테이너 ──────────────────────────────────────────────────────
hdr "컨테이너"
if ! command -v docker >/dev/null 2>&1; then
  ng "docker가 없다"
  exit 1
fi

state=$(docker inspect --format '{{.State.Status}}' "$C_NAME" 2>/dev/null || echo "absent")
health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$C_NAME" 2>/dev/null || echo "none")
restarts=$(docker inspect --format '{{.RestartCount}}' "$C_NAME" 2>/dev/null || echo "?")

if [ "$state" = "running" ]; then
  say "$OK" "상태: running (health=$health, 재시작 ${restarts}회)"
else
  ng "상태: $state — 컨테이너가 돌지 않는다. docker compose logs app 을 봐라"
fi

# 재시작이 잦으면 OOM이다. nano는 0.5GB — 스왑 없이는 새벽에 잡아먹힌다 (12절)
if [ "$restarts" != "?" ] && [ "$restarts" -gt 3 ] 2>/dev/null; then
  # 우분투는 dmesg_restrict가 기본이라 일반 사용자로는 dmesg가 비어 보인다 — sudo 로 봐야 한다
  say "$WARN" "재시작 ${restarts}회 — OOM 의심. 아래 스왑 항목과 'sudo dmesg | grep -i oom'을 확인해라"
fi

oom=$(docker inspect --format '{{.State.OOMKilled}}' "$C_NAME" 2>/dev/null || echo "?")
[ "$oom" = "true" ] && ng "직전 종료가 OOMKilled다 — 스왑을 먼저 확인해라"

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
  *) ng "워커 설정을 확인해라 (2개면 폴링·알림이 중복 발사된다, D-17): $cmd" ;;
esac

# (c) 스왑 2GB
swap_kb=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
swap_mb=$((swap_kb / 1024))
if [ "$swap_mb" -ge 1900 ]; then
  say "$OK" "스왑 ${swap_mb}MB"
else
  ng "스왑 ${swap_mb}MB — 2GB를 만들어라 (DEPLOY.md '스왑'). 없으면 새벽에 OOM이 컨테이너를 잡는다"
fi

# (d) 퍼블리시가 루프백으로 묶여 있는가. 0.0.0.0이면 보안그룹만 믿는 상태가 된다
binding=$(docker inspect --format '{{range $p, $c := .NetworkSettings.Ports}}{{range $c}}{{$p}}->{{.HostIp}}:{{.HostPort}} {{end}}{{end}}' "$C_NAME" 2>/dev/null || echo "")
case "$binding" in
  *"127.0.0.1"*) say "$OK" "포트 퍼블리시: $binding" ;;
  "") say "$WARN" "퍼블리시된 포트가 없다" ;;
  *) ng "포트가 루프백 밖으로 열려 있다: $binding" ;;
esac

# ── 3. 앱 응답 ───────────────────────────────────────────────────────
hdr "앱 응답"
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/healthz || echo "000")
  if [ "$code" = "200" ]; then
    say "$OK" "GET /healthz → 200"
  else
    ng "GET /healthz → $code"
  fi
else
  say "$WARN" "curl이 없어 건너뜀 (sudo apt-get install -y curl)"
fi

# ── 4. Tailscale ─────────────────────────────────────────────────────
hdr "Tailscale"
if command -v tailscale >/dev/null 2>&1; then
  # `tailscale status --json` 은 들여쓴 JSON 을 낸다 — `"BackendState": "Running"` 처럼
  # 콜론 뒤에 공백이 있다. 공백을 허용하지 않으면 매칭이 실패해 "상태를 읽을 수 없다"가 뜬다
  # (실제로 첫 배포에서 이 오탐이 났다).
  ts_json=$(tailscale status --json 2>/dev/null || true)
  ts_state=$(printf '%s' "$ts_json" | grep -o '"BackendState": *"[^"]*"' | head -1 | cut -d'"' -f4)
  [ -n "${ts_state:-}" ] && say "$OK" "BackendState: $ts_state" || say "$WARN" "상태를 읽을 수 없다"
  serve=$(tailscale serve status 2>&1 | head -5)
  if printf '%s' "$serve" | grep -q "127.0.0.1:8000"; then
    printf '%s\n' "$serve" | sed 's/^/    /'
  else
    ng "serve가 8000을 프록시하지 않는다 — sudo tailscale serve --bg 8000"
    printf '%s\n' "$serve" | sed 's/^/    /'
  fi
  # key expiry가 켜져 있으면 반년 뒤 조용히 끊긴다 (12절).
  # ★ 이 노드(Self)만 본다 — JSON 에는 피어(아이폰·맥)도 들어 있어서 전체를 grep 하면
  #   남의 expiry 때문에 오탐이 난다. "Peer" 앞까지가 Self 구역이다.
  if printf '%s' "${ts_json%%\"Peer\":*}" | grep -q '"KeyExpiry"'; then
    say "$WARN" "이 노드에 key expiry가 남아 있다 — admin 콘솔에서 비활성화해라 (안 하면 반년 뒤 조용히 끊긴다)"
  fi
else
  ng "tailscale이 없다"
fi

# ── 5. 스케줄러가 실제로 도는가 (D-39 로그) ──────────────────────────
hdr "스케줄러 (최근 10분 로그)"
logs=$(docker logs --since 10m "$C_NAME" 2>&1 || echo "")
if [ -z "$logs" ]; then
  say "$WARN" "최근 10분 로그가 비어 있다"
else
  ticks=$(printf '%s' "$logs" | grep -c "폴링 틱" || true)
  fails=$(printf '%s' "$logs" | grep -c "폴링 틱 실패" || true)

  # 기동 로그는 **전체 로그**에서 본다. 10분 창으로만 보면 컨테이너가 오래 떠 있는 정상
  # 상태에서 0건이 되고, 그때마다 경고가 떠서 진짜 신호를 무시하게 된다 (실제로 그랬다).
  # `grep -m1 -q`라 첫 줄에서 끝난다 — 로그가 커도 비용이 없다.
  if docker logs "$C_NAME" 2>&1 | grep -m1 -q "폴링 스케줄러 시작"; then
    started_at=$(docker inspect --format '{{.State.StartedAt}}' "$C_NAME" 2>/dev/null | cut -c1-19)
    say "$OK" "스케줄러 기동 확인 (컨테이너 시작 ${started_at:-?} UTC)"
  else
    ng "기동 로그가 없다 — SCHEDULER_ENABLED / LOG_LEVEL 을 확인해라 (D-39)"
  fi

  say "·" "최근 10분: 폴링 틱 ${ticks}건 / 틱 실패 ${fails}건"

  # 틱 0건은 대개 정상이다 — `TickReport.__bool__`이 polled/expired/skipped 가 전부 비면
  # False라서, **조회할 구독이 도래하지 않은 틱은 로그를 남기지 않는다**
  # (app/scheduler/poller.py). 그래서 0건일 때는 설정을 대신 확인한다.
  if [ "$ticks" = "0" ]; then
    env_line=$(docker exec "$C_NAME" sh -c 'echo "$SCHEDULER_ENABLED|$LOG_LEVEL|$ADAPTER"' 2>/dev/null || echo "?|?|?")
    sched=${env_line%%|*}
    rest=${env_line#*|}
    level=${rest%%|*}
    adapter=${rest#*|}
    case "$sched" in
      true|True|1) : ;;
      *) ng "SCHEDULER_ENABLED=$sched — 알림이 아예 오지 않는다" ;;
    esac
    case "$level" in
      INFO|DEBUG|info|debug) : ;;
      *) say "$WARN" "LOG_LEVEL=$level — 폴링 틱 로그가 안 남아 검증이 불가능하다 (D-39)" ;;
    esac
    [ "$adapter" = "korail2" ] || say "$WARN" "ADAPTER=$adapter — mock이면 가짜 좌석으로 알림이 온다"
    say "·" "틱 로그 0건은 조회할 구독이 도래하지 않았다는 뜻이다 (설정은 위에서 확인했다)"
  fi
  [ "$fails" != "0" ] && ng "틱 실패가 있다 — docker compose logs app | grep -A20 '폴링 틱 실패'"
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
    say "$WARN" "$db 소유자가 ${owner}다 — 컨테이너는 uid 1000으로 돈다. sudo chown -R 1000:1000 data"
  fi
else
  ng "$db 가 없다 — 개발 DB를 옮겼는지 확인해라 (DEPLOY.md '데이터 이관')"
fi

# ── 7. 디스크 ────────────────────────────────────────────────────────
hdr "디스크"
df -h / | tail -1 | sed 's/^/  /'
say "·" "찼을 때 먼저 죽는 것은 SQLite 쓰기다. docker image prune -a 로 정리한다"

# ── 판정 ─────────────────────────────────────────────────────────────
printf '\n'
if [ "$ng_count" -eq 0 ]; then
  say "$OK" "치명 항목 없음"
else
  say "$NG" "치명 항목 ${ng_count}개 — 위의 ✗ 를 봐라"
fi
printf '\n'

[ "$ng_count" -eq 0 ] || exit 1
