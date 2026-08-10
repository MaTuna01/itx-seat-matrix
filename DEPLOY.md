# 배포 (AWS EC2 + Docker + Tailscale)

**PLAN.md 12절의 실행 절차서다.** 왜 t4g.nano인지, 왜 서울 리전인지, 왜 Tailscale인지는
12절과 17절(D-6, D-8, D-10, D-38)에 있다. 여기서는 그 결정을 **어떤 순서로 실행하는지**만 다룬다.

접근 경로는 **A(Tailscale serve) 유지**로 확정했다 (D-38). 공개 노출로 전환하려면 D-38의
전환 트리거를 먼저 읽어라 — 오리진이 바뀌면 기기마다 알림을 다시 켜야 한다 (D-34).

> **1~8절은 처음 한 번의 절차다.** 그 뒤의 재배포는 `dev → main` 머지로 자동화돼 있다
> (9절 "CD 사전 준비"·"재배포", D-51). 6절의 손 빌드는 폴백으로 남는다.

---

## 0. 3대가 관여한다 — 무엇이 어디서 나오는지

이 프로젝트의 배포는 한 대에서 끝나지 않는다. 시작 전에 이걸 확실히 해둬야 빠뜨리지 않는다.

| 머신 | 역할 | 이유 |
|---|---|---|
| **M4 MacBook Air** (arm64) | **작업 거점 — 빌드와 나머지 전부** | t4g는 Graviton(arm64). Apple Silicon에서 빌드하면 네이티브 arm64가 나온다 |
| **Intel iMac** (x86_64) | **`data/itx.db` 원본 제공 — 이것만** | 실 코레일 자격증명과 푸시 기기 등록이 이 DB에만 있다 |
| **EC2 t4g.nano** (Ubuntu 26.04 LTS, arm64) | 실행 | 통근 시간대에 깨어 있어야 30초 틱이 멈추지 않는다 — **평일 06:00~24:00만 가동한다** (9절 "자동 정지·기동", → D-54). SSH 사용자는 `ubuntu` (D-42) |

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
(현재 tailnet: `imac`, `iphone-14-pro`, `macbookair`. 배포 후 `korail-matrix`가 추가된다.)

---

## 1. EC2 프로비저닝 (콘솔 — **소유자가 직접 한다**)

실 과금이므로 이 절은 사람이 실행한다. 리전 **ap-northeast-2(서울)**.

EC2 → **인스턴스 시작**:

| 항목 | 값 | 주의 |
|---|---|---|
| 이름 | `korail-matrix` | tailnet 호스트명과 같게 두면 헷갈리지 않는다 |
| AMI | **Ubuntu Server LTS — arm64** (Canonical) | ★ x86_64 AMI를 고르면 t4g에서 시작조차 안 된다. AMI 목록에서 아키텍처를 **arm64로 먼저 전환**하고 골라라. 기본 SSH 사용자는 `ubuntu`다 (`ec2-user`가 아니다). **버전은 콘솔 기본값(현재 26.04 `resolute`)을 그대로 쓴다** — 24.04로 맞출 이유가 없다 (→ D-42) |
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

> **`Could not get lock /var/lib/dpkg/lock-frontend` 이 나오면 기다려라.** 갓 만든
> 인스턴스는 부팅 직후 `unattended-upgrades`가 도는 중이라 apt가 두 개 동시에 못 돈다
> (D-42가 예고한 그 자동 갱신이다). 잠금 파일을 지우지 말고 끝날 때까지 기다린 뒤 **실패한
> 명령만** 다시 치면 된다 — 저장소 등록은 이미 끝나 있으므로 설치 스크립트를 처음부터
> 다시 돌릴 필요는 없다:
>
> ```bash
> while pgrep -x unattended-upgr >/dev/null; do echo "대기 중..."; sleep 5; done
> ```

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

**운영 서버는 `main`만 본다.** `dev`는 개발기(아이맥)용이다 — 운영이 `dev`를 따라가면
`git pull` 한 번에 그 사이 머지된 무관한 작업까지 딸려온다. 브랜치를 바꾸는 것만으로는
컨테이너가 재시작되지 않으니(이미지는 별개다) 언제든 안전하게 전환할 수 있다.

