# 배포 (AWS EC2 + Docker + Tailscale)

**PLAN.md 12절의 실행 절차서다.** 왜 t4g.nano인지, 왜 서울 리전인지, 왜 Tailscale인지는
12절과 17절(D-6, D-8, D-10, D-38)에 있다. 여기서는 그 결정을 **어떤 순서로 실행하는지**만 다룬다.

접근 경로는 **A(Tailscale serve) 유지**로 확정했다 (D-38). 공개 노출로 전환하려면 D-38의
전환 트리거를 먼저 읽어라 — 오리진이 바뀌면 기기마다 알림을 다시 켜야 한다 (D-34).

---

## 0. 3대가 관여한다 — 무엇이 어디서 나오는지

이 프로젝트의 배포는 한 대에서 끝나지 않는다. 시작 전에 이걸 확실히 해둬야 빠뜨리지 않는다.

| 머신 | 역할 | 이유 |
|---|---|---|
| **M4 MacBook Air** (arm64) | **작업 거점 — 빌드와 나머지 전부** | t4g는 Graviton(arm64). Apple Silicon에서 빌드하면 네이티브 arm64가 나온다 |
| **Intel iMac** (x86_64) | **`data/itx.db` 원본 제공 — 이것만** | 실 코레일 자격증명과 푸시 기기 등록이 이 DB에만 있다 |
| **EC2 t4g.nano** (Ubuntu 24.04 LTS, arm64) | 실행 | 24시간 깨어 있어야 30초 틱이 멈추지 않는다 (Phase 3이 열린 채로 남은 이유). SSH 사용자는 `ubuntu` (D-42) |

**작업은 M4에서 하고, 아이맥 앞에는 5절(DB 이관) 때 한 번만 앉는다.** 저장소는 M4에서 새로
clone하고, `.env`는 아이맥에서 긁어오지 않고 **별도 보관본(노션 등)에서 손으로 만든다**(4절) —
대신 `SECRET_KEY` 지문을 대조해야 한다.

> **M4에서 `ssh imac`은 안 된다.** macOS는 Tailscale SSH의 **서버가 될 수 없고**(리눅스 전용),
> 맥의 "원격 로그인"을 켜지 않았다면 tailnet 안에서도 22번이 닫혀 있다. 그래서 DB는 아이맥이
> **클라이언트가 되어 EC2로 직접 밀어 넣는다** (5절 ②). EC2는 리눅스라 Tailscale SSH가 되므로
> M4·아이맥 → EC2 방향은 전부 열려 있다.

> **Intel iMac에서 배포 이미지를 빌드하지 마라.** `--platform linux/arm64`를 빠뜨리면 x86
> 이미지가 나와 EC2에서 `exec format error`로 죽고(12절이 경고하는 함정), 붙여도 QEMU
> 에뮬레이션에서 `npm ci` + vite 빌드가 몇 배로 느려진다. 개발기로는 계속 쓴다.

**M4도 tailnet에 넣어라.** 이미지 전송과 파일 복사를 전부 tailnet 위에서 한다.
(현재 tailnet: `imac`, `iphone-14-pro`. 배포 후 `itx`가 추가된다.)

---

## 1. EC2 프로비저닝 (콘솔 — **소유자가 직접 한다**)

실 과금이므로 이 절은 사람이 실행한다. 리전 **ap-northeast-2(서울)**.

EC2 → **인스턴스 시작**:

| 항목 | 값 | 주의 |
|---|---|---|
| 이름 | `itx` | |
| AMI | **Ubuntu Server 24.04 LTS — arm64** (Canonical) | ★ x86_64 AMI를 고르면 t4g에서 시작조차 안 된다. AMI 목록에서 아키텍처를 **arm64로 먼저 전환**하고 골라라. 기본 SSH 사용자는 `ubuntu`다 (`ec2-user`가 아니다) |
| 인스턴스 유형 | **t4g.nano** | |
| 키 페어 | 새로 만들어 받아둔다 (`itx.pem`) | Tailscale이 붙기 전 첫 접속용. 붙은 뒤에는 안 쓰지만 **잠겼을 때의 유일한 탈출구**라 만들어 둔다 |
| 네트워크 | 기본 VPC / 퍼블릭 IP 자동 할당 **켜기** | 아웃바운드로 Tailscale·코레일에 나가야 한다. 탄력적 IP는 **붙이지 않는다** (12절) |
| 보안 그룹 | 새로 생성. 인바운드 **SSH(22) — 소스 `내 IP`만**. 그 외 없음 | 3절에서 이 규칙을 지운다 |
| 스토리지 | **gp3 10GB** | |

시작 후 **퍼블릭 IPv4**를 메모한다 (3절까지만 쓴다).

> **T 계열 크레딧**: t4g는 기본이 `unlimited`라 베이스라인을 넘기면 초과 과금이 붙는다.
> 이 워크로드(30초 시계 확인 + 정차역당 1~2회 조회)는 베이스라인 안에서 끝난다.
> **인스턴스에서 이미지를 빌드하면** 그때만 크레딧을 크게 쓴다 — 6절에서 M4 빌드를 쓰는 이유 중 하나다.

첫 접속:

```bash
chmod 400 ~/Downloads/itx.pem
ssh -i ~/Downloads/itx.pem ubuntu@<퍼블릭IP>
```