```bash
git clone https://github.com/MaTuna01/itx-seat-matrix.git ~/itx-seat-matrix
cd ~/itx-seat-matrix
git switch main        # ★ 운영은 main. dev 를 체크아웃하지 마라

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
sudo tailscale up --ssh --hostname=korail-matrix

# 3) 앱을 tailnet에 노출. 443 → 127.0.0.1:8000
sudo tailscale serve --bg 8000
tailscale serve status        # https://korail-matrix.tail9115e9.ts.net 확인
```

그다음 **admin 콘솔**([login.tailscale.com](https://login.tailscale.com/admin/machines)):

- [ ] **MagicDNS 켜기** + **HTTPS Certificates 켜기** — 둘 다 필요하다. 안 켜면 `*.ts.net`
      신뢰 인증서가 안 나오고, 자체서명으로는 **PWA 홈화면 추가와 웹푸시가 동작하지 않는다** (D-8)
- [ ] `korail-matrix` 노드의 **key expiry 비활성화** (Machines → korail-matrix → ⋯ → Disable key expiry).
      끄고 나면 목록에 `Expiry disabled`로 표시된다 — 그걸 눈으로 확인해라.
      기본값은 180일 후 재인증이다 — **반년 뒤 어느 날 조용히 접근이 끊기고 스케줄러 알림도 함께 멈춘다**

### 22번을 닫는다 — 확인 뒤에

**다른 기기(M4)에서 Tailscale SSH가 되는 것을 먼저 확인한다:**

```bash
ssh ubuntu@korail-matrix     # M4에서. 키 파일 없이 붙어야 한다
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
scp ~/itx-prod.env ubuntu@korail-matrix:~/itx-seat-matrix/.env
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
아이맥 앞에서 하고, **3절까지 끝나 `korail-matrix` 노드가 살아 있어야 한다.**)

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
scp /tmp/itx-migrate.db ubuntu@korail-matrix:~/itx-seat-matrix/data/itx.db
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

scp ~/Downloads/itx-migrate.db ubuntu@korail-matrix:~/itx-seat-matrix/data/itx.db
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
docker save itx-seat-matrix:local | gzip | ssh ubuntu@korail-matrix 'gunzip | docker load'

# ★ 받은 쪽에서도 확인한다 — load 가 조용히 실패하면 여기서 드러난다
ssh ubuntu@korail-matrix "docker image inspect itx-seat-matrix:local --format '{{.Architecture}}'"
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

M4·iMac 브라우저에서 `https://korail-matrix.tail9115e9.ts.net` → 로그인 화면이 떠야 한다.

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
`https://korail-matrix.tail9115e9.ts.net`이다. **웹푸시 구독은 오리진 단위**라 기존
`push_device` 등록은 새 주소에서 쓸 수 없다 (D-34). VAPID 키를 그대로 옮긴 것과는 별개 문제다.

폰(iOS Safari)에서:

1. `https://korail-matrix.tail9115e9.ts.net` 접속 → 로그인
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

### CD 사전 준비 — **한 번만 한다** (#22, D-51)

`.github/workflows/cd.yml`이 `main` 푸시에서 자동 배포한다. 저장소에 담을 수 없는 준비물이
셋 있고, **없으면 워크플로가 `tailscale up`에서 멈춘다.**

**순서를 지켜라 — ACL이 OAuth보다 먼저다.** `tag:ci`가 `tagOwners`에 없으면 OAuth 클라이언트에
그 태그를 붙일 수 없다.

**① ACL** — admin → Access controls. 러너는 **korail-matrix의 22번 하나만** 열어준다.
`hosts`의 IP는 `tailscale ip -4 korail-matrix`로 확인한다.

**★ `korail-matrix`에 `tag:server`를 붙인다.** Tailscale SSH는 **`dst`에 사용자(이메일)를
쓰면 `src`가 같은 사용자여야 한다** — "내 기기 → 내 기기"만 표현할 수 있는 형태라, 태그에서
출발하는 규칙은 목적지도 태그여야 한다 (`users in dst are only allowed from the same user`).

```jsonc
"tagOwners": {
    "tag:ci":     ["ma775100@gmail.com"],
    "tag:server": ["ma775100@gmail.com"],
},
"hosts": { "korail-matrix": "100.x.y.z" },

"grants": [
    // ★ 기본 템플릿의 {"src": ["*"] …} 를 이걸로 바꾼다. 내 기기들끼리는 그대로 열려 있고,
    //   **태그는 member가 아니므로** 러너가 이 포괄 규칙을 타지 못한다
    {"src": ["autogroup:member"], "dst": ["*"], "ip": ["*"]},
    // 러너에게 허용된 것은 이것뿐이다
    {"src": ["tag:ci"], "dst": ["tag:server"], "ip": ["tcp:22"]},
],

"ssh": [
    // ① 내 기기 → 내 기기 (아이맥 등). 태그가 없는 노드용 — 지우지 마라
    {"action": "accept", "src": ["autogroup:member"], "dst": ["autogroup:self"],
     "users": ["autogroup:nonroot", "root"]},
    // ② 내 기기 → 서버. ★ 태그를 붙이는 순간 korail-matrix 는 autogroup:self 로 잡히지
    //    않는다. **이 규칙이 없으면 내가 SSH를 잃는다** (인바운드 0개라 되돌릴 길이 없다)
    {"action": "accept", "src": ["autogroup:member"], "dst": ["tag:server"],
     "users": ["ubuntu", "autogroup:nonroot"]},
    // ③ CI 러너 → 서버. "check"가 아니라 "accept"다 — check는 브라우저 재인증을 요구하고
    //    CI에는 브라우저가 없다
    {"action": "accept", "src": ["tag:ci"], "dst": ["tag:server"],
     "users": ["ubuntu"]},
],

```

> `grants`(신 문법)를 쓰는 tailnet이면 `acls`(구 문법)를 함께 두지 마라 — 역할이 겹친다.
>
> **`tests`는 아직 넣지 마라.** ACL 테스트는 *지금 tailnet에 있는 기기*로 평가하는데
> `korail-matrix`에 태그가 붙기 전에는 `dst: tag:server`에 걸리는 기기가 없어
> `want: Accept, got: Drop`으로 **저장 자체가 막힌다** (닭·달걀이다). 아래 ②의 5번에서
> 태그를 붙인 뒤에 추가한다.

**② 태그 붙이기 — 락아웃 주의.** 순서를 지켜라. **먼저 `ssh ubuntu@korail-matrix` 세션을
하나 열어둔 채로 시작한다** (이미 열린 세션은 ACL을 바꿔도 끊기지 않는다. 보험이다).

1. 위 정책을 저장한다 (`tests` 없이). 아직 태그가 없으므로 규칙 ①이 SSH를 유지한다
2. **새 터미널**에서 `ssh ubuntu@korail-matrix` 확인
3. Machines → `korail-matrix` → ⋯ → **Edit ACL tags** → `tag:server`.
   **`tailscale up`을 다시 돌리지 마라** — 재인증이 걸려 세션이 끊긴다
4. **다시 새 터미널**에서 `ssh ubuntu@korail-matrix` 확인. 이번엔 규칙 ②를 탄다 — 여기가 관문이다
5. 이제 `tests`를 넣고 저장한다. 이번엔 통과한다:

```jsonc
"tests": [
    {"src": "tag:ci", "accept": ["korail-matrix:22"], "deny": ["korail-matrix:443"]},
],
```

안 되면 열어둔 세션에서 정책을 되돌린다. 그마저 잃었으면 복구는 **EC2 콘솔에서 보안그룹에
22번을 임시로 다시 열고 원래 키페어로 접속**하는 경로다 (t4g는 Nitro라 시리얼 콘솔도 된다).

> **덤**: 태그가 붙은 노드는 key expiry가 적용되지 않는다 — 3절이 걱정하던 "반년 뒤 어느 날
> 조용히 끊긴다"가 구조적으로 사라진다.

**③ OAuth 클라이언트 → GitHub 시크릿** — [admin → Settings → OAuth clients](https://login.tailscale.com/admin/settings/oauth).
`auth_keys` **쓰기** 권한 + 태그 `tag:ci`. secret은 **이 화면을 벗어나면 다시 못 본다.**
발급된 값을 GitHub 저장소 **Settings → Secrets and variables → Actions**에 넣는다:

| 시크릿 | 값 |
|---|---|
| `TS_OAUTH_CLIENT_ID` | OAuth client ID |
| `TS_OAUTH_SECRET` | OAuth client secret (`tskey-client-…`) |

**④ 확인** — 위를 다 넣은 뒤 **출근 시간대를 피해** Actions 탭에서 CD를 `workflow_dispatch`로
한 번 돌린다. 러너가 `gh-cd`라는 이름의 일회용 노드로 tailnet에 들어왔다 나가는 것이
admin 콘솔 Machines에 보인다.

> `production` Environment는 미리 만들지 않아도 첫 실행에서 자동 생성된다. 승인자는 두지
> 않는다 — 재배포 타이밍은 아래 폴 포인트 가드가 대신 지킨다.

### 재배포 — **`dev → main` 머지가 곧 배포다**

`dev`에서 작업하고 `dev → main` PR을 올려 머지하면(소유자가 직접 — CLAUDE.md 6) CD가
**테스트 → arm64 빌드 → 폴 포인트 가드 → 전송 → 기동 → `deploy_check.sh`**까지 한다.
서버의 작업 트리도 배포한 커밋으로 맞춰지므로 "지금 서버에 뭐가 올라가 있나"는 여전히
`main` 하나로 답이 된다.

**폴 포인트 가드.** 자동 배포 = 컨테이너 재시작이다. `next_poll_at` 포인터가 재시작을 흡수하고
(D-19) 2분 이내 지각이면 즉시 실행되지만, **폴 포인트(정차역 도착 -10/-4분) 직전에 재배포하면
그 한 번은 놓칠 수 있다.** 그래서 배포 직전에 서버 DB를 보고 **10분 안에 폴이 잡힌 활성 구독이
있으면 멈춘다.** 시각을 하드코딩하지 않으므로 구독이 없는 날은 아침에도 그냥 배포된다.

멈췄을 때는 그 폴이 지난 뒤 Actions에서 **Re-run**하면 된다. 급하면 `workflow_dispatch`의
`force`를 켠다 (그 폴 한 번을 포기한다는 뜻이다).

지금 걸릴지 손으로 미리 볼 수 있다 — **읽기만 하므로 아무 때나 돌려도 안전하다**:

```bash
# M4 등에서. 종료 코드 0 = 배포해도 된다 / 1 = 보류
ssh ubuntu@korail-matrix 'python3 - ~/itx-seat-matrix/data/itx.db' < scripts/deploy_guard.py

# "내일 08:10이면 걸렸을까" — 예행 연습
ssh ubuntu@korail-matrix 'python3 - --now 2026-08-11T08:10 ~/itx-seat-matrix/data/itx.db' \
  < scripts/deploy_guard.py
```

<details>
<summary>수동 배포 — 폴백 (러너가 죽었을 때·긴급)</summary>

CD가 못 도는 상황에서도 배포 경로는 그대로 남아 있다. **`main`을 기준으로** 빌드한다.

```bash
# M4: 빌드 + 전송
cd ~/itx-seat-matrix
git switch main && git pull            # ★ 배포는 main 기준으로 빌드한다
docker build --platform linux/arm64 --provenance=false -t itx-seat-matrix:local .
docker save itx-seat-matrix:local | gzip | ssh ubuntu@korail-matrix 'gunzip | docker load'

# EC2
cd ~/itx-seat-matrix && git pull        # compose 파일·스크립트 갱신 (main 추적 중)
docker compose up -d --no-build
./scripts/deploy_check.sh
```

손으로 할 때는 **롤백 포인터가 찍히지 않는다** — 아래 롤백 절의 `:previous`가 낡은 것을
가리킬 수 있으니 `docker images itx-seat-matrix`로 눈으로 확인하고 되돌려라.
</details>

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

**CD가 이미 한다.** 배포 후 `deploy_check.sh`가 실패하면 워크플로가 이미지와 작업 트리를
**함께** 직전 상태로 되돌리고 재점검한 뒤 실패로 끝난다. 둘 중 하나만 되돌리면 옛 이미지가
새 compose·새 스크립트로 뜨기 때문에 짝을 맞춘다.

손으로 되돌릴 때도 같은 두 짝을 되돌린다 — CD가 매 배포마다 직전 이미지를 `:previous`로
찍어 둔다:

```bash
cd ~/itx-seat-matrix
docker tag itx-seat-matrix:previous itx-seat-matrix:local
git reset --hard <직전커밋>                    # git log 로 확인. 이미지와 짝을 맞춘다
docker compose up -d --no-build
./scripts/deploy_check.sh
```

`:previous`가 없거나(첫 배포·수동 배포 뒤) 더 앞으로 가야 하면 이미지 목록에서 고른다.
**`docker image prune`이 태그 없는 옛 이미지를 지우므로 두 세대 앞은 남아 있지 않을 수 있다:**

```bash
docker images itx-seat-matrix
docker tag <이전IMAGE_ID> itx-seat-matrix:local
```

DB 스키마 마이그레이션(`PRAGMA user_version`)은 되돌아가지 않는다. 스키마가 바뀐 배포를
되돌릴 때는 백업 파일로 복구한다. **CD의 자동 롤백도 여기까지는 못 한다** — 스키마를 바꾸는
배포는 백업을 먼저 떠 두고 올려라.

### 멈추기 / 시작하기

```bash
docker compose stop      # 알림도 멈춘다
docker compose start
```

### 자동 정지·기동 — **미사용 시간대에 인스턴스를 끈다** (#58)

평일 **06:00~24:00(KST)** 만 가동하고 주말은 완전히 정지한다. 월 ~$4.7 → ~$2.9.
**EBS 10GB(~$0.91/월)는 꺼도 계속 나간다** — 줄어드는 것은 컴퓨트뿐이다.

기동은 AWS(EventBridge Scheduler)가, **정지 판단은 박스 안에서** 한다. 시각만 보고 끄면
안 되기 때문이다 — 꺼져 있는 동안 도래한 폴 포인트는 `resolve_poll`의 grace 2분을 넘겨
**스킵되고 포인터만 전진한다**(D-19). 운행이 통째로 지나갔으면 `is_ride_over`가 구독을
만료시킨다. 남는 것은 로그 한 줄이고 알림은 오지 않는다.

그래서 `deploy_guard.py`와 같은 패턴을 쓴다 (D-51): **다음 기동 시각 전에 폴이 잡혀
있으면 끄지 않는다.** 주말은 이 계산에 자연히 들어간다 — 금요일 밤의 "다음 기동"은
월요일 06:00이므로, 토요일 열차 구독이 있으면 금요일 밤부터 정지를 거부한다.

> **판단 불능일 때 `deploy_guard.py`와 방향이 반대다.** 배포 가드는 모르면 통과시키고,
> 정지 가드는 모르면 **켜둔다.** 하룻밤 $0.09 대 출근길 알림 전체라 어느 쪽이 싼지가
> 분명하다. 다만 이 방향의 고장은 **요금서에만 나타나므로** 첫 주에 한 번 로그를 봐라.

#### ★ 먼저 확인 — 인스턴스 시작 종료 동작이 `stop`인가

이걸 안 보고 진행하면 **박스가 사라진다.** OS가 poweroff를 걸었을 때 EC2가 인스턴스를
정지시킬지 종료시킬지는 인스턴스 속성이 정한다. 기본값은 `stop`이지만 확인은 공짜다.

EC2 콘솔 → 인스턴스 선택 → **작업 → 인스턴스 설정 → 종료 동작 변경**(Change shutdown
behavior) → **`중지(Stop)`** 인지 확인.

> 9단계에서 껐던 **종료 방지(termination protection)는 이걸 막아주지 않는다.**
> 그건 API 호출만 막고 OS가 건 종료에는 관여하지 않는다.

#### ① 기동 — EventBridge Scheduler (콘솔, 소유자가 직접)

리전 **ap-northeast-2**. EventBridge → 스케줄러 → **일정 생성**:

| 항목 | 값 |
|---|---|
| 이름 | `itx-start-weekday` |
| 일정 패턴 | 되풀이 / cron 기반 |
| cron 식 | `cron(0 6 ? * MON-FRI *)` |
| 시간대 | **`Asia/Seoul`** ← UTC로 환산하지 마라. 서머타임이 없어도 손으로 환산하면 틀린다 |
| 유연한 기간 | **끄기(Off)** ← 켜면 최대 15분 늦게 시작해 첫 폴을 놓칠 수 있다 |
| 대상 | 템플릿이 지정된 대상 → **EC2 `StartInstances`** |
| 입력 | `{"InstanceIds": ["i-<서울 인스턴스 ID>"]}` |
| 권한 | 새 역할 생성 (콘솔이 `ec2:StartInstances`만 붙여준다) |

Lambda는 필요 없다. 호출이 월 22회라 요금도 사실상 0이다.

#### ② 정지 — systemd 타이머 (박스에서)

```bash
# EC2. 저장소에 유닛이 들어 있다 (scripts/systemd/)
cd ~/itx-seat-matrix

# 캘린더 식이 이 systemd 에서 파싱되는지 먼저 본다
systemd-analyze calendar 'Mon-Fri 23:50 Asia/Seoul'

# 가드를 예행 연습한다 — 읽기만 하므로 아무 때나 안전하다
python3 scripts/shutdown_guard.py data/itx.db
python3 scripts/shutdown_guard.py data/itx.db --now 2026-08-14T23:50   # 금요일 밤이면?

sudo cp scripts/systemd/itx-shutdown.service scripts/systemd/itx-shutdown.timer \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now itx-shutdown.timer

systemctl list-timers itx-shutdown.timer    # NEXT 가 다음 평일 23:50 인지 확인
```

호스트 타임존도 KST로 맞춰두면 `journalctl`·`docker compose logs`가 읽기 편해진다
(도메인이 전부 KST다). 타이머는 캘린더 식에 타임존을 직접 적으므로 여기에 의존하지 않는다:

```bash
sudo timedatectl set-timezone Asia/Seoul
```

> `deploy_check.sh`는 `docker logs --since`(상대시각)와 docker API의 UTC 타임스탬프만
> 쓰므로 타임존 변경에 영향받지 않는다 — 확인했다.

#### ③ 첫 주 확인

```bash
journalctl -u itx-shutdown --since '7 days ago'
```

`정지 가능:` / `정지 보류:` 중 하나가 매일 밤 한 줄씩 남는다. **`정지 보류:`만 계속
나온다면 절감이 0이라는 뜻이다** — 사유가 같은 줄에 찍혀 있다.

#### 끄고 싶을 때 (되돌리기)

```bash
sudo systemctl disable --now itx-shutdown.timer
```

기동 쪽은 EventBridge 콘솔에서 일정을 **비활성화**한다. 둘은 독립이라 한쪽만 꺼도 된다 —
다만 **정지만 남기면 아침에 안 켜진다.** 되돌릴 때는 정지부터 꺼라.

#### 손으로 켜야 할 때

주말이나 새벽에 예외적으로 타야 하면 AWS 콘솔(모바일 앱 포함)에서 인스턴스를 시작한다.
1~2분 뒤 `restart: unless-stopped`가 컨테이너를 되살리고 Tailscale도 자동으로 붙는다.
**퍼블릭 IP는 켤 때마다 바뀌지만** tailnet 주소로만 접근하므로 상관없다.

> **가동 시간대를 바꾸려면 세 곳을 함께 바꿔야 한다** — EventBridge cron 식,
> `scripts/shutdown_guard.py`의 `START_TIME`, `itx-shutdown.timer`의 `OnCalendar`.
> 한쪽만 바꾸면 조용히 틀린다: 기동을 07:00으로 늦췄는데 가드가 06:00을 믿으면,
> 06:10 폴을 "기동 후"로 오판해 전날 밤에 인스턴스를 꺼버린다.

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
- **CD가 서버의 `.env`를 건드리게 만들지 마라.** 자격증명은 손으로만 옮긴다 (4절, D-35).
  워크플로에 `.env` 내용이 들어가는 순간 시크릿이 Actions 로그·아티팩트로 샐 경로가 생긴다
- **`tag:ci`에 SSH 말고 다른 권한을 주지 마라.** 러너는 공개 인터넷에 있는 남의 기계다 —
  ACL에서 열어준 것이 `korail-matrix:22` 하나여야 OAuth 시크릿이 새도 피해가 거기서 끝난다
- **폴 포인트 가드를 "그냥 통과시키게" 고치지 마라.** 자꾸 걸리면 `--window-minutes`를
  줄이는 것이지, 가드를 지우는 것이 아니다 (#22, D-51)