---

## 2. 인스턴스 초기 설정

### 스왑 2GB — **먼저 한다** (12절)

nano는 메모리 0.5GB다. 스왑이 없으면 새벽에 OOM Killer가 컨테이너를 잡아먹고,
아침에 알림이 조용히 오지 않는다.

```bash
sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # 재부팅 후에도 유지
free -h                                                      # Swap 2.0Gi 확인
```

`fallocate`가 아니라 `dd`를 쓴다 — 파일시스템에 따라 `fallocate`로 만든 파일은
`swapon`이 거부한다.

### Docker + compose 플러그인 (도커 공식 apt 저장소)

우분투 자체 패키지(`docker.io`)에는 compose 플러그인이 따라오지 않는다. 공식 저장소를 쓰면
`docker-compose-plugin`이 함께 오므로 **바이너리를 손으로 내려받는 단계가 없다.**

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# arch 는 dpkg 가 알려준다 — arm64 를 손으로 적지 않는다 (오타 여지를 없앤다)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
exit          # 그룹 반영을 위해 재로그인 (안 하면 계속 sudo가 필요하다)
```

재로그인 후 확인:

```bash
docker compose version     # v2.x
docker run --rm hello-world
```

### snapd를 지운다 — 0.5GB에서는 아깝다

우분투 서버 이미지에는 snapd가 들어 있고 상주하면서 100MB 안팎을 먹는다. 이 서버가 쓰는
것은 도커뿐이라 지워도 잃는 게 없다:

```bash
sudo systemctl disable --now snapd.socket snapd.service snapd.seeded.service 2>/dev/null
sudo apt-get purge -y snapd
free -h        # 여유 메모리가 늘어난 것을 확인
```

> 캐노니컬 AWS 이미지는 **SSM 에이전트를 snap으로** 넣는다. 즉 snapd를 지우면 Session
> Manager 경로도 사라진다. 다만 이 인스턴스에는 **IAM 인스턴스 프로파일을 붙이지 않았으므로
> SSM은 애초에 쓸 수 없다** — 잠겼을 때의 탈출구는 1절의 키 페어다. 그건 지우지 마라.

### 자동 업데이트는 그대로 둔다

우분투는 `unattended-upgrades`가 기본으로 켜져 있다. 자동 **재부팅**은 기본값이 꺼짐이라
아침에 인스턴스가 사라질 일은 없다. 도커가 갱신되면 컨테이너가 한 번 재시작되면서
**폴링이 한 틱 빠질 수 있지만**, `next_poll_at` 포인터는 DB에 있어 재시작에 강하고
compose가 `restart: unless-stopped`라 알아서 돌아온다 (D-17 상단 주석).

### 저장소 클론

컨테이너를 돌리는 데 `docker-compose.yml`이 필요하고, 정차역 캐시 재적재 스크립트도
저장소에서 온다. **서버에 python·uv는 깔지 않는다** — 스크립트는 컨테이너 안에서 돈다.

```bash
git clone https://github.com/MaTuna01/itx-seat-matrix.git ~/itx-seat-matrix
cd ~/itx-seat-matrix

# ★ 먼저 확인한다 — 우분투의 기본 사용자 ubuntu 는 uid 1000 이고, 컨테이너도 uid 1000 으로
#   돈다. 이 두 값이 같아야 바인드 마운트한 data/ 를 컨테이너가 쓸 수 있다
id -u        # 1000 이어야 한다

# data/ 는 gitignore라 클론에 없다. **컨테이너가 uid 1000으로 도므로 소유자를 맞춰둔다.**
# 먼저 만들지 않으면 docker가 root 소유로 만들고 SQLite가 "readonly database"로 죽는다
mkdir -p data
sudo chown -R 1000:1000 data
```

---

## 3. Tailscale — **순서를 뒤집으면 스스로 잠긴다**

Tailscale은 **호스트에** 설치한다 (컨테이너 사이드카가 아니다). 자세한 근거는 PLAN.md
12절 "접근 경로 설정".

```bash
# 1) 22번이 아직 열려 있는 상태에서
curl -fsSL https://tailscale.com/install.sh | sh

# 2) --ssh 를 반드시 붙인다 (22번을 닫기 위한 전제다)
sudo tailscale up --ssh --hostname=itx

# 3) 앱을 tailnet에 노출. 443 → 127.0.0.1:8000
sudo tailscale serve --bg 8000
tailscale serve status        # https://itx.tail9115e9.ts.net 확인
```

그다음 **admin 콘솔**([login.tailscale.com](https://login.tailscale.com/admin/machines)):

- [ ] **MagicDNS 켜기** + **HTTPS Certificates 켜기** — 둘 다 필요하다. 안 켜면 `*.ts.net`
      신뢰 인증서가 안 나오고, 자체서명으로는 **PWA 홈화면 추가와 웹푸시가 동작하지 않는다** (D-8)
- [ ] `itx` 노드의 **key expiry 비활성화** (Machines → itx → ⋯ → Disable key expiry).
      기본값은 180일 후 재인증이다 — **반년 뒤 어느 날 조용히 접근이 끊기고 스케줄러 알림도 함께 멈춘다**

### 22번을 닫는다 — 확인 뒤에

**다른 기기(M4)에서 Tailscale SSH가 되는 것을 먼저 확인한다:**

```bash
ssh ubuntu@itx     # M4에서. 키 파일 없이 붙어야 한다
```

붙으면 EC2 콘솔 → 보안 그룹 → **인바운드 규칙을 전부 삭제**한다 (22번 포함).
인바운드 0개여도 Tailscale은 붙는다 (직접 연결 실패 시 DERP 릴레이 경유).

---

## 4. `.env` 이관 — **키를 새로 만들면 조용히 깨진다**

로컬 `.env`를 통째로 복사하지 마라. **그대로 옮길 것 / 새로 정할 것 / 옮기지 말 것**이 섞여 있다.

| 키 | 처리 | 틀렸을 때 |
|---|---|---|
| `SECRET_KEY` | **그대로 옮긴다** | 새로 만들면 `korail_pw_enc`·디스코드 웹훅 복호화가 전부 깨진다. 조용히 죽지 않고 `FETCH_FAILED` 1회 + 화면의 "연결됨" 표시가 꺼진다 (D-35) |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | **그대로 옮긴다** | 바꾸면 기존 `push_device` 등록이 전부 무효 — 기기마다 알림을 다시 켜야 한다 (D-34) |
| `VAPID_SUBJECT` | 그대로 | 스킴(`mailto:`) 필수. 없으면 앱이 붙여준다 |
| `DATA_GO_KR_SERVICE_KEY` | 그대로 옮긴다 | 정차역 캐시 재적재(9절 참조)가 안 된다 |
| `COOKIE_SECURE` | **`true`** | ts.net은 HTTPS다. `false`로 두면 쿠키가 필요 이상으로 느슨해진다 |
| `ADAPTER` | **`korail2`** | `mock`이면 가짜 좌석으로 알림이 온다 — 조용히 틀린다 |
| `LOG_LEVEL` | `INFO` | WARNING이면 폴링 틱 로그가 사라져 검증(9절)이 불가능해진다 |
| `SCHEDULER_ENABLED` | `true` | `false`면 알림이 아예 안 온다 |
| `KORAIL_ID` / `KORAIL_PW` | **옮기지 않는다** | `scripts/phase0_feasibility.py` 전용 잔재다. `config.Settings`에 필드조차 없어 앱은 읽지 않는다. 코레일 계정은 **DB의 user 행**에 Fernet 암호로 있다 (D-35) |
| `KORAIL_SUB_ID` / `KORAIL_SUB_PW` | 옮기지 않는다 | 같은 이유 (미보유·미검증, D-22) |

### M4에서 만든다 — 시크릿은 별도 보관본(노션 등)에서 손으로

아이맥의 `.env`를 긁어올 필요는 없다. 시크릿을 노션 같은 곳에 보관해 뒀다면 거기서 옮긴다.
**단 손으로 옮기는 순간 오타 위험이 생기므로 지문 대조가 필수다** (바로 아래).

```bash
# M4. 저장소를 clone 한 디렉터리에서
cd ~/itx-seat-matrix

# 1) 보관본에서 시크릿 5개를 붙여 넣는다 (KORAIL_* 는 넣지 않는다)
cat > ~/itx-prod.env <<'EOF'
SECRET_KEY=<노션에서>
VAPID_PUBLIC_KEY=<노션에서>
VAPID_PRIVATE_KEY=<노션에서>
VAPID_SUBJECT=<노션에서>
DATA_GO_KR_SERVICE_KEY=<노션에서>
EOF

# 2) 배포용 값 추가
cat >> ~/itx-prod.env <<'EOF'
DB_PATH=data/itx.db
COOKIE_SECURE=true
ADAPTER=korail2
SESSION_DAYS=30
SESSION_TRANSIENT_HOURS=12
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=30
LOG_LEVEL=INFO
EOF
```

> `<<'EOF'`의 따옴표를 지우지 마라. 없으면 셸이 값 안의 `$`를 변수로 확장해
> **키가 조용히 잘린다.** base64 키에 `$`가 드물지만 없다고 보장할 수 없다.

### ★ 지문 대조 — 이걸 건너뛰면 D-35를 다시 만난다

`SECRET_KEY`가 **바이트 단위로** 원본과 같아야 한다. 한 글자라도 다르면 — 앞뒤 공백,
노션이 바꿔치기하는 스마트 쿼트(`"`가 `"`·`"`로, `-`가 `–`로) — **앱은 정상 기동하고 로그인도
되는데** 5절에서 옮겨온 DB의 `korail_pw_enc` 복호화만 실패한다. 증상은 `FETCH_FAILED` 1회와
설정 화면의 "연결됨" 꺼짐뿐이라 원인이 `.env`에 있다는 걸 알아내기 어렵다.

`scripts/env_fingerprint.sh`가 **값을 노출하지 않고** 12자 지문만 출력한다. 양쪽에서 돌린다:

```bash
# 원본 — 아이맥의 터미널에서 (출력에 값은 없다. 12자를 눈으로 옮겨 적으면 된다)
cd ~/itx-seat-matrix && scripts/env_fingerprint.sh

# 사본 — M4에서, 방금 만든 배포용
scripts/env_fingerprint.sh ~/itx-prod.env
```

> **`ssh imac`으로 원격 실행하려 하지 마라.** macOS는 Tailscale SSH의 **서버가 될 수 없고**
> (리눅스 전용이다), 맥의 "원격 로그인"을 따로 켜지 않았다면 tailnet 안에서도 22번이 닫혀 있다.
> 아이맥 앞에 앉아서 돌리는 게 정답이다 — 어차피 12자 다섯 줄이다.

**두 출력의 12자가 전부 일치해야 한다.** 하나라도 다르면 그 키를 다시 옮긴다.
`(빈 값)`이 보이면 붙여넣기가 실패한 것이다. `KORAIL_*` 경고가 나오면 그 줄을 지운다.

> 아이맥을 완전히 내리기 **전에** 대조해라. 내린 뒤에 지문이 다른 걸 발견하면
> 원본을 다시 켜야 한다.

### 전송

```bash
# M4 → EC2
scp ~/itx-prod.env ubuntu@itx:~/itx-seat-matrix/.env
rm -P ~/itx-prod.env     # macOS. Linux면 shred -u
```

서버에서 권한을 좁히고, 옮겨진 쪽에서도 한 번 더 대조한다 (`scp` 중 깨질 일은 없지만
값이 있는지·`KORAIL_*`이 없는지 확인은 공짜다):

```bash
chmod 600 ~/itx-seat-matrix/.env
cd ~/itx-seat-matrix && scripts/env_fingerprint.sh
```

---

## 5. 데이터 이관 — ★ **WAL 때문에 `itx.db`만 복사하면 최근 데이터가 사라진다**

DB는 **WAL 모드**다 (`app/storage/db.py`가 `PRAGMA journal_mode = WAL`). 그래서
`data/` 안에 `itx.db` 외에 `itx.db-wal`, `itx.db-shm`이 있고, **가장 최근 커밋들이
아직 `-wal` 쪽에 있다.** `itx.db` 하나만 복사하면 파일은 정상적으로 열리고 앱도 잘 뜨는데
**최근에 넣은 코레일 자격증명이나 푸시 기기 등록만 없다** — 가장 나쁜 종류의 조용한 실패다.

`.backup`을 쓴다. WAL을 포함해 일관된 단일 파일을 만들어 준다.

### ① 아이맥 서버를 내린다

**이 시점부터 EC2가 원본이 된다.** 백업을 뜬 뒤 아이맥에서 등록한 것(새 푸시 기기,
자격증명 변경)은 EC2에 없고, 두 DB가 갈라진다. 그래서 먼저 내린다:

```bash
# 아이맥. 포그라운드로 띄워뒀으면 Ctrl-C
pgrep -fl 'uvicorn app.main'      # 남아 있으면 kill
```

`.backup`은 라이브 DB에도 쓸 수 있지만, 내려두면 "백업 이후에 뭐가 더 들어갔나"를
생각할 필요가 없어진다.

### ② 아이맥에서 EC2로 **직접** 보낸다 — M4를 거치지 않는다

★ **M4에서 `ssh imac`으로 뽑아오려 하지 마라.** macOS는 Tailscale SSH의 **서버가 될 수 없다**
(리눅스 전용). 맥의 "원격 로그인"을 켜지 않았다면 tailnet 안에서도 22번이 닫혀 있고, 켜더라도
사용자명이 기기마다 달라 `ssh imac`이 아니라 `ssh <아이맥계정>@imac`이어야 한다.

거꾸로 하면 문제가 사라진다. **EC2는 리눅스라 Tailscale SSH가 되므로, 아이맥이 클라이언트가
되어 EC2로 밀어 넣으면 된다** — 중간 경유도, 원격 로그인도 필요 없다. (그래서 이 절만은
아이맥 앞에서 하고, **3절까지 끝나 `itx` 노드가 살아 있어야 한다.**)

```bash
# 아이맥에서. sqlite3 는 macOS 기본 탑재다
cd ~/itx-seat-matrix
sqlite3 data/itx.db ".backup '/tmp/itx-migrate.db'"

# sqlite3 CLI가 없으면 파이썬으로 (동일한 온라인 백업 API를 쓴다)
#   uv run python -c "import sqlite3; s=sqlite3.connect('data/itx.db'); d=sqlite3.connect('/tmp/itx-migrate.db'); s.backup(d); d.close(); s.close()"

# 내용 확인 — user/subscription/station/train_stop/push_device 가 다 있어야 한다
sqlite3 /tmp/itx-migrate.db "select 'user',count(*) from user union all
  select 'subscription',count(*) from subscription union all
  select 'station',count(*) from station union all
  select 'train_stop',count(*) from train_stop union all
  select 'push_device',count(*) from push_device;"

# EC2로 직접 전송
scp /tmp/itx-migrate.db ubuntu@itx:~/itx-seat-matrix/data/itx.db
```

> `/tmp/itx-migrate.db`는 **7·8절 검증이 끝날 때까지 지우지 마라** — 유일한 롤백이다.
> 끝나면 지운다(`rm -P /tmp/itx-migrate.db`). 코레일 자격증명이 든 파일이니 사본을
> 여기저기 흘리지 마라. (재부팅하면 `/tmp`가 비워질 수 있으니, 검증까지 시간이 걸릴 것 같으면
> 홈 디렉터리에 두는 편이 낫다.)

### ③ M4를 거치고 싶으면 — **AirDrop으로 옮긴다**

아이맥에서 EC2로 바로 보내는 게 짧지만, 파일을 M4에 두고 싶을 수도 있다(롤백본을 손에 두는
셈이다). 그때는 **AirDrop**을 쓴다. 두 대가 나란히 있는 맥이므로 드래그 한 번이고,
원격 로그인도 ssh도 필요 없다.

```bash
# 아이맥 — 데스크톱에 만든다 (AirDrop 으로 집어 보내기 쉽게)
cd ~/itx-seat-matrix
sqlite3 data/itx.db ".backup '$HOME/Desktop/itx-migrate.db'"
```

→ Finder에서 그 파일 우클릭 → **공유 → AirDrop → M4** (양쪽 Wi-Fi·블루투스 켜져 있어야 한다)

```bash
# M4 — 받은 파일을 확인하고 EC2로
sqlite3 ~/Downloads/itx-migrate.db "select 'user',count(*) from user union all
  select 'push_device',count(*) from push_device union all
  select 'train_stop',count(*) from train_stop;"

scp ~/Downloads/itx-migrate.db ubuntu@itx:~/itx-seat-matrix/data/itx.db
```

끝나면 **아이맥 데스크톱의 사본을 지운다** (`rm -P ~/Desktop/itx-migrate.db`). M4 쪽 사본은
7·8절 검증이 끝날 때까지 롤백본으로 남긴다.

> **이메일·메신저로 보내지 마라.** 이 파일에는 앱 계정의 비밀번호 해시, 아이폰 푸시
> 엔드포인트, 그리고 **코레일 본계정 비밀번호(`korail_pw_enc`)**가 들어 있다. Fernet으로
> 암호화돼 있지만 **복호화 키(`SECRET_KEY`)는 보관본(노션 등)에 있어** 두 곳이 각각
> 제3자 서버에 놓이는 셈이다. 무엇보다 메일·메신저에 한번 올라간 파일은 대화방에서 지워도
> **백업·인덱스에서 지워졌는지 확인할 방법이 없다.** AirDrop은 로컬 전송이라 사본이 남지 않는다.
>
> AirDrop이 잘 안 붙으면 tailnet 위로 한 번만 서빙하는 방법도 있다 — 아이맥에서
> `cd /tmp && python3 -m http.server 8080 --bind $(tailscale ip -4)`, M4에서
> `curl -O http://imac:8080/itx-migrate.db`, 끝나면 Ctrl-C. `--bind`를 빼면 같은 Wi-Fi의
> 아무 기기에나 열리므로 **반드시 붙여라.**

**서버에서:**

```bash
cd ~/itx-seat-matrix
sudo chown -R 1000:1000 data     # 컨테이너는 uid 1000으로 돈다
ls -l data
```

> **개발 DB(`data/itx.db`)는 지우지 않는다.** 계정이 들어 있고 가입이 잠겨 있어(D-24)
> 복구가 번거롭다. 위 절차는 읽기만 한다.

station·train_stop 캐시도 이 파일에 함께 온다. 소스 CSV는 `data/`가 gitignore라
저장소에 없으므로 **DB를 옮기는 편이 스크립트 재적재보다 확실하다.**
(정차역 캐시 신선도 관리는 9절.)

---

## 6. 이미지 빌드 → 전송 (M4에서)

레지스트리(ECR/Docker Hub)는 쓰지 않는다. `docker save`로 tar를 만들어 tailnet 위로 밀어 넣으면
추가 과금도, 자격증명 관리도 없다.

```bash
# M4에서. 저장소를 클론해 두고
cd ~/itx-seat-matrix
git switch dev && git pull

# arch를 명시한다 — M4에서는 기본값도 arm64지만, 명시해두면 다른 맥에서 실수하지 않는다
# --provenance=false 는 빼지 마라 (바로 아래 이유)
docker build --platform linux/arm64 --provenance=false -t itx-seat-matrix:local .

# arm64인지 확인 (여기서 x86_64면 EC2에서 exec format error가 난다)
docker image inspect itx-seat-matrix:local --format '{{.Architecture}}'

# 전송 (압축해서 ~70MB 안팎)
docker save itx-seat-matrix:local | gzip | ssh ubuntu@itx 'gunzip | docker load'

# ★ 받은 쪽에서도 확인한다 — load 가 조용히 실패하면 여기서 드러난다
ssh ubuntu@itx "docker image inspect itx-seat-matrix:local --format '{{.Architecture}}'"
```

> **`--provenance=false`를 왜 붙이나.** 요즘 buildx는 기본으로 provenance(attestation)를
> 붙이고, 그러면 `docker save` 산출물이 **index 안에 index가 있는 중첩 구조**가 된다
> (`application/vnd.oci.image.index.v1+json`이 두 겹). 컨테이너 이미지 스토어가 containerd가
> 아닌 데몬 — 도커 CE의 기본값이 그렇고, 우분투에 apt로 넣는 `docker-ce`도 여기 해당한다 — 에서는 이 tar를 `docker load`가
> 제대로 읽지 못할 수 있다. `--provenance=false`면 최상위가 평범한 `manifest.v2+json`을
> 직접 가리켜서 어느 데몬에서도 로드된다. **이미지 내용은 완전히 같다** (config digest 동일).
> 하필 100MB를 다 보낸 뒤 실패하는 자리라 처음부터 붙이는 편이 낫다.

<details>
<summary>폴백: 인스턴스에서 직접 빌드 (M4가 없을 때)</summary>

`docker-compose.yml`에 `build:`가 남아 있으므로 서버에서도 빌드된다. 다만 0.5GB RAM에서
`npm ci` + vite 빌드를 돌리는 일이라 **스왑 2GB가 반드시 먼저 있어야 하고**, 몇 분 걸리며
빌드 캐시가 10GB EBS를 갉아먹는다. 끝나면 `docker builder prune -af`로 정리해라.

```bash
cd ~/itx-seat-matrix && docker compose build && docker compose up -d
```

**`.env`가 없으면 `docker compose`는 빌드조차 시작하지 않는다** (`env file ... not found`로
즉시 종료). 4절을 먼저 끝내라 — 이 순서를 지키면 마주치지 않지만, 폴백으로 이 절만 보고
따라오면 걸린다.
</details>

---

## 7. 기동 + 확인

```bash
cd ~/itx-seat-matrix
docker compose up -d --no-build     # 이미지를 load 해왔으므로 빌드하지 않는다
docker compose ps                   # health: healthy 가 될 때까지 (start-period 20초)
./scripts/deploy_check.sh           # 12절 체크리스트를 한 번에 확인
```

`deploy_check.sh`가 보는 것: 컨테이너/헬스/재시작·OOM, **이미지 arm64**, **`--workers 1`**,
**스왑 2GB**, 퍼블리시가 루프백인지, `/healthz`, Tailscale serve + key expiry,
최근 10분의 폴링 틱 로그, DB 파일 소유자(uid 1000), 디스크.

로컬 응답 확인:

```bash
curl -i http://127.0.0.1:8000/healthz
```

M4·iMac 브라우저에서 `https://itx.tail9115e9.ts.net` → 로그인 화면이 떠야 한다.

- [ ] 로그인된다 (기존 계정이 그대로 — DB를 옮겼으므로)
- [ ] 설정 화면에서 **코레일 "연결됨"**이 켜져 있다 → `SECRET_KEY`가 제대로 옮겨졌다는 증거다.
      꺼져 있으면 4절로 돌아가라 (D-35)
- [ ] 역 드롭다운에 역이 나온다 → station 캐시가 왔다
- [ ] 열차 검색 → 매트릭스가 그려진다 → `ADAPTER=korail2` + 정차역 캐시 정상

### ★ 아이맥 서버가 여전히 내려가 있는지 확인한다

5절 ①에서 내렸지만, 그 사이 재부팅했거나 습관적으로 다시 띄웠을 수 있다. 지금이
**두 서버가 동시에 살아 있을 수 있는 유일한 구간**이므로 한 번 더 본다:

```bash
# 아이맥에서 (M4에서 ssh 로 확인할 수는 없다 — 0절 주의 참조)
pgrep -fl 'uvicorn app.main'     # 아무것도 안 나와야 한다
```

아이맥의 `tailscale serve`도 이때 정리하면 헷갈리지 않는다. 앱이 내려간 뒤에도 설정은 남아
있어서 `https://imac.…`가 **502를 돌려주는 상태**가 되기 때문이다:

```bash
# 아이맥에서. 개발 중에 다시 필요하면 그때 켠다
sudo tailscale serve --https=443 off
```

DB를 복사해 왔으므로 `push_device`·`subscription` 행이 **양쪽에 똑같이 있다.**
아이맥 서버가 실 어댑터로 살아 있으면 스케줄러가 두 곳에서 각각 30초 틱을 돌려서:

- 같은 폰으로 **알림이 두 번 온다** (`--workers 1`은 한 호스트 안만 막는다 — D-17)
- 코레일 조회가 두 배가 된다 (CLAUDE.md 10 위반)
- 어느 쪽이 보낸 알림인지 구분이 안 돼 10절 검증 결과를 신뢰할 수 없다

아이맥은 개발기로 계속 쓴다. 다만 **개발 서버는 `ADAPTER=mock`으로만 띄워라** —
실 어댑터로 띄우면 그 순간 위 3가지가 다시 발생한다. (`~/Library/LaunchAgents`에 이 앱의
plist는 없다 — 수동 실행이라 한 번 내리면 재부팅해도 되살아나지 않는다.)

---

## 8. 폰 재등록 — **오리진이 바뀌었으므로 한 번은 반드시 필요하다**

지금까지 폰은 `https://imac.tail9115e9.ts.net`을 보고 있었다. 새 주소는
`https://itx.tail9115e9.ts.net`이다. **웹푸시 구독은 오리진 단위**라 기존
`push_device` 등록은 새 주소에서 쓸 수 없다 (D-34). VAPID 키를 그대로 옮긴 것과는 별개 문제다.

폰(iOS Safari)에서:

1. `https://itx.tail9115e9.ts.net` 접속 → 로그인
2. **공유 → 홈 화면에 추가** (홈 화면 앱에서만 웹푸시가 동작한다)
3. 홈 화면 아이콘으로 열고 → 설정 → **"알림 켜기" 버튼을 탭**
   (권한 요청은 사용자 제스처 안에서만 된다 — 자동 요청은 조용히 실패한다, D-21)
4. **"테스트 발송"**으로 실제 수신 확인
5. 예전 `imac.…` PWA 아이콘은 지운다 (헷갈리면 엉뚱한 서버를 보게 된다)

죽은 등록은 발송 시 410/404로 자동 정리된다 (D-20). 확인:

```bash
docker compose exec app python -c "
import sqlite3; c=sqlite3.connect('data/itx.db')
print(c.execute('select id, substr(endpoint,1,45), created_at from push_device').fetchall())"
```

> iMac을 개발용으로 계속 쓸 거면 `imac`의 `tailscale serve`는 켜둬도 된다.
> 다만 **폰이 어느 쪽을 보고 있는지 헷갈리지 않게** 홈 화면 아이콘은 하나만 남겨라.

---

## 9. 운영

### 재배포

```bash
# M4: 빌드 + 전송
cd ~/itx-seat-matrix && git pull
docker build --platform linux/arm64 --provenance=false -t itx-seat-matrix:local .
docker save itx-seat-matrix:local | gzip | ssh ubuntu@itx 'gunzip | docker load'

# EC2
cd ~/itx-seat-matrix && git pull        # compose 파일·스크립트 갱신
docker compose up -d --no-build
./scripts/deploy_check.sh
```

출근 시간대 재배포도 안전하다 — `next_poll_at` 포인터가 DB에 있어 재시작을 흡수하고
(D-19), 2분 이내 지각이면 즉시 실행, 넘으면 스킵하고 다음 포인트로 전진한다.
**다만 폴 포인트(정차역 도착 -10/-4분) 직전에 재배포하면 그 한 번은 놓칠 수 있다.**

### 로그

```bash
docker compose logs -f app                    # 실시간
docker compose logs app | grep "폴링 틱"       # 폴링이 도는지
docker compose logs --since 30m app           # 최근 30분
```

### 정차역 캐시 재적재 (D-29 — 신선도 관리)

정차역 캐시는 "최근 실적" 템플릿이라 시각표 개정으로 열차번호가 바뀌면 낡는다.
캐시에 없는 열차번호는 조용히 틀리지 않고 에러로 드러난다.

```bash
docker compose exec app python scripts/load_train_stops.py
```

### 백업 — **계정과 코레일 자격증명이 들어 있다**

```bash
# EC2에서. WAL 포함 일관 스냅샷
docker compose exec app python -c "
import sqlite3; s=sqlite3.connect('data/itx.db'); d=sqlite3.connect('data/backup.db'); s.backup(d)"
```

암호는 Fernet으로 암호화돼 있지만 `SECRET_KEY`와 함께 새면 의미가 없다.
**백업 파일과 `.env`를 같은 곳에 두지 마라** (12절).

### 롤백

```bash
docker images itx-seat-matrix                 # 직전 이미지가 남아 있으면
docker tag <이전IMAGE_ID> itx-seat-matrix:local
docker compose up -d --no-build
```

DB 스키마 마이그레이션(`PRAGMA user_version`)은 되돌아가지 않는다. 스키마가 바뀐 배포를
되돌릴 때는 백업 파일로 복구한다.

### 멈추기 / 시작하기

```bash
docker compose stop      # 알림도 멈춘다
docker compose start
```

---

## 10. Phase 3 완료 기준 검증 — 실제 출근길 한 번

배포의 목적은 이것이다. **"역 접근 시 자동 갱신 → 알림 수신"**을 실제 통근에서 통과시키면
Phase 3의 남은 완료 기준이 닫힌다. 맥에서는 잠들어서 불가능했던 검증이다.

### 전날 저녁 — 준비

- [ ] `./scripts/deploy_check.sh` 전부 통과 (특히 **스왑**·**`--workers 1`**·**serve**)
- [ ] 폰에서 **테스트 발송** 수신 (8절)
- [ ] 앱에서 내일 탈 열차로 **구독을 만든다** (입석/착석 + 착석이면 좌석 지정)
- [ ] 구독의 폴 포인트가 잡혔는지 확인 — `next_poll_at`이 NULL이면 알림이 영영 안 온다:

```bash
docker compose exec app python -c "
import sqlite3; c=sqlite3.connect('data/itx.db'); c.row_factory=sqlite3.Row
for r in c.execute('select id,train_no,status,active,next_poll_at,last_verdict_hash from subscription where active=1'):
    print(dict(r))"
```

### 당일 아침 — 무엇을 확인하는가

폴링은 **정차역 실효 도착시각의 -10분 / -4분**에 일어난다 (9절, D-12). 30초 틱은
"시계 확인"일 뿐이고 실제 코레일 조회는 그 시점에만 발생한다.

기대 동작:

1. **첫 폴 포인트에서 베이스라인 알림 1건** — `last_verdict_hash`가 NULL이므로 상태 변화와
   무관하게 1건 온다 (D-20). **이게 오면 스케줄러→알림 경로 전체가 살아 있다는 증거다.**
   여기까지가 이번 검증의 핵심이다.
2. 이후 폴 포인트에서는 **상태가 바뀔 때만** 온다. 구간만 진행했거나 하위 추천 순서만
   바뀌었으면 **침묵하는 것이 정상이다** (원칙 6, D-16). 조용한 것은 실패가 아니다.
3. 알림 탭 → 매트릭스로 딥링크된다 (D-20)
4. 하차역 도착 후 구독이 `active=0`으로 내려간다

폰에서 알림을 받은 뒤 서버에서 대조:

```bash
docker compose logs --since 1h app | grep -E "폴링 틱|알림"
```

`폴링 틱: 조회 1 · 알림 ['SEATS_AVAILABLE'] · …` 형태의 줄과 폰의 알림이 짝이 맞으면 통과다.

### 실패 시 — 어느 로그를 보는가

증상별로 볼 곳이 다르다. **위에서 아래로 좁혀 나간다.**

| 증상 | 먼저 볼 것 | 원인 후보 |
|---|---|---|
| **알림이 아무것도 안 왔다** | `docker compose logs app \| grep "폴링 스케줄러 시작"` | 없으면 스케줄러가 안 떴다 → `SCHEDULER_ENABLED=false`거나 `LOG_LEVEL`이 INFO가 아니다 |
| 스케줄러는 떴는데 틱 로그가 없다 | `grep "폴링 틱"` + 위의 `next_poll_at` 쿼리 | `next_poll_at`이 NULL이거나 이미 지나갔다. `active=1`인지도 본다 |
| 틱은 도는데 알림이 0건 | `grep -E "폴링 틱"`의 `알림 []` | 정상 침묵일 수 있다 (기대 동작 2). `last_verdict_hash`가 이미 채워져 있으면 베이스라인은 지났다 |
| `FETCH_FAILED`만 온다 | `grep -E "FETCH_FAILED\|MACRO ERROR\|매진"` | `MACRO ERROR` → DynaPath 우회 파손, 고칠 곳은 `korail_dynapath.py` 하나다 (D-22). 매진 관련이면 D-36 |
| 코레일 "연결됨"이 꺼졌다 | `grep SECRET_KEY` | `SECRET_KEY`가 로컬과 다르다 → 4절 (D-35) |
| 알림이 **두 번** 온다 | `./scripts/deploy_check.sh`의 워커 항목 | 프로세스가 2개다 (D-17). `--workers 1`인지, 컨테이너가 2개 뜬 건 아닌지 |
| 밤사이 컨테이너가 죽었다 | `docker inspect itx --format '{{.State.OOMKilled}} {{.RestartCount}}'` | OOM → 스왑 확인 (2절). 반복되면 micro(2GB)로 승급 (14절) |
| 어느 날 갑자기 접속이 안 된다 | `tailscale status` | key expiry가 살아 있었다 (3절). admin 콘솔에서 비활성화 |
| 틱이 예외로 죽는다 | `grep -A20 "폴링 틱 실패"` | 스택트레이스가 여기 나온다 |

로그를 파일로 받아 두려면:

```bash
docker compose logs --since 3h --no-color app > ~/itx-$(date +%F).log
```

### 덤으로 얻는 것 — 매진 코드값 (D-36 후속)

매진을 만나면 로그에 `[h_msg_cd=…]`가 남는다. `SOLD_OUT_CODES`가 아직 비어 있어
한국어 문구 매칭에 기대고 있는데(D-36), 이 값을 확보하면 그 의존을 줄일 수 있다.

```bash
docker compose logs app | grep "h_msg_cd"
```

값이 잡히면 **별도 이슈(C)**에서 `app/adapters/korail_client.py`의 `SOLD_OUT_CODES`에 등재한다.
이번 배포 이슈의 범위는 아니다.

---

## 11. 하지 말 것

- **`--workers`를 2 이상으로 올리지 마라.** APScheduler가 인프로세스라 알림이 중복 발사된다 (D-17).
  `deploy.replicas`, `docker compose up --scale`도 같은 사고다
- **EC2와 아이맥에서 실 어댑터 서버를 동시에 띄우지 마라.** 호스트가 둘이면 `--workers 1`이
  막아주지 못한다 — DB를 복사했으니 폰 등록도 양쪽에 있어서 알림이 두 번 간다 (7절 끝)
- **포트를 `"8000:8000"`으로 바꾸지 마라.** 인바운드가 닫혀 있어 당장은 안 뚫리지만,
  보안그룹 하나에만 의존하는 상태가 된다 (이중 방어, D-10)
- **탄력적 IP를 붙이지 마라.** Tailscale 주소로 접근하므로 불필요하고 미사용 시 과금된다 (12절)
- **`SECRET_KEY`·VAPID 키를 서버에서 새로 만들지 마라** (D-34, D-35)
- **`.env`를 손으로 옮겼는데 지문 대조를 건너뛰지 마라.** `scripts/env_fingerprint.sh`를
  원본·사본 양쪽에서 돌린다 (4절). 오타 하나가 "기동은 되는데 코레일만 안 되는" 상태를 만든다
- **`.env`·`*.db`를 커밋하지 마라.** pre-commit 훅이 막지만(D-33) 훅을 믿고 방심하지 마라
- **실 코레일 API를 루프로 때리지 마라.** 디버깅은 `ADAPTER=mock`으로 (CLAUDE.md 10)
