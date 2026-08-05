# ITX 자유석 좌석 매트릭스 조회 서비스 — 기획 및 구현 계획

> 개인용 프로젝트. 앱스토어/퍼블릭 배포 없이 사용.
> 이 문서는 Claude Code로 구현할 때 컨텍스트로 사용한다.
>
> **문서 버전: v9**
> - v1: Spring Boot + Python 사이드카, 알림 봇 중심
> - v2: Python 단일 스택으로 전환
> - v3: 알림을 정식 목표로 승격, 계정(회원) 계층 도입
> - v4: 알림 채널을 iOS 웹푸시 기본 + 디스코드 opt-in으로 확정
> - v5: 지연 대응(DelayPort + 정차역당 2회 조회) + GPS 포그라운드 위치 보정
> - v6: Phase 0 실현 가능성 검증 신설 + 구독 상태 기계(입석/착석) + 알림 체계 재설계(셀 전이 기반) + 운영 디테일 확정
> - v7: 구현 디테일 확정 — 좌석 유니버스/부재 추론, 인덱스·시각 규칙, 폴링 멱등성(next_poll_at), 알림 합성·베이스라인·기기 정리, 공통 구현 규칙(KST·clock 주입·to_thread)
> - v8: Phase 1 구현 중 인증 설계 갱신 — 로그인 유지(세션 수명 이원화) + 가입 잠금을 env에서 관리자 토글로
> - v9: **열차 선택 UX 확정 — 역 드롭다운 + 시각 하한 검색, station 테이블 역할 확장**
>
> "왜 이렇게 했지?"가 궁금하면 [17. 결정 이력](#17-결정-이력-decision-log)을 먼저 읽을 것.
> 방향을 튼 지점은 전부 거기에 이유와 함께 남겨두었다.

---

## 0. 최우선: Phase 0 실현 가능성 검증 (→ D-14)

**아래가 검증되기 전에는 본 구현에 착수하지 않는다.** 반나절짜리 스크립트로 go/no-go를 확인한다.

| # | 검증 항목 | 결과에 따른 분기 | **검증 결과 (2026-08-05)** |
|---|---|---|---|
| 1 | **비로그인으로 좌석맵 조회가 가능한가** | 가능 → 코레일 자격증명 저장 설계(Fernet, `korail_pw_enc`, `PUT /api/me/korail`) **전부 삭제**. 최선 시나리오 | ❌ **NO** — 비로그인 세션의 `ScheduleView`(열차조회) 첫 호출부터 `strResult=FAIL`, `h_msg_cd=MACRO ERROR`. 로그인 여부와 무관하게 차단 |
| 2 | 로그인 필수라면, **예매 이력 없는 조회 전용 계정**으로 좌석맵 접근이 가능한가 | 가능 → 조회용 부계정 사용. 정기권 본계정과 분리해 **세션 충돌(검표 순간 본계정 앱 로그아웃) 리스크 제거** | ⏸ **미검증** — 부계정 미보유. 항목 1·3의 결과상 검증해도 의미 없음(로그인 자체가 `MACRO ERROR`) |
| 3 | **좌석맵 조회가 순수 조회인가** — 호출 후 코레일 앱/계정에 임시 홀드·장바구니 흔적이 남지 않는가 | **No → 프로젝트 재검토.** 조회가 예약 프로세스 개시를 수반하면 정차역당 2회 × 구간 N회 호출의 부하·흔적이 완전히 다른 문제가 됨 | ✅ **YES — 순수 조회 (실측 확정)**. `ResidualSeatsResearch.do` 호출 전/후 `reservations()`(0→0)·`tickets()`(3→3) 무변화 + 폰 코레일 앱 수동 확인(예약승차권/장바구니/발권대기/알림) 무흔적. 서로 다른 구간 분할(천안→영등포, 천안→수원→영등포)로 **2회 재현** |
| 4 | korail2 응답에 **지연 정보**가 포함되는가 (D-12 검증을 여기로 앞당김) | 있음 → DelayPort 실구현이 공짜. 외부 API 검증 불필요 | ✅ **YES (실측 확정)** — `h_expct_dlay_hr`(`delay_time`) 실측값 `'000000'`(무지연). **6자리 포맷** (4자리 hhmm 아님, 파싱 주의) |
| 5 | 열차번호+날짜로 **정차역 목록+역별 도착시각**을 파생할 수 있는가 | 원칙 1의 전제. 안 되면 설계 근간 수정 필요 | ❌ **NO (소스 레벨 확정)** — 열차번호 → 전체 정차역 목록을 주는 함수·엔드포인트가 korail2·letskorail 어디에도 없다. `ScheduleView`는 조회한 dep→arr 한 쌍과 운행 순번(`h_dpt_stn_run_ordr`/`h_arv_stn_run_ordr`)만 준다 → 외부 소스(공공데이터포털 열차 정차역 API 등) 필요 |
| 6 | 좌석맵 응답이 **전체 좌석+상태**를 주는가, **구매 가능 좌석만** 주는가 (→ D-18) | 전체 → 병합이 단순 조인. 구매 가능만 → **부재 추론 규칙** 적용 (5절 '좌석 유니버스') | ✅ **전체 좌석+상태 (실측 확정)** — 인접 구간(천안→수원 vs 수원→영등포) `ResidualSeatsResearch.do` 좌석키 집합이 **완전히 동일**(72석, 양쪽 차집합 `[]`)하고 각 좌석마다 `h_sale_psb_flg`(Y/N)를 포함. **병합 = 단순 조인**, 부재 추론 규칙 불필요 |

검증 우선순위: **3 → 1 → 2 → 5 → 6 → 4.** 3번이 no면 이후는 의미 없음.

### 검증 결과 요약 — **NO-GO (2026-08-05)**

우선순위 1위 항목(3)에 도달하기 전에 **더 앞단에서 막혔다.** 0절이 상정하지 않았던 결과다.

- **좌석맵의 소재는 확인됐다.** korail2에는 좌석 단위 조회 기능이 아예 없다(공개 메서드는
  `login/logout/search_train/search_train_allday/reserve/tickets/reservations/cancel`,
  좌석 정보는 열차 단위 플래그 `h_gen_rsv_cd`뿐). 매트릭스의 원천은 코레일 모바일 API의
  `research.TrainResearch`(호차별 잔여석) / `research.ResidualSeatsResearch.do`(좌석별 판매가능 Y/N)
  두 엔드포인트이며, 이를 감싼 라이브러리는 **letskorail(bsangmin)** 이다.
  구간(출발·도착역 코드 + 운행 순번) + 호차를 인자로 받아 5절 매트릭스 설계와 1:1로 대응한다.
- **그러나 접근이 차단됐다.** 로그인(`login.Login`)과 비로그인 열차조회(`seatMovie.ScheduleView`)
  양쪽 모두 `strResult=FAIL`, `h_msg_cd=MACRO ERROR`,
  "앱을 최신 버전으로 업데이트한 뒤 재실행..." 응답. 즉 **자격증명 문제가 아니라
  비공식 클라이언트 자체에 대한 거부**다. korail2·letskorail 모두 수년간 미갱신 상태다.
- 이 응답만으로는 "자동화 클라이언트 차단"과 "클라이언트 버전이 낡아 거부"를 구분할 수 없다.
  다만 구분이 되더라도 공식 앱을 흉내 내 통과시키는 방향은 **채택하지 않는다** —
  서비스가 자동화를 명시적으로 거부하는 신호이며, 10절·D-17의 호출 예절 원칙과 반대다.
- 따라서 **자격증명 3갈래(6절) 중 어느 것도 확정할 수 없다.** 비로그인·부계정·본계정 모두
  현재 경로에서는 동작하지 않는다.

**검증 로그**: `scripts/phase0_feasibility.py`(step 0~6), 원시 응답은 `scripts/phase0_results/`
(마스킹 후 저장, 커밋 제외). 실 호출은 총 4회(코드 발급 1 / 로그인 1 / 비로그인 조회 1 / 나머지는 로컬 분석).

### 갱신 — 안티봇 우회 PR로 접근 복구, 판정 **조건부 재개 (2026-08-05)**

위 NO-GO의 직접 원인(`MACRO ERROR`)이 해소됐다. korail2 오픈 PR
[#54 "Implement anti-bot bypass"](https://github.com/carpedm20/korail2/pull/54)
(브랜치 `dhfhfk:bypassDynapath`)를 실측한 결과:

- **로그인·열차조회 모두 성공.** PR은 최근 앱 업데이트가 도입한 `x-dynapath-m-token` 헤더 +
  `Sid`를 앱의 토큰 생성 알고리즘을 파이썬으로 재구현해 생성한다(경로가 `DYNAPATH_PATHS`에
  포함될 때만 부착). `_version`도 `250601002`로 최신화. 본계정 로그인 → 천안→영등포 10건 조회 성공.
- **항목 4 = YES (실측 확정)**: 응답의 `h_expct_dlay_hr`(`delay_time`)가 실제로 온다.
  관측값 `'000000'`(무지연). **포맷은 4자리 hhmm이 아니라 6자리** — 실연동 파싱 시 주의.
- **항목 5 = NO 유지**: 우회와 무관하게 ScheduleView는 조회한 dep→arr 한 쌍만 반환. 전체 정차역 파생 불가.
- **항목 3·6 = 아직 미측정**: 좌석맵 엔드포인트(`research.TrainResearch` /
  `research.ResidualSeatsResearch.do`)는 `DYNAPATH_PATHS`에 없어 토큰 없이 **인증 세션만으로**
  호출 가능하다 → 이제 로그인된 세션이 생겼으므로 측정 가능. 항목 3(순수성)이 여전히 최우선 게이트.

**우회 채택 자체가 미결 결정이다.** 코레일이 명시적으로 안티봇을 넣었다는 것은 (1) 다음 앱
업데이트로 토큰 스킴이 또 바뀌어 우회가 깨질 수 있고(어댑터 교체로 대응 가능하나 유지보수 부채),
(2) 서비스가 자동화를 거부하는 신호를 우회하는 것의 정당성 문제가 남는다는 뜻.
개인용·저빈도·조회 전용이라는 본 프로젝트 성격과 이 트레이드오프를 어떻게 볼지는
**항목 3 결과 확인 후 최종 D-항목으로 확정**한다. (→ D-14 연장선)

### 최종 판정 — **GO (2026-08-05)**

항목 3·6 실측 완료. 무궁화호-1472(2026-08-06, 천안→수원→영등포, 1호차)로 측정:

- **항목 3 = 순수 조회 확정.** `ResidualSeatsResearch.do` 호출 전후 `reservations()`(0→0)·
  `tickets()`(3→3) 자동 스냅샷 무변화 + 폰 코레일 앱 수동 확인(예약승차권/장바구니/발권대기/알림)
  무흔적. 서로 다른 구간 분할로 **2회 재현**(천안→영등포 1회, 천안→수원→영등포 1회) — 우연이 아니다.
- **항목 6 = 전체 좌석+상태 확정.** 인접 구간(천안→수원 / 수원→영등포)의 좌석키 집합이 72석
  완전 동일(양쪽 차집합 `[]`), 각 좌석 `h_sale_psb_flg`(Y/N) 포함. PLAN.md 5절 '좌석 유니버스'가
  상정한 **병합=단순 조인**이 맞다. 부재 추론 규칙(합집합 유니버스)은 **불필요** — 구현이 단순해진다.
- 항목 1(비로그인)은 우회 적용 전 기준 NO로 확정된 채 재검증하지 않는다 — 아래 결정에 따라
  본계정 로그인 경로로 확정했으므로 실익이 없다.
- 항목 2(부계정)는 부계정을 보유하지 않아 끝내 미검증. 아래 결정에서 본계정으로 대체한다.

**결론: Phase 0 통과. Phase 1 착수 가능.** 6절 자격증명 3갈래는 "로그인 필수 + 본계정" 갈래로
확정한다 (→ D-22, 6절 갱신). 세션 충돌 리스크(D-14 문제 1)는 미해소 상태로 인수한다 — 실사용 중
검표 시점에 코레일 앱이 로그아웃되는 사례가 관측되면 조회 빈도/타이밍 조정으로 대응한다.

## 1. 배경 및 문제 정의

- 사용자는 ITX 정기권으로 자유석/입석을 이용해 통근한다.
- 빈 좌석에 앉아 가려면 **코레일 앱에서 검색 구간을 계속 바꿔가며** 지금 앉은 좌석이 다음 구간에도 비어있는지 수동으로 반복 확인해야 한다. 이게 매일 반복되는 핵심 불편.
- 사용자가 원하는 것은 두 가지다:
  1. **판단 재료** — 어느 좌석으로 옮길지, 아예 지하철로 갈아탈지를 직접 결정하고 싶다
  2. **최소한의 알림** — 계속 화면을 들여다볼 수는 없으니, 내 자리가 팔린 것 정도는 먼저 알려줘야 한다
- 탑승 중 사용자는 두 상태 중 하나다: **입석(STANDING)** — 앉을 자리를 찾는 중 / **착석(SEATED)** — 특정 좌석에 앉아 있고, 그 좌석이 팔리면 비켜야 함. 두 상태는 필요한 정보와 알림이 다르다. (→ D-15)
- 결론: **좌석 × 정차구간 점유 매트릭스 대시보드 + 상태 기반 알림**을 갖춘 개인용 웹앱(PWA).

## 2. 목표 / 비목표

### 목표
- 열차번호 + 날짜 + (탑승역, 하차역)으로 좌석 × 구간 매트릭스 시각화
- 상단 자동 판정 요약:
  - 내 자리 상태 ("수원부터 판매됨") — 착석 시
  - 이동/착석 추천 ("4호차 1B — 서울까지 빈 좌석")
  - 대안 판정 ("수원 이후 전 좌석 매진 → 지하철 환승 고려")
- **상태 기반 알림** (→ 상세는 8절)
  - [입석] 정차역 진입 시 앉을 수 있는 좌석 다이제스트
  - [착석] 내 자리가 잔여 이용구간 내에서 판매됨 ★ 최우선
  - [착석] 내 자리의 이용 가능 구간이 연장됨 (취소/환불 발생)
  - [공통] 잔여 좌석 0 → 지하철 환승 판단이 필요함
  - [공통] 조회 실패 → 화면 데이터가 낡았음
- **탑승 상태 전이 입력** — 앉음 / 자리 이동 / 일어남을 앱에서 한 번의 탭으로 반영 (→ D-15)
- 정차역 도착 전(기본 -10분/-4분) 자동 재조회
- **계정 로그인** — 서버가 사용자를 식별하고, 프리셋·구독·푸시 기기를 사용자에 귀속
  (코레일 자격증명 저장 여부는 Phase 0 결과에 따름 → 0절, D-14)
- 자주 쓰는 구간/열차를 프리셋으로 저장
- iPhone 사파리 "홈 화면에 추가"(PWA)

### 비목표
- 앱스토어 배포, 네이티브 iOS 앱 (→ D-1)
- 예매/발권 (조회 전용)
- 공개 서비스 운영, 회원가입 개방 (계정은 있으나 가입은 부트스트랩 1회로 잠금 → D-10)
- 소셜 로그인/OAuth (1~2인용에 과함)

## 3. 핵심 설계 원칙

### 원칙 1 — 역/노선/구간을 하드코딩하지 않는다
모든 노선 정보는 **열차번호에서 조회 시점에 파생**시킨다.
열차번호+날짜 → 코레일 조회 → 실제 정차역 목록 → 인접 구간 N-1개 생성.
매트릭스 로직은 "수원"이라는 단어를 모른다.
→ 정차 패턴이 다른 열차도 **코드 수정 없이** 동작. 새 구간 = 프리셋 행 추가.

### 원칙 2 — 외부 연동은 전부 Port 뒤로 격리
바뀔 수 있는 것은 인터페이스 뒤에 둔다.
- `KorailPort` — 비공식 API. **언제 깨져도 이상하지 않은** 가장 취약한 지점
- `DelayPort` — 열차 지연 정보. 소스 미확정이므로 기본 구현은 "지연 0" (→ D-12)
- `NotifierPort` — 웹 푸시 / 디스코드. iOS 웹푸시 신뢰성이 낮아 보조 채널 여지가 필요 (→ D-9, D-11)

### 원칙 3 — 사용자 귀속 데이터는 코드가 아니라 DB에
프리셋, 구독, 푸시 기기 전부 `user_id`로 묶는다.
새 구간 지원 = 행 추가. 새 기기 = 행 추가. (→ D-10)

### 원칙 4 — 스케줄러는 구독 기반
하드코딩 cron이 아니라 **활성 구독 테이블**을 읽어 각 열차 시각표 기준으로 폴링.
구간·사용자·기기가 늘어도 스케줄러 코드는 그대로.

### 원칙 5 — 판정 로직은 순수 함수로, 반드시 테스트한다
외부 의존이 없어 테스트가 쉽고, **틀려도 조용히 틀리는** 유일한 지점이다.
어댑터가 깨지면 에러가 나서 즉시 알지만, 판정 로직이 틀리면 "빈 줄 알고 앉았다가 쫓겨난다".
실사용 후 조정될 가능성이 높은 값(추천 랭킹, 알림 임계값)은 **설정값을 가진 순수 함수로 격리**해 패치를 한 줄로 만든다. (→ D-17)

### 원칙 6 — 알림은 상태 변화에만 발송한다 *(v6 정밀화)*
"**동일 상태의 중복 발송 금지**"로 정의한다. 매 폴링마다 쏘면 무시하게 되고, 무시하는 알림은 없느니만 못하다.
- 입석 상태에서는 **현재 구간도 상태의 일부**다 — 구간이 진행되면 상태가 바뀐 것이므로 정차역당 최대 1회 다이제스트가 성립한다 (→ 8절, D-16)
- "무엇이 상태인가"(해시 대상)는 8절에 알림 종류별로 명시한다. 여기가 흐리면 좌석 상황이 그대로인데 알림이 나가는 스퍼리어스 발송이 생긴다

### 공통 구현 규칙 *(v7 → D-21)*
구현자가 임의로 정하면 조용히 틀리는 전역 규칙. 전 코드베이스에 일괄 적용한다.
- **시간대**: 모든 datetime은 **KST aware**(`ZoneInfo("Asia/Seoul")`). naive datetime 금지.
  `date`는 열차 **운행일** 기준 (자정 넘김 열차의 경계 혼동 방지)
- **clock 주입**: 스케줄러·판정·구간 추정 등 시간 의존 함수는 전부 `now: datetime`을
  **인자로 받는다**. 없으면 Phase 1 목업으로 "시간이 흐르는" 시나리오 테스트가 불가능하다
- **동기 라이브러리 격리**: korail2는 requests 기반 **동기** 라이브러리다. async 앱에서
  직접 부르면 이벤트 루프가 통째로 멈춰 병렬 조회 설계가 무력화된다.
  어댑터에서 반드시 **`asyncio.to_thread`로 감싼다** (Semaphore 동시성 제한은 그대로 유효)
- **코레일 세션 재사용**: 폴링마다 로그인하면 그 자체가 공격적 트래픽. 어댑터가 세션을
  프로세스 내 캐시하고, **만료 감지 시에만 1회 재로그인**

## 4. 시스템 아키텍처

```
[iPhone Safari PWA]  ── 홈 화면에 추가
      │  HTTPS (Tailscale ts.net 도메인, 공개 노출 없음)
      │  + 세션 쿠키 인증
      ▼
┌──────────────────────────────────────────────┐
│  FastAPI 단일 앱 (Python 3.12)                │
│                                               │
│  api/         REST 엔드포인트 + 인증 의존성      │
│  auth/        세션 로그인, 비밀번호 해시         │
│  domain/      매트릭스 병합 + 판정 로직          │
│               (순수 함수, 외부 무지)             │
│  adapters/    KorailPort  ├ Mock  └ Korail2    │
│               DelayPort   ├ Zero  └ (공공API)   │
│               NotifierPort ├ WebPush └ Discord │
│  scheduler/   APScheduler 구독 폴링 + 알림 발송  │
│  storage/     SQLite (user/preset/subscription │
│                       /push_device/cache)      │
└──────────────────────────────────────────────┘
      │                          │
      ▼                          ▼
[코레일 비공식 API]        [웹푸시 / 디스코드 웹훅]
   (korail2 경유)
```

**컨테이너 1개.** v1의 파이썬 사이드카는 삭제됐다 (→ D-4).
**uvicorn worker는 반드시 1개** — APScheduler가 인프로세스라 2개면 폴링·알림이 중복 발사된다. (→ D-17)

### 스택
| 영역 | 선택 | 이유 |
|---|---|---|
| 웹 프레임워크 | FastAPI | 비동기 네이티브, 자동 OpenAPI 문서 |
| 모델/검증 | Pydantic v2 | v1의 Java record를 거의 그대로 이식, 타입 안정성 회복 |
| 코레일 연동 | korail2 | 역공학 결과물. 직접 포팅 대비 유지보수 비용 최소 |
| 인증 | 세션 쿠키 + argon2(passlib) | JWT보다 단순, 즉시 무효화 가능 (→ D-10) |
| 비밀 암호화 | cryptography Fernet | 코레일 비밀번호·웹훅 URL 저장용 대칭키 (Phase 0 결과에 따라 축소 가능) |
| 웹 푸시 | pywebpush + VAPID | iOS 16.4+ 홈화면 앱 지원 |
| 스케줄러 | APScheduler | 앱 내부 인프로세스 (worker=1 전제) |
| HTTP | httpx | 비동기, 병렬 구간 조회 |
| DB | SQLite (stdlib) | 1~2인용 · 행 수십 개 수준 |
| 의존성 | uv | 빠르고 lock 재현성 좋음 |
| 프론트 | React (Vite) + 바닐라 CSS | 프로토타입이 이미 React |

### 배포/보안 (요약, 상세는 12절)
- **AWS EC2 t4g.nano (서울 리전, ARM/Graviton)** (→ D-6)
- Docker 단일 컨테이너, `restart: unless-stopped`
- **Tailscale로만 접근**, 보안그룹 인바운드 전부 차단
- `tailscale serve`의 `*.ts.net` 신뢰 HTTPS → PWA 홈화면 추가 + 웹 푸시 정상 동작
  (자체서명 인증서로는 **안 된다**. 결정적 디테일 → D-8)
- **네트워크 격리와 계정 인증을 함께 쓴다** (이중 방어 → D-10)

## 5. 도메인 모델

```python
from pydantic import BaseModel
from datetime import date, datetime
from enum import Enum
from typing import Protocol, Literal

# ── 사용자 ──────────────────────────────────
class User(BaseModel):
    id: int
    email: str
    display_name: str
    created_at: datetime
    # korail_id / korail_pw_enc 는 (필요한 경우에만) DB에만, API 응답에 절대 노출 금지

# ── 구독 상태 (→ D-15) ──────────────────────
class SubscriptionStatus(str, Enum):
    STANDING = "STANDING"   # 입석 — 앉을 자리를 찾는 중
    SEATED   = "SEATED"     # 착석 — my_car / my_seat_no 필수

# ── 좌석 매트릭스 ────────────────────────────
class Segment(BaseModel):
    from_station: str
    to_station: str
    idx: int

class SeatRow(BaseModel):
    car: int
    seat_no: str
    cells: list[bool]          # 구간별 판매 여부, len == len(stops) - 1

class SeatMatrix(BaseModel):
    train_no: str
    date: date
    stops: list[str]           # 조회로 파생된 정차역 (순서 보장)
    seats: list[SeatRow]
    fetched_at: datetime

class SeatRecommendation(BaseModel):
    car: int
    seat_no: str
    clear_until_idx: int
    clear_all: bool

class Verdict(BaseModel):
    sub_status: SubscriptionStatus
    # ── SEATED일 때만 채워짐, STANDING이면 None ──
    my_seat_status: Literal["CLEAR_ALL", "SOLD_FROM", "UNKNOWN"] | None
    my_seat_sold_from: str | None
    my_seat_clear_until_idx: int | None
    # ── 공통 ──
    move_to: list[SeatRecommendation]      # STANDING: 착석 추천 / SEATED: 이동 추천
    all_sold_after_current: bool           # True → "지하철 환승 고려"
    current_seg_idx: int

# ── 알림 (→ 8절, D-16) ─────────────────────
class AlertKind(str, Enum):
    SEATS_AVAILABLE = "SEATS_AVAILABLE"  # [입석] 다음 구간부터 앉을 수 있는 좌석 다이제스트
    MY_SEAT_SOLD    = "MY_SEAT_SOLD"     # [착석] 내 자리가 잔여 구간 내 판매됨 (구 RECOMMEND_CHANGED 흡수)
    SEAT_EXTENDED   = "SEAT_EXTENDED"    # [착석] 내 자리 이용 가능 구간 연장 (셀 전이 감지)
    ALL_SOLD        = "ALL_SOLD"         # [공통] 잔여 0 → 환승 판단 필요
    FETCH_FAILED    = "FETCH_FAILED"     # [공통] 한 조회 시점 내 3회 실패, 데이터 낡음

class Alert(BaseModel):
    kind: AlertKind
    title: str
    body: str
    subscription_id: int
```

```python
class KorailPort(Protocol):
    async def get_stops(self, cred: KorailCred | None, train_no: str, d: date) -> list[StopInfo]:
        """정차역 + 역별 도착시각 (순서 보장). 시각은 스케줄러가 사용.
        cred는 Phase 0 결과에 따라 None 허용(비로그인) 가능."""
        ...
    async def get_seat_map(self, cred: KorailCred | None, train_no: str, d: date,
                           frm: str, to: str) -> SeatMap:
        """특정 인접 구간의 좌석별 판매 여부."""
        ...

class NotifierPort(Protocol):
    async def send(self, user_id: int, alert: Alert) -> bool:
        """실패 시 False."""
        ...

class DelayPort(Protocol):
    async def get_delay_minutes(self, train_no: str, d: date) -> int | None:
        """현재 지연 분. None = 정보 없음(지연 0으로 간주).
        기본 구현 ZeroDelayAdapter는 항상 None을 반환한다.
        korail2 응답 내 지연 정보 확인(Phase 0-4) 후 실구현으로 교체. (→ D-12, D-14)"""
        ...
```

### DB 스키마 (SQLite)
```sql
user(id, email UNIQUE, password_hash, display_name,
     is_admin DEFAULT 0,             -- 첫 계정에만 자동 부여. 가입 허용 토글 권한 (→ D-24)
     korail_id, korail_pw_enc,       -- Phase 0-1 결과 '비로그인 가능'이면 두 컬럼 삭제
     discord_webhook_enc,            -- NULL이면 미연동
     discord_enabled DEFAULT 0,      -- 연동해도 켜야만 발송 (opt-in 2단계)
     created_at)

session(token PK, user_id FK, created_at, expires_at, user_agent,
        persistent DEFAULT 0)        -- '로그인 유지' 여부. 슬라이딩 연장 수명을 가른다 (→ D-23)

app_setting(key PK, value, updated_at, updated_by FK)
            -- 관리자가 런타임에 바꾸는 설정. 현재 키: signup_enabled (→ D-24)

preset(id, user_id FK, name, from_station, to_station,
       usual_train_nos JSON,
       poll_offsets_min JSON DEFAULT '[10, 4]')  -- 정차역 도착 n분 전 조회 시점들

subscription(id, user_id FK, train_no, date, board_at, alight_at,
             status TEXT CHECK(status IN ('STANDING','SEATED')),  -- → D-15
             my_car, my_seat_no,        -- SEATED일 때만 NOT NULL (앱 레벨 검증)
             active, created_at,
             last_verdict_hash,         -- 원칙 6: 변화 감지용. ★스케줄러만 기록
             last_cells_snapshot JSON,  -- 내 좌석의 직전 조회 셀 상태. SEAT_EXTENDED 전이 감지용 (→ D-16)
             next_poll_at,              -- 다음 폴 포인트. 재시작 내구성의 핵심 (→ D-19)
             last_notified_at, fail_count)

station(code PK, name, lat, lng)       -- 공공데이터 정적 참조.
             -- 용도 2개: ① GPS 보정 좌표 (→ D-13) ② 역 선택 드롭다운 소스 (→ D-25)

push_device(id, user_id FK, endpoint, p256dh, auth, label, created_at)
            -- 기기별 1행. 폰/아이패드 동시 지원

matrix_cache(train_no, date, frm, to, fetched_at, payload JSON)
             -- 60초 TTL, 화면 트래픽 전용 (→ D-17). 키에 조회 범위 포함 (→ D-18)
```

### 인덱스 규칙 — 전체 노선 vs 내 이용구간 *(v7 → D-18)*
`get_stops()`는 열차의 **전체 노선**을 반환한다 — 사용자가 천안→서울이어도 열차는 대전발일 수 있다.
혼동을 막기 위해 규칙을 고정한다:
- 모든 인덱스(`current_seg_idx`, `clear_until_idx` 등)는 **전체 노선 `stops` 기준**
- **실효 시작 = `max(current_seg_idx, board_idx)`** — 조회 범위·판정·알림은 전부
  `실효 시작 ~ alight_idx`로 통일. 탑승역 이전 구간은 열차가 어디를 달리든 관심 밖
- 부수 효과 — **탑승 전 다이제스트가 공짜로 생긴다**: 열차가 아직 탑승역에 오지 않았을 때
  첫 조회(-10분)가 자연히 "탑승 전 착석 가능 좌석" 알림이 된다.
  "4호차가 비니 승강장 뒤쪽에 서라"는 실사용 가치가 커서 버그가 아니라 **기능으로 명문화**한다

### 현재 구간 추정 — 시각 규칙 *(v7 → D-18)*
"평택 정차 중"일 때 현재 구간이 어디인지 미정의면 조용히 틀린다. 규칙:
- `current_seg_idx = max i s.t. 실효도착(stops[i]) ≤ now` — **도착시각만 기준**
  (실효 도착 = 시각표 도착 + 지연분, 9절과 동일. v9까지 `arrival ≤ now + 지연보정`으로
  적혀 있었으나 **부호가 반대**였다 → D-26)
- 역 정차 중에는 **그 역부터의 구간**을 본다 — "이번 역에서 탈 사람이 산 자리"를
  판정해야 하므로 이게 맞는 방향
- 순수 함수 `estimate_seg(stops_with_times, delay_min, now)`로 분리, `now`는 인자 (→ 공통 구현 규칙)

### 매트릭스 병합 (domain/matrix.py)
1. `get_stops()` → 정차역 N개 → 인접 구간 생성
2. **조회 범위는 실효 시작~하차역으로 한정** — 지나온 구간·탑승 전 구간은 판정·표시 모두에 불필요하므로 호출하지 않는다. 호출량이 절반 이하로 줄고 제재 리스크도 함께 준다 (→ D-17, D-18)
3. 구간별 `get_seat_map()` **병렬 호출**
   ```python
   sem = asyncio.Semaphore(3)          # 코레일 부하/제재 방지
   async def fetch(seg):
       async with sem:
           await asyncio.sleep(random.uniform(0.1, 0.4))   # 지터
           return await port.get_seat_map(...)
           # Port 인터페이스는 async 유지. korail2가 동기이므로 어댑터 '내부'에서
           # asyncio.to_thread로 감싸는 것은 어댑터의 책임 (→ 공통 구현 규칙)
   maps = await asyncio.gather(*(fetch(s) for s in segments))
   ```
4. 좌석 키(`car-seat_no`)로 조인 → `SeatMatrix` (미조회 과거 구간 셀은 `past` 마킹)
5. **60초 TTL 캐시** — 화면 새로고침 연타가 코레일 재호출로 이어지지 않게.
   캐시 키는 `(train_no, date, frm, to)` — 조회 범위가 다르면 다른 캐시 항목 (범위 불일치 방지).
   **스케줄러는 이 캐시를 우회하고 항상 실조회한다** — 캐시는 사용자 화면 트래픽 흡수 전용 (→ D-17)

### 좌석 유니버스 — "응답에 없는 좌석"의 의미 *(v7 → D-18, Phase 0-6 결과에 따라 분기)*
- 좌석맵이 **전체 좌석+상태**를 주면: 단순 조인으로 끝 (최선)
- **구매 가능 좌석만** 주면 부재 추론이 필요하다:
  - **유니버스 = 조회한 전 구간 응답의 합집합**
  - 특정 구간 응답에 없는 좌석 → 그 구간은 **판매됨(true)** 으로 채움
  - **알려진 구멍**: 잔여 전 구간에서 팔린 좌석은 유니버스에서 아예 사라진다.
    추천 대상으로는 무해하지만(어차피 추천 불가), **내 좌석이 사라질 수 있다** → 판정 규칙으로 처리(하단)

### 판정 로직 (domain/verdict.py) — 순수 함수, 테스트 필수
- 입력에 `SubscriptionStatus`를 명시적으로 받는다 (STANDING이면 my_seat 관련 판정 생략)
- **내 좌석 부재 규칙 (v7 → D-18)**: SEATED인데 내 좌석 키가 매트릭스에 없으면
  **잔여 전 구간 판매로 간주** → `my_seat_status = SOLD_FROM`, `sold_from = 다음 정차역`.
  이 규칙이 없으면 KeyError 아니면 UNKNOWN으로 조용히 빠진다. test_verdict.py 케이스 필수
- `clear_until(seat, current_idx)`: 현재 구간부터 연속으로 비어있는 마지막 역 인덱스
- `clear_all(seat, current_idx, alight_idx)`: 하차역까지 전 구간 빈자리 여부
- 추천: `clear_all == True` 좌석을 정렬해 리스트로 제시
  - SEATED: **현재 호차 근접순** (이동 거리 최소화)
  - STANDING: 호차 기준 없음 → clear_until 내림차순
  - 랭킹 함수는 설정값을 가진 순수 함수로 격리 — 실사용 후 조정 용이 (→ D-17)
- `clear_all` 좌석이 없으면 `clear_until` 최댓값 좌석 제시 ("최소 안양까지는 확보")
- 남은 전 구간 × 전 좌석 매진 → `all_sold_after_current = True`
- **한계 명시: "빈 좌석 ≠ 착석 가능"** — 판매 데이터상 비어 있어도 다른 입석 승객이 이미 앉아 있을 수 있다. 시스템이 해결할 수 없는 한계이며, **추천을 단수가 아니라 리스트로 유지하는 근거**다 (1순위가 점유돼 있으면 2순위로) (→ D-17)
- (Phase 4) 2회 이동 조합 탐색 — 구간 커버리지 문제로 풀이 가능

## 6. 인증 설계

### 방식
- **이메일 + 비밀번호 → 서버 세션 쿠키** (`HttpOnly`, `Secure`, `SameSite=Lax`)
- 비밀번호 해시: **argon2id** (argon2-cffi). 직접 구현 금지
- 세션은 DB 테이블. 재접속 시 슬라이딩 연장
- JWT를 쓰지 않는 이유: 1~2인용에서는 세션 테이블이 더 단순하고,
  기기 분실 시 **즉시 무효화**가 되며, 리프레시 토큰 로직이 통째로 불필요 (→ D-10)

### 로그인 유지 (remember me) — 세션 수명 이원화 *(v8 → D-23)*
로그인 폼의 **"로그인 유지" 체크박스**로 세션 수명을 두 갈래로 나눈다.
쿠키와 서버 세션 **양쪽 모두**를 바꾼다 — 쿠키만 세션 쿠키로 해봐야 서버 세션이
30일 살아 있으면 탈취된 토큰의 유효기간은 그대로다.

| 체크 | 쿠키 | 서버 세션 만료 | 용도 |
|---|---|---|---|
| **on** (지속) | `Max-Age` 30일 | 30일 (슬라이딩) | 내 폰 홈화면 앱 — 매일 쓰는 기본 경로 |
| **off** (기본값) | `Max-Age` 없음 = 브라우저 세션 쿠키 | **12시간** (슬라이딩) | 공용/임시 브라우저 |

- 기본값은 **해제**다. 보안 기본값을 안전한 쪽에 둔다
- `session.persistent` 컬럼에 어느 갈래인지 기록한다 — 슬라이딩 연장 시 같은 수명으로 늘려야 하므로
- 수명은 설정값(`SESSION_DAYS`, `SESSION_TRANSIENT_HOURS`)으로 격리 (D-17 원칙)

### 가입 잠금 — 관리자 토글 *(v8, D-10 개정 → D-24)*
- 가입 허용 여부는 **env가 아니라 DB**(`app_setting.signup_enabled`)에 둔다.
  기본값은 **false**(잠김) — "열어둘 이유가 없는 엔드포인트는 닫는다"는 D-10의 취지는 유지
- **첫 계정은 부트스트랩으로 항상 허용**한다 (사용자 0명이면 잠금과 무관하게 가입 가능).
  그 첫 계정이 **관리자**(`user.is_admin = 1`)가 된다
- 관리자는 `GET/PATCH /api/admin/settings`로 가입 허용을 켜고 끈다.
  지인에게 계정을 열어줄 때 **재배포 없이** 켰다 끄면 된다
- 관리자 지정은 첫 계정 자동 부여뿐이다. 승격 API는 만들지 않는다 (1~2인용에 과함 —
  필요하면 DB에서 직접 바꾼다)

### 코레일 자격증명 — **확정: 로그인 필수 + 본계정 + 안티봇 우회 의존** (Phase 0 결과, → D-14, D-22)
부계정 미보유로 항목 2가 끝내 미검증됐고, 개인용·저빈도·조회 전용이라는 프로젝트 성격상
본계정 하나로 진행하기로 확정했다 (→ D-22). 세션 충돌(D-14 문제 1, 검표 순간 코레일 앱
로그아웃 가능성)은 **미해소 리스크로 인수**한다 — 실사용 중 관측되면 재검토.
- `korail_pw_enc`는 **Fernet 대칭키 암호화**, 키는 env `SECRET_KEY`
- API 응답에 절대 포함하지 않는다. 설정 화면에서는 "등록됨/미등록"만 표시
- `KorailPort`의 korail2 어댑터는 **korail2 PR #54(`dhfhfk:bypassDynapath`) 기반**으로 구현한다
  (→ D-22). korail2 본체는 PyPI 정식 릴리스(`korail2>=0.4.0`)에 그대로 의존하고, DynaPath
  우회(토큰 생성 + 헤더 부착) 로직만 `adapters/` 안에 **벤더링**한다 — 원본은
  `https://github.com/dhfhfk/korail2.git` `bypassDynapath` 브랜치, 고정 커밋
  `4b134266fff097ea0fd54e9f760cb128b6c8f878` (2026-08-05 확인). 브랜치가 rebase/삭제돼도
  이 저장소 안의 벤더 코드는 영향받지 않는다 (확정, D-22 개정)

### 프론트
- 최초 1회 로그인(+ "로그인 유지" 체크) 후 세션 쿠키가 유지되므로
  **홈화면 앱에서 매번 로그인할 일은 없다**
- 401 응답 시 로그인 화면으로 라우팅
- 설정 화면에 로그아웃 + (관리자에게만) 가입 허용 토글

## 7. REST API

```
POST   /api/auth/signup      { email, password, display_name, remember? }
       # 사용자 0명(부트스트랩) 또는 signup_enabled=true일 때만. 첫 계정은 관리자 (→ D-24)
POST   /api/auth/login       { email, password, remember? } → Set-Cookie
       # remember=true면 지속 쿠키 30일, 아니면 브라우저 세션 쿠키 + 12시간 (→ D-23)
POST   /api/auth/logout
GET    /api/me               → { id, email, display_name, is_admin, korail_linked: bool }

GET    /api/admin/settings                    → { signup_enabled: bool }   # 관리자만 (403)
PATCH  /api/admin/settings   { signup_enabled: bool }                      # 관리자만 (→ D-24)
PUT    /api/me/korail        { korail_id, korail_pw }   # Phase 0 결과 '로그인 필수'일 때만 존재
PUT    /api/me/discord       { webhook_url }            # 암호화 저장, 저장 시 테스트 발송
PATCH  /api/me/discord       { enabled: bool }          # 알림 on/off 토글
DELETE /api/me/discord                                  # 연동 해제

GET    /api/stations
       → 역 목록 (출발/도착역 드롭다운 소스). Phase 1은 Mock 노선, Phase 2는 station 테이블 (→ D-25)

GET    /api/trains/search?date=&from=&to=&time=
       → 열차 목록 (열차번호 선택용). time = "이 시각 이후 출발" 하한 (HH:MM, → D-25)

GET    /api/trains/{train_no}/matrix?date=&board_at=&alight_at=&my_seat=&lat=&lng=
       → SeatMatrix + Verdict 통합 응답  ★ 프론트의 유일한 핵심 호출
       my_seat는 선택 (없으면 STANDING 관점 판정)
       lat/lng는 선택. 있으면 current_seg_idx를 GPS 실측으로 보정 (→ D-13)
       조회 범위는 현재 구간~하차역 (→ 5절)

GET    /api/presets      POST /api/presets      DELETE /api/presets/{id}
       → { name, from_station, to_station, usual_train_nos[], poll_offsets_min[] }

POST   /api/subscriptions
       { train_no, date, board_at, alight_at, status, my_car?, my_seat_no? }
       → 오늘 탑승 세션 등록. status=SEATED면 my_car/my_seat_no 필수 (422 검증)
PATCH  /api/subscriptions/{id}   { status?, my_car?, my_seat_no? }   ★ 상태 전이 (→ D-15)
       → "여기 앉았음" (STANDING→SEATED), "자리 옮겼음" (좌석 변경), "일어났음" (SEATED→STANDING)
DELETE /api/subscriptions/{id}                    # 하차/취소

POST   /api/push/devices    { endpoint, keys, label }    → 기기 등록
DELETE /api/push/devices/{id}
POST   /api/push/test                                    → 테스트 발송 ★
```

> **모든 `/api/*`는 세션 인증 필수** (`Depends(current_user)`).
> 쿼리·바디에 `user_id`를 받지 않는다. 항상 세션에서 꺼낸다. (IDOR 방지)

> `/api/push/test`를 반드시 만들 것. iOS 웹푸시는 조용히 실패하는 일이 잦아서,
> **테스트 버튼이 없으면 알림이 안 오는 게 버그인지 iOS 문제인지 구분할 수 없다.**

`/matrix` 응답 예시:
```json
{
  "train_no": "1004",
  "date": "2026-08-05",
  "stops": ["천안","평택","수원","안양","영등포","서울"],
  "current_seg_idx": 1,
  "position_source": "gps",
  "delay_minutes": 4,
  "seats": [
    { "car": 3, "seat_no": "7A", "cells": [true,true,true,false,false] }
  ],
  "verdict": {
    "sub_status": "SEATED",
    "my_seat_status": "SOLD_FROM",
    "my_seat_sold_from": "수원",
    "my_seat_clear_until_idx": 2,
    "move_to": [{ "car": 4, "seat_no": "1B", "clear_until_idx": 5, "clear_all": true }],
    "all_sold_after_current": false,
    "current_seg_idx": 1
  },
  "next_poll": { "station": "수원", "offset_min": 4 },
  "fetched_at": "2026-08-05T08:14:02+09:00"
}
```

## 8. 알림 설계 *(v6 전면 재설계 → D-16)*

### 발송 조건 (이것만. 늘리지 말 것)

| 종류 | 상태 | 트리거 | 문구 예시 |
|---|---|---|---|
| `SEATS_AVAILABLE` | 입석 | 구간 진행(정차역 진입) 시 착석 가능 좌석 존재. **정차역당 최대 1회 다이제스트**, 같은 역의 -10분/-4분 조회 사이엔 내용이 달라졌을 때만 갱신 발송 | "수원부터 착석 가능: 4-1B (서울까지) 외 2석" |
| `MY_SEAT_SOLD` ★ | 착석 | 내 좌석이 **잔여 이용구간 내** 어디서든 판매됨. SOLD_FROM 상태가 지속되는 동안은 준-입석으로 취급해 **최상위 추천이 바뀌면 재발송** (구 `RECOMMEND_CHANGED` 흡수) | "3-7A 수원부터 판매됨 → 4호차 1B로 이동" / "1B 판매됨 → 4호차 4B로 변경" |
| `SEAT_EXTENDED` | 착석 | 내 좌석의 잔여 구간 셀 중 **판매(true)→빈자리(false) 전이** 발생. 실제 취소/환불과 1:1 대응 (하단 '감지 방식' 참고) | "3-7A 안양까지로 연장됨 (이동 불필요)" / "3-7A 서울까지 확보 — 이동 불필요" |
| `ALL_SOLD` | 공통 | 남은 구간에 앉을/옮길 좌석 전무 | "수원 이후 잔여 없음 → 1호선 환승 고려" |
| `FETCH_FAILED` | 공통 | **한 조회 시점 내 30초 간격 3회 재시도 모두 실패** (→ D-17) | "좌석 정보 갱신 실패 · 화면 데이터 낡음" |

**알림 시점 = 조회 시점이다.** 조회가 있어야 변화를 알 수 있으므로,
**조회 시점(정차역 도착 -10분 / -4분)이 알림 타이밍을 결정**한다:
- **-10분 조회**: 환승처럼 **결정에 시간이 필요한** 변화(`ALL_SOLD`)를 여유 있게 포착
- **-4분 조회**: 도착 직전 막판 발권을 포착. 자리 이동은 4분이면 충분

### SEAT_EXTENDED 감지 방식 — 셀 전이 기반 (clear_until 비교 금지)
`clear_until` 증가를 트리거로 쓰면 **열차가 판매 구간을 지나치기만 해도** 값이 점프해
취소가 없었는데 "연장" 알림이 나간다 (스퍼리어스 발송). 따라서:
- 트리거 = `last_cells_snapshot`과 현재 조회의 **셀 단위 비교**에서 잔여 구간 내 `true→false` 전이 검출
- 사용자 실경험상 **출발 후 취소는 희귀 이벤트**이므로 한 구간 연장까지 모두 발송한다.
  조정 손잡이로 `min_extension_segments: int = 1`을 순수 함수 설정값으로 두되, 기본값 1(전부 발송) 유지 (→ D-16)

### 상태 정의 (last_verdict_hash의 해시 대상) — 명시적으로 고정
| 구독 상태 | 해시 튜플 |
|---|---|
| STANDING | `(current_seg_idx, 최상위 추천 좌석 키, all_sold_after_current)` |
| SEATED | `(my_seat_status, my_seat_sold_from, my_seat_clear_until_idx, 최상위 추천 좌석 키, all_sold_after_current)` |

- `move_to` **전체 리스트와 정렬 순서는 해시에서 제외** — 하위 추천의 미세 변동으로 알림이 나가면 안 됨
- `SEAT_EXTENDED`는 해시가 아니라 `last_cells_snapshot` 전이로 감지 (해시는 "달라졌나"만 답하고 방향을 모름)
- 이 표는 test_alerts.py에서 케이스로 잠근다: **"구간만 진행됐을 때(SEATED) 알림이 나가지 않는다"**, "하위 추천 순서만 바뀌었을 때 침묵한다"

### 합성 규칙 — 폴링 시점당 푸시 최대 1건 *(v7 → D-20)*
한 조회에서 여러 종류가 동시에 성립할 수 있다 (예: `MY_SEAT_SOLD` + `ALL_SOLD` —
"이동하라"와 "이동할 곳 없다"가 각각 오면 모순 메시지 2건).
- **우선순위: `ALL_SOLD` > `MY_SEAT_SOLD` > `SEATS_AVAILABLE` > `SEAT_EXTENDED`**
- 상위 종류가 하위의 내용을 **본문에 흡수**해 한 건으로 합성:
  "3-7A 수원부터 판매됨 · 잔여 없음 → 1호선 환승 고려"
- `FETCH_FAILED`는 성립 시 다른 종류가 애초에 계산 불가이므로 합성 대상 아님

### 첫 폴링 베이스라인 알림 *(v7 → D-20)*
`last_verdict_hash`가 NULL인 **첫 조회는 항상 1건 발송**한다:
- SEATED: "3-7A 서울까지 안전" (또는 현재 상태)
- STANDING: 착석 가능 다이제스트
- 목적 2가지: ① 유용한 초기 상태 확인 ② **알림 파이프라인이 오늘 살아있다는 생존 확인** —
  iOS 웹푸시 불신 문제(D-9)의 실전 완화책. 매일 타는 열차에서 첫 알림이 안 오면 그날 푸시가 죽은 것

### 발송 원칙
- **동일 상태 중복 발송 금지** (원칙 6, v6 정밀화)
- 알림에는 **항상 다음 행동**을 담는다. "자리 팔렸음"만으로는 앱을 열어야 하므로 의미가 반감.
  이동/변경 알림에는 "이동했으면 앱에서 내 자리 갱신" 유도 문구 포함 (→ D-15)
- `SEATS_AVAILABLE` 다이제스트는 **상위 3석**(clear_all 우선)까지만 + "외 N석" —
  상한은 설정값으로 격리 (→ D-17, D-20)
- 하차역 도착 시각 경과 시 구독 자동 만료 → 알림 자동 중단
- `FETCH_FAILED`는 1회 발송 후 복구까지 재발송 없음 (실패 알림 스팸 방지)
- **한계**: 추천 좌석이 판매 데이터상 비어 있어도 입석 승객이 점유 중일 수 있다.
  그래서 알림 본문의 추천도 화면의 추천도 **복수 후보를 전제**로 한다 (5절, → D-17)

### 채널 (`NotifierPort`)

| 채널 | 역할 | 활성 조건 |
|---|---|---|
| **WebPushNotifier** | **기본. 항상 발송** | push_device 등록만 하면 됨 |
| **DiscordNotifier** | 보조. 웹훅 URL로 발송 | 사용자가 **① 웹훅 연동 + ② 토글 on** 둘 다 했을 때만 |

- 디스코드는 **봇이 아니라 웹훅**으로 구현한다. 사용자가 자기 서버 채널에서
  웹훅 URL을 만들어 설정 화면에 붙여넣으면 끝 — 봇 토큰 발급, 서버 초대,
  권한 설정이 전부 불필요하고 코드도 `httpx.post(webhook_url, json=...)` 한 줄 수준 (→ D-11)
- 웹훅 URL은 사실상 자격증명이므로 **Fernet 암호화 저장**, API 응답에는 "연동됨" 여부만
- `PUT /api/me/discord` 저장 시 **즉시 테스트 메시지를 발송**해 URL 유효성을 그 자리에서 검증
- 디스코드가 켜져 있으면 웹푸시 실패 여부와 무관하게 **양쪽 모두 발송**한다.
  폴백(실패 시에만) 방식은 "웹푸시가 실패했는지"를 서버가 확실히 알 수 없어
  (iOS는 수신 실패를 서버에 알려주지 않음) 오히려 알림 구멍을 만든다
- **죽은 푸시 기기 정리 (v7 → D-20)**: iOS는 푸시 endpoint를 조용히 회전/만료시킨다.
  pywebpush가 **410/404를 반환하면 해당 push_device 행을 즉시 삭제** —
  안 하면 죽은 기기가 쌓여 매 발송이 에러를 뿜고, 진짜 실패와 구분이 안 된다
- **알림 탭 → 매트릭스 딥링크 (v7 → D-20)**: 푸시 payload에 구독 식별 정보를 담고
  service worker `notificationclick`에서 해당 매트릭스 화면으로 직행.
  "알림은 앱을 열 시점을 알리는 장치"(D-2/D-9)의 마지막 연결 고리

iOS 웹푸시는 홈화면 추가가 전제이고 배달 신뢰성이 네이티브보다 낮다.
그래서 `/api/push/test`로 상시 점검 가능하게 하고, 미덥지 않으면 디스코드를 켜서 보완한다. (→ D-9, D-11)

### 그래도 대시보드가 주인공이다
알림은 "앱을 열어야 할 때"를 알려주는 장치이지, 알림만 보고 판단하게 만들지 않는다.
판단은 매트릭스 화면에서 한다. (→ D-2, D-9)

## 9. 스케줄러

### 재시작 내구성 — next_poll_at 포인터 *(v7 → D-19)*
APScheduler는 인프로세스라 잡 상태가 메모리에 있다. 출근 시간에 컨테이너가 재시작되면
(OOM, 배포) 폴 포인트를 **중복 실행하거나 통째로 건너뛰어도 알 방법이 없다.** 따라서:
- **실행할 폴 포인트를 DB에 둔다**: `subscription.next_poll_at`
- 구독 생성/갱신 시 시각표에서 폴 포인트 목록(각 정차역 실효 도착시각 - [10, 4]분)을
  계산해 첫 포인트를 `next_poll_at`에 기록
- 30초 틱의 일은 단 하나: **`next_poll_at ≤ now`인 활성 구독을 실행하고 포인터를 다음
  포인트로 전진.** 재시작해도 DB의 포인터에서 그대로 이어진다 (멱등)
- **늦은 폴 유예(grace) 2분**: 재시작 등으로 폴 포인트가 지났을 때, 2분 이내 지각이면
  즉시 실행하고, 넘었으면 **스킵하고 다음 포인트로 전진**. 낡은 시점의 조회를 뒤늦게
  쏘면 다음 조회와 겹치기만 한다

### 폴링 사이클
- APScheduler 인터벌 잡(30초)이 **활성 구독 테이블**을 읽음.
  30초 루프는 "시계 확인"일 뿐, 코레일 조회는 `next_poll_at` 도래 시에만 발생한다
- **실효 도착시각 = 시각표 도착시각 + DelayPort 지연분(없으면 0)** (→ D-12).
  지연이 갱신되면 남은 폴 포인트도 재계산해 `next_poll_at`에 반영
- `next_poll_at` 도래 시 (정차역당 최대 2회):
  1. 매트릭스 재조회 — **60초 캐시를 우회하고 항상 실조회** (캐시는 화면 트래픽 전용 → D-17).
     조회 범위는 실효 시작~하차역 (5절, → D-18)
  2. `Verdict` 계산 — 구독의 `status`(STANDING/SEATED)를 입력으로.
     current_seg_idx는 `estimate_seg(stops, delay, now)` **시각표+지연 추정** 기준 (GPS는 화면 전용, → D-13)
  3. 변화 감지:
     - `last_verdict_hash`가 NULL이면 **베이스라인 알림 1건** (8절, → D-20)
     - 해시가 `last_verdict_hash`와 다르면 해당 종류 `Alert` 생성 (8절 해시 표 기준)
     - `last_cells_snapshot` 대비 잔여 구간 내 true→false 전이 시 `SEAT_EXTENDED` 생성
     - 복수 종류 동시 성립 시 **우선순위 합성으로 푸시 1건** (8절 합성 규칙, → D-20)
  4. `NotifierPort` 발송 — 웹푸시는 항상, 디스코드는 `discord_enabled`인 사용자만 병행.
     웹푸시 410/404 응답 시 해당 push_device 삭제 (→ D-20)
  5. `last_verdict_hash`, `last_cells_snapshot`, `last_notified_at`, `next_poll_at` 갱신
     (**스케줄러만 기록** — 사용자의 `/matrix` 화면 조회는 알림 상태를 건드리지 않는다)
- 사용자가 `PATCH /api/subscriptions`로 상태/좌석을 바꾸면 다음 폴링부터 새 기준 적용.
  전이 직후 `last_cells_snapshot`은 무효화(NULL) — 새 좌석 첫 조회에서 스냅샷만 쌓고 전이 판정은 그 다음부터
  (`last_verdict_hash`는 유지 — 상태 전이 자체로 베이스라인이 재발송되면 소음)
- DelayPort 조회는 폴링 사이클당 1회, 결과는 캐시. 실패해도 지연 0으로 계속 동작
- **조회 실패 시 같은 조회 시점 내에서 30초 간격 최대 3회 재시도**, 모두 실패하면 `FETCH_FAILED`
  발송 후 해당 시점 포기, 포인터 전진 (→ D-17. "3폴링 연속" 방식은 한 역 반을 지나서야 알림이 와 폐기)
- 하차역 실효 도착시각 경과 시 `active = false`
- **조회 빈도 원칙: 정차역당 1~2회 (+실패 재시도).** 비공식 API 자동화는 약관 회색지대다. 공격적 폴링 금지.

## 10. 프론트엔드 (PWA)

- React (Vite) + 바닐라 CSS, FastAPI `StaticFiles`로 서빙
- **프로토타입 완성본: `seat-matrix.jsx`** (레포에 포함) — 매트릭스 화면 확정
  - 상단: 열차 배지 + 노선 진행바 (현재 위치 펄스)
  - 판정 카드: 내 자리 상태 / 이동·착석 추천 / 지하철 환승 제안
  - 좌석 × 구간 매트릭스: `clear_until` 내림차순, END 태그,
    "하차역까지 빈 좌석만" 필터, 지나온 구간 흐림 처리
- 구현 시 변경점: 목업 상수(`STATIONS`, `SEATS`, `CURRENT_SEG`, `MY_DEST`)를
  `/matrix` 응답으로 대체

### 탑승 상태 전이 UI (→ D-15)
- 탑승 등록 시 **입석/착석 선택**, 착석이면 좌석 지정
- 매트릭스에서 좌석 행 선택 → **"이 자리에 앉음" 버튼 하나**로 세 전이를 커버:
  - STANDING → SEATED (첫 착석)
  - SEATED → SEATED (자리 이동)
- **"일어남" 버튼** 별도 (SEATED → STANDING, 자리 뺏김/자발적 기립)
- 내부적으로 전부 `PATCH /api/subscriptions/{id}` 한 엔드포인트
- 옮기는 행위가 이 앱의 핵심 루프다 — **전이 입력이 없으면 이후 모든 알림이 이미 떠난 자리를 기준으로 울린다.** 알림 문구에도 갱신 유도 포함 (8절)

- 추가 화면: 로그인 / 프리셋 선택 / 열차 선택 /
  설정(코레일 연동*, 알림 기기, 디스코드 웹훅 연동 + on/off 토글, 테스트 발송)
  (*Phase 0 결과 비로그인 가능이면 코레일 연동 화면 자체가 없음)

### 열차 선택 화면 — 역은 고르는 것이지 입력하는 것이 아니다 *(v9 → D-25)*
탑승 등록의 첫 화면이다. 코레일 앱과 같은 순서로 좁혀 들어간다:
1. **출발역 / 도착역을 드롭다운에서 선택** — 역 이름을 타이핑시키지 않는다.
   오타가 곧 404이고, 사용자는 정식 역명(`서울역`인지 `서울`인지)을 모른다.
   소스는 `GET /api/stations` (→ 5절 station 테이블, D-25)
2. **운행일 + 검색 기준 시각** — "오후 5시 이후 열차"처럼 **하한 시각**을 준다.
   통근은 "몇 시 차"가 아니라 "퇴근하고 탈 수 있는 차"를 고르는 일이다
3. **열차 목록에서 선택** — `GET /api/trains/search`. 열차명/번호 + 출발·도착 시각
4. 입석/착석 선택(착석이면 좌석 지정) → 구독 생성 → 매트릭스
- 프리셋이 있으면 1~2단계를 건너뛴다 (자주 쓰는 구간 = 행 추가, 원칙 1·3)
- PWA: manifest + service worker + 푸시 수신 핸들러 + `notificationclick` 매트릭스 딥링크 (→ D-20)
- **푸시 권한 요청은 사용자 제스처에서만 (iOS 제약, → D-21)**: 페이지 로드 시 자동 요청
  코드는 조용히 실패한다. 설정 화면의 "알림 켜기" 버튼 **탭 핸들러 안에서만** 권한 요청

### 현재 위치 표시 (GPS 포그라운드 보정, → D-13)
- 노선 진행바의 현재 위치(`current_seg_idx`)는 기본적으로 **시각표+지연 추정**
- 앱을 열었을 때 위치 권한이 있으면 폰 GPS 좌표를 `/matrix`에 첨부 →
  서버가 station 좌표와 대조해 **실측 구간으로 덮어씀**
- **구간 판정 방식: 인접역 선분 투영** — 역 '점'과의 최근접 비교가 아니라,
  `stops` 목록 내 인접 두 역을 잇는 선분에 GPS 좌표를 투영해 진행률로 구간을 확정한다.
  후보를 `stops` 내 역으로만 한정하므로 타 노선 역 오매칭이 원천 차단된다 (→ D-17)
- **위치 권한 거부 시에도 전 기능 정상 동작** (선택 기능)
- 안전장치: GPS가 노선(선분)에서 일정 거리 이상 벗어나면(탑승 전/하차 후 등) 무시하고 추정값 사용
- **신선도 안전장치 (v7 → D-21)**: Geolocation 좌표의 timestamp/accuracy를 함께 전송 —
  **30초 이상 낡았거나 정확도 반경이 과대하면 무시**하고 추정값 사용 (임계값은 설정으로 격리)

### 열차 안 네트워크 대응 (실사용 필수)
열차 내부는 회선이 자주 끊긴다.
- **마지막 매트릭스를 로컬 캐시**하고 조회 실패 시 빈 화면 대신 캐시본 표시
- `fetched_at`을 **항상 화면에 노출** ("3분 전 데이터")
- 이게 있고 없고의 체감 차이가 크다.

## 11. 구현 단계

### Phase 0 — 실현 가능성 검증 ★ 신설 (→ 0절, D-14)
- korail2로 반나절짜리 검증 스크립트 작성 (본 프로젝트 코드와 무관한 일회성)
- 0절의 6개 항목을 우선순위(3→1→2→5→6→4) 순으로 확인, 결과를 이 문서 0절에 기록
- ✅ 완료 기준: go/no-go 판정 + 자격증명 처리 방식(비로그인/부계정/본계정) 확정
- **여기서 no-go면 이후 Phase는 착수하지 않는다**

### Phase 1 — 뼈대 + 계정 + 목업으로 전체 관통
- FastAPI 프로젝트 (`api` / `auth` / `domain` / `adapters` / `scheduler` / `storage`)
- **User + 세션 로그인 먼저** (스키마에 `user_id` FK를 처음부터 심는다 → D-10)
- subscription에 `status` / `last_cells_snapshot` 포함해 스키마 확정 (→ D-15, D-16)
- `KorailPort` Protocol + **`MockKorailAdapter`** (프로토타입 목업 데이터 재현)
- `domain/matrix.py`, `domain/verdict.py`, `domain/alerts.py`, `domain/timeline.py`(estimate_seg + 폴 포인트 계산) + **pytest 단위 테스트** (여기 집중. clock은 전부 `now` 인자 주입 → 공통 구현 규칙)
- `/matrix` 엔드포인트 + 구독 CRUD/PATCH + 프론트를 API 연동으로 전환, 로그인 화면, 상태 전이 UI
- **열차 선택 화면 골격** (역 드롭다운 + 시각 하한 검색 + 열차 목록) — 데이터는 Mock,
  Phase 2에서 소스만 실연동으로 교체한다 (→ D-25). Mock 어댑터는 시각대가 다른 열차 여러 편을 준다
- ✅ 완료 기준: 로그인 후 목업 데이터로 프로토타입과 동일한 화면이 렌더링되고,
  좌석 행 선택 → "이 자리에 앉음"으로 구독 상태가 바뀐다

### Phase 2 — 코레일 실연동
- `Korail2Adapter` 구현 (Phase 0에서 확정된 인증 방식 적용: 비로그인 / 부계정 세션 관리)
- 환경변수 `ADAPTER=mock|korail2`로 전환
- 동시성 제한(3) + 지터 + 60초 캐시(화면 전용) + 재시도(30초×3)
- 좌석맵 응답을 도메인 모델로 정규화 (열차종별 차이 흡수)
- 조회 범위 현재 구간~하차역 한정 적용
- **지연 정보 소스 확정** (→ D-12): Phase 0-4에서 korail2 내 지연 정보를 확인했으므로,
  ① 있으면 DelayPort 실구현 ② 없으면 공공데이터 실시간 API 검증
  (ITX 커버 여부 / 갱신 주기 / 지연'분' 직접 제공 여부) ③ 미채택 시 ZeroDelay 유지 (2회 조회가 보완)
- 역 정적 데이터 적재 (station 테이블) — **용도 2개**: GPS 보정 좌표 + 역 선택 드롭다운 소스.
  Phase 1이 만든 열차 선택 화면의 데이터 소스를 여기로 갈아끼운다 (→ D-25).
  **출처 검증이 선행 과제**: korail2 공개 API에 역 목록이 없다(Phase 0 감사) → 공공데이터포털 등 외부 소스
- 선분 투영 구간 판정 (GPS 보정)
- ✅ 완료 기준: 실제 열차번호로 매트릭스 조회 성공

### Phase 3 — 알림 + 자동화
- `NotifierPort` + WebPush 어댑터(기본) + Discord 웹훅 어댑터(opt-in), `/api/push/test`
- APScheduler 폴링 — `next_poll_at` 포인터 + grace 2분 (재시작 내구성 → D-19)
- 해시 + 셀 스냅샷 이중 변화 감지, 우선순위 합성(폴링당 푸시 1건), 첫 폴링 베이스라인 (8절)
- 8절 5종 알림 구현 (상태별 분기 포함), 410/404 죽은 기기 정리
- PWA manifest/service worker/푸시 핸들러(딥링크 포함) + 오프라인 캐시
  (푸시 권한 요청은 설정 화면 버튼 탭에서만 — iOS 제약)
- ✅ 완료 기준: 탑승 등록 → 역 접근 시 자동 갱신 → [입석] 착석 가능 다이제스트 수신 /
  [착석] 내 자리 판매 시 폰에 알림 수신 → 앱에서 "이 자리에 앉음" → 이후 알림이 새 자리 기준으로 발송

### Phase 4 — 배포 + 개선
- EC2 t4g.nano 프로비저닝, Docker, Tailscale serve
- 2회 이동 조합 추천
- 좌석 점유 이력 저장 → "이 시간대 이 열차는 어느 호차가 잘 빈다" 통계
- **실사용 몇 주 후 조정 예정 항목** (설정값으로 격리해둔 손잡이들, → D-17):
  추천 랭킹 가중치 / `min_extension_segments` / `SEATS_AVAILABLE` 다이제스트 상세도
- **관리자 복구 수단** (→ D-24 후속). 가입이 잠긴 채 관리자 계정을 잃거나 첫 계정이
  엉뚱하게 점유되면 **앱에서 풀 방법이 없다** — 로그인도 가입(403)도 막히고 DB 직접 수정만 남는다.
  Phase 1 개발 중 실제로 겪었다(브라우저 검증용 계정이 첫 계정=관리자 자리를 차지).
  후보 2개:
  - **CLI 한 줄** (예: `uv run python -m app.storage.admin_reset <email>`) — **권장**.
    Tailscale 격리 + 서버 접근 자체가 이미 권한이라 별도 시크릿이 필요 없고, 상시 열린 구멍이 안 남는다
  - env `ADMIN_BOOTSTRAP_EMAIL` — 부팅 시 해당 계정을 관리자로 승격(없으면 무동작).
    간단하지만 재배포가 필요하고, 켜둔 채 잊으면 그 자체가 백도어다
  Phase 1~3에서는 **DB 파일 삭제/수정으로 대응한다** (1인용이고 데이터가 하루치라 비용이 낮다)

## 12. 배포 상세 (AWS EC2)

### 인스턴스
- **t4g.nano (ARM/Graviton), ap-northeast-2(서울)**, EBS gp3 10GB
- 온디맨드 월 5,500원 안팎, 1년 Savings Plan 시 3~4천원대
- ※ 2026년 5월 기준 개략치. 요금·환율은 콘솔에서 재확인할 것

### 서울 리전을 고른 이유
백엔드가 코레일 서버를 **구간 수만큼 병렬 호출**한다.
해외 리전이면 호출마다 왕복 지연이 붙어 조회 한 번이 눈에 띄게 느려진다. (→ D-6)

### 체크리스트
- [ ] **ARM64 이미지로 빌드** (`python:3.12-slim` arm64). x86 이미지는 아예 안 뜬다
- [ ] **스왑 2GB 설정** — nano는 0.5GB. 스왑 없으면 새벽에 OOM Killer가 컨테이너를 잡아먹음
- [ ] **uvicorn `--workers 1` 고정** — APScheduler 인프로세스. 2개면 폴링·알림 중복 발사 (→ D-17)
- [ ] 보안그룹 인바운드 **전부 차단** (22번 포함, Tailscale SSH 사용)
- [ ] **탄력적 IP 붙이지 말 것** — Tailscale 주소로 접근하므로 불필요하고 미사용 시 과금
- [ ] `restart: unless-stopped`로 재부팅 자동 복구
- [ ] SQLite 파일 볼륨 마운트. **계정·자격증명이 들어가므로 백업 파일 취급 주의**
- [ ] `.env`: `SECRET_KEY`(Fernet), 세션 시크릿, VAPID 키쌍
      (가입 허용은 env가 아니라 DB — 관리자가 앱에서 토글한다 → D-24)
      (디스코드 웹훅은 env가 아니라 **DB의 user 행**에 저장됨 — 사용자별 설정이므로)
- [ ] `.gitignore`에 `.env`, `*.db` 확인

## 13. 테스트 전략

**전부 테스트하려 하지 말고, 조용히 틀리는 곳만 확실히 잠근다.**

| 영역 | 테스트 | 이유 |
|---|---|---|
| `domain/verdict.py` | **필수, 촘촘히** (STANDING/SEATED 양쪽 + **내 좌석 부재 규칙** + 실효 시작 `max(cur, board)`) | 순수 함수. 틀리면 조용히 틀린 답 → 자리 뺏김 |
| `domain/matrix.py` | 필수 (병합/조인, 부분 구간 조회, **부재 추론 유니버스 합집합**) | 좌석 키 조인·부재 추론 실수는 눈에 안 띔 |
| `domain/alerts.py` 변화 감지 | **필수** — ① 구간만 진행 시(SEATED) 침묵 ② 하위 추천 순서 변동 시 침묵 ③ 열차 진행만으로 `SEAT_EXTENDED` 미발화 ④ 셀 true→false 전이 시 발화 ⑤ 상태 전이 직후 스냅샷 무효화 ⑥ **복수 종류 동시 성립 시 우선순위 합성 1건** ⑦ **해시 NULL 첫 조회 베이스라인 발송** | 중복 발송/미발송 둘 다 조용히 틀린다. **케이스가 가장 많은 영역** |
| `estimate_seg` (구간 추정) | 필수 (역 정차 중 / 지연 반영 / 운행 전·후 경계, `now` 주입) | 시각 규칙이 틀리면 판정·알림 전부 한 구간씩 밀린다 |
| 스케줄러 포인터 | 필수 (재시작 후 포인터 이어받기, grace 2분 내 실행 / 초과 스킵) | 재시작 내구성은 눈으로 확인 불가 (→ D-19) |
| `auth/` | 최소 (로그인·세션 만료·401) | 틀리면 즉시 드러나지만 보안 영역이라 기본은 확인 |
| `adapters/` | 스모크 수준 | 외부가 바뀌면 어차피 깨짐. 깨지면 에러로 즉시 드러남 |
| `api/`, 프론트 | 생략 가능 (단, PATCH 상태 전이 검증 422는 확인) | 눈으로 확인됨 |

바이브코딩으로 진행하더라도 위 표의 "필수" 세 줄만은 테스트를 붙인다. (→ D-5)

## 14. 리스크 및 대응

| 리스크 | 내용 | 대응 |
|---|---|---|
| **조회가 순수 조회가 아닐 가능성** | 좌석맵 조회가 예약 프로세스 개시(임시 홀드)를 수반하면 부하·흔적 문제가 전혀 다른 차원 | **Phase 0 go/no-go 최우선 검증** (→ 0절, D-14) |
| **코레일 세션 충돌** | 서버 로그인이 폰의 코레일 앱 세션을 무효화 → 검표 순간 정기권 제시 불가 | Phase 0에서 동시 세션 정책 확인, 조회 전용 부계정 분리 (→ D-14) |
| **비공식 API 변경** | 코레일이 로그인/엔드포인트를 바꾸면 파손. 언젠가 반드시 일어난다 | `KorailPort` 격리로 어댑터만 수정. korail2 업스트림 추적. Mock 폴백 |
| 계정 제재 | 자동화 조회는 약관 회색지대 | 정차역당 1~2회 + 조회 범위 축소(현재~하차역)로 호출량 최소화, 지터, 60초 캐시 |
| **판정 로직 오류** | 조용히 틀린 답 → 빈 줄 알고 앉았다 쫓겨남 | 순수 함수 + 단위 테스트로 잠금 (13절) |
| **스퍼리어스 알림** | 구간 진행·정렬 변동만으로 알림 발송 → 신뢰 붕괴 | 해시 대상 명시(8절 표) + 셀 전이 감지 + 테스트 케이스로 잠금 (→ D-16) |
| **내 자리 정보 부패** | 자리를 옮겼는데 시스템은 옛 자리 기준으로 알림 | PATCH 상태 전이 + 알림 문구에 갱신 유도 (→ D-15) |
| 열차 지연 | 시각표 기준 조회가 실제보다 일찍 나가 막판 발권을 놓침 | DelayPort 보정 + 정차역당 2회 조회(-10/-4분) + 앱 열람 시 수동 갱신 (→ D-12) |
| **알림 미수신** | iOS 웹푸시가 조용히 실패 | `/api/push/test` 버튼 + 디스코드 opt-in 병행 발송 + **첫 폴링 베이스라인 = 매일 생존 확인** + 410/404 기기 정리 (8절, → D-20) |
| 알림 피로 | 과다 발송 → 무시하게 됨 | 동일 상태 중복 발송 금지, 종류 5개로 고정, 폴링당 푸시 1건 합성 (원칙 6, → D-20) |
| **재시작 중 폴 유실/중복** | 출근 시간 컨테이너 재시작 시 조회를 건너뛰거나 중복 실행 | `next_poll_at` DB 포인터 + grace 2분 (→ D-19) |
| **이벤트 루프 블로킹** | 동기 korail2를 async에서 직접 호출 → 병렬 조회 무력화 + 앱 전체 멈춤 | 어댑터에서 `asyncio.to_thread` 필수 (→ D-21) |
| **내 좌석의 매트릭스 부재** | 부재 추론 유니버스에서 전 구간 판매 좌석이 사라짐 → KeyError/UNKNOWN | 부재 = 잔여 전 구간 판매 규칙 + 테스트 (→ D-18) |
| **추천 좌석 점유** | 판매 데이터상 빈 좌석에 입석 승객이 이미 착석 | 시스템 한계로 명시. 추천을 복수 리스트로 유지 (5·8절, → D-17) |
| **자격증명 유출** | 코레일 비밀번호를 DB에 저장하는 경우 | Fernet 암호화 + API 미노출 + Tailscale 격리 + DB 파일 백업 주의 (Phase 0 결과 비로그인이면 리스크 자체 소멸) |
| 열차 내 회선 불안정 | 조회 실패로 빈 화면 | 로컬 캐시 + `fetched_at` 표시 (10절) + 30초×3 재시도 (9절) |
| 인스턴스 메모리 | nano 0.5GB | 스왑 2GB. 초과하면 micro(2GB)로 승급 |

## 15. 폴더 구조 (제안)

```
itx-seat-matrix/
├── PLAN.md
├── pyproject.toml            # uv
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── scripts/
│   └── phase0_feasibility.py # Phase 0 일회성 검증 스크립트
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── auth.py
│   │   ├── me.py
│   │   ├── trains.py
│   │   ├── presets.py
│   │   ├── subscriptions.py  # CRUD + PATCH 상태 전이
│   │   └── push.py
│   ├── auth/
│   │   ├── session.py        # 쿠키 세션, current_user 의존성
│   │   └── crypto.py         # argon2 해시, Fernet 암복호화
│   ├── domain/
│   │   ├── models.py         # Pydantic
│   │   ├── matrix.py         # 병합 (부분 구간)
│   │   ├── verdict.py        # 판정 (순수 함수, status 입력, 내 좌석 부재 규칙)
│   │   ├── timeline.py       # estimate_seg + 폴 포인트 계산 (순수 함수, now 주입)
│   │   ├── alerts.py         # 해시 + 셀 스냅샷 변화 감지 → Alert 생성 (순수 함수)
│   │   └── geo.py            # 선분 투영 구간 판정 (순수 함수)
│   ├── adapters/
│   │   ├── korail_port.py
│   │   ├── korail_mock.py
│   │   ├── korail2_adapter.py
│   │   ├── delay_port.py
│   │   ├── delay_zero.py         # 기본: 항상 None (지연 0 간주)
│   │   ├── notifier_port.py
│   │   ├── webpush_notifier.py
│   │   └── discord_notifier.py
│   ├── scheduler/
│   │   └── poller.py
│   └── storage/
│       ├── db.py
│       └── migrations/
├── tests/
│   ├── test_verdict.py       # ★ 핵심
│   ├── test_matrix.py
│   ├── test_alerts.py        # ★ 핵심 — 13절 케이스 5종 필수
│   ├── test_geo.py
│   └── test_timeline.py      # 구간 추정 + 폴 포인터/grace
└── web/                      # Vite + React
    └── src/
        ├── SeatMatrix.jsx
        ├── Login.jsx
        └── Settings.jsx
```

## 16. Claude Code 시작 프롬프트

### Phase 1 (완료)

```
PLAN.md를 읽고 Phase 1을 구현해줘. (Phase 0 검증은 이미 완료됐다고 가정 — 결과는 0절 참고)
- Python 3.12, FastAPI, Pydantic v2, uv
- 폴더 구조는 PLAN.md 15절 준수
- User 모델 + 세션 쿠키 로그인부터 (argon2, 로그인 유지 D-23, 가입 잠금은 관리자 토글 D-24)
  모든 도메인 테이블에 user_id FK를 처음부터 포함
- subscription은 status(STANDING/SEATED) + last_cells_snapshot 포함,
  PATCH /api/subscriptions/{id}로 상태 전이 (SEATED인데 좌석 없으면 422)
- KorailPort Protocol + MockKorailAdapter (프로토타입 목업 데이터 재현)
- domain/verdict.py, domain/matrix.py, domain/alerts.py, domain/timeline.py는
  순수 함수 + pytest 테스트 필수. 시간 의존 함수는 전부 now를 인자로 받는다
  특히 test_alerts.py는 PLAN.md 13절의 7개 케이스를 반드시 포함
- 인덱스는 전체 노선 stops 기준, 실효 시작 = max(current_seg_idx, board_idx) (5절)
- SEATED인데 내 좌석이 매트릭스에 없으면 잔여 전 구간 판매로 판정 (5절 부재 규칙)
- 모든 datetime은 KST aware, naive 금지 (3절 공통 구현 규칙)
- GET /api/trains/{train_no}/matrix 응답은 PLAN.md 7절 JSON 스키마 준수
- 모든 /api/*는 Depends(current_user) 적용, user_id는 절대 쿼리로 받지 않음
- 프론트는 seat-matrix.jsx를 web/ Vite 프로젝트로 옮기고 목업 상수를 API 호출로 대체
  + 로그인 화면 + 좌석 행 선택 → "이 자리에 앉음" / "일어남" 상태 전이 UI
- 코레일 연동과 알림 발송은 이 단계에서 하지 않는다 (Phase 2, 3)
```

### Phase 2 — 코레일 실연동 *(다음 세션에서 이 블록을 그대로 붙여넣는다)*

```
PLAN.md 11절 Phase 2(코레일 실연동)를 시작한다.
Phase 1은 완료됐다 — 이슈 #3, 브랜치 feat/phase1-skeleton, pytest 104 통과,
Mock 어댑터로 로그인→열차 선택→매트릭스→"이 자리에 앉음" 전이까지 관통 확인됨.

착수 전:
1. Phase 1 PR이 dev에 머지됐는지 확인해라. 안 됐으면 알려줘 — 머지는 내가 한다.
2. feature 템플릿으로 새 이슈를 발급하고 dev에서 feat/<이름>으로 분기해라. 커밋만 하고 push는 내가 한다.

착수 순서 (앞이 뒤의 전제다):
A. **get_stops 소스 확정이 최우선.** Phase 0 항목 5 = NO(열차번호 → 전체 정차역 파생 불가)가
   여전히 미해결이다. 원칙 1(역 하드코딩 금지)의 전제이므로 여기가 막히면 뒤가 다 막힌다.
   외부 소스(공공데이터포털 열차 정차역 API 등) 후보를 조사해 제시하고,
   **내 승인 없이 특정 소스로 구현하지 마라.** D-25의 역 마스터(목록·좌표)와 같은 뿌리 문제이니 함께 푼다.
B. Korail2Adapter (D-22). korail2 본체는 PyPI 정식 릴리스(korail2>=0.4.0)로 의존하고,
   DynaPath 우회(x-dynapath-m-token 생성 + 헤더 부착)만 adapters/에 **벤더링**한다.
   원본 = github.com/dhfhfk/korail2 브랜치 bypassDynapath,
   고정 커밋 4b134266fff097ea0fd54e9f760cb128b6c8f878 (공급망 리뷰 완료된 커밋).
   korail2는 **동기** 라이브러리다 — 어댑터 내부에서 asyncio.to_thread로 감싼다 (절대규칙 3).
   세션은 프로세스 내 캐시, **만료 감지 시에만** 재로그인.
C. 자격증명 저장: PUT /api/me/korail (Fernet, env SECRET_KEY). API 응답에 절대 노출 금지.
   GET /api/me의 korail_linked가 이미 이 컬럼을 읽는다.
D. 조회 예절: Semaphore(3)+지터는 adapters/seatmap_fetcher.py에 이미 있다.
   여기에 재시도(30초×3)와 60초 TTL 캐시를 추가한다 — matrix_cache 테이블 신설,
   키는 (train_no, date, frm, to), **화면 트래픽 전용이고 스케줄러는 우회**한다 (D-17).
E. 좌석맵 정규화(열차종별 차이 흡수). 병합은 단순 조인이 맞다 — Phase 0 항목 6 실측 확정.
   domain/matrix.py의 유니버스 합집합 규칙은 방어용으로 그대로 둔다.
F. DelayPort 실구현 (D-12). h_expct_dlay_hr는 **6자리 포맷**이다(4자리 hhmm 아님, Phase 0 실측).
   실패해도 지연 0으로 계속 동작해야 한다.
G. station 테이블 적재 → ① domain/geo.py 선분 투영 + /matrix의 lat/lng, position_source="gps"
   ② GET /api/stations의 소스를 Mock에서 station 테이블로 교체 (D-25).
   GPS 신선도 안전장치(30초 초과·정확도 과대 시 무시)도 함께 (D-21).

지킬 것:
- **실 코레일 API를 루프로 때리지 마라.** 개발·디버깅은 ADAPTER=mock으로 한다 (CLAUDE.md 10).
  실 호출은 필요한 최소 횟수만, 무엇을 왜 호출하는지 먼저 말하고 해라.
- 실 자격증명·우회 코드를 건드리는 스크립트는 **네가 실행하지 말고 명령을 알려줘라.** 내가 직접 돌린다.
- **개발 DB(data/itx.db)를 삭제·초기화하지 마라.** 내 계정이 들어 있고 가입이 잠겨 있어 복구가 번거롭다.
  브라우저 검증이 필요하면 DB_PATH를 임시 경로로 지정해 별도 인스턴스로 띄워라.
- 시크릿은 .env에만. 추적되는 파일(.env.example 포함)에 실제 값을 절대 쓰지 마라.
- Phase 3 영역(NotifierPort/웹푸시/디스코드/APScheduler 폴링/PWA service worker)은 아직 만들지 않는다.
- PLAN.md와 충돌하거나 문서가 침묵하는 지점을 만나면 멈추고 보고해라. 합의된 변경은 본문 수정 + D-항목.

열린 항목 (Phase 1에서 보고했으나 문서 미반영):
- 5절 estimate_seg 표기 `arrival(stops[i]) <= now + 지연보정`이 9절 "실효 도착 = 시각표 + 지연"과
  **부호가 반대**다. 구현은 물리적으로 맞는 9절 정의를 따랐다(app/domain/timeline.py 주석 참고).
  5절 문구 수정 + D-항목이 필요하다 — 지연 보정을 실제로 켜는 Phase 2에서 정리하자.

완료 기준: ADAPTER=korail2로 **실제 열차번호 매트릭스 조회 성공**, ADAPTER=mock 폴백 유지,
pytest 전부 통과(어댑터는 스모크 수준으로 충분).
```

---

## 17. 결정 이력 (Decision Log)

> **이 절의 목적**: 나중에 이 문서를 다시 볼 때 "왜 이렇게 했지?"를 즉시 알 수 있게.
> 뒤집힌 결정은 지우지 않고 **개정 이력으로 남긴다** (D-2 → D-9, D-8 → D-10, D-16이 D-9 일부 개정).

### D-1. 네이티브 iOS 앱 → PWA
- **처음 생각**: 스프링부트 백엔드 + iOS 앱을 앱스토어 없이 내 폰에만 설치
- **문제**: 무료 Apple ID 서명은 **7일마다 만료**되어 맥에 다시 꽂아야 함.
  피하려면 Apple Developer Program 연 $99. 매일 쓰는 통근 도구에 이 마찰은 과함
- **결정**: 프론트를 웹으로, 사파리 "홈 화면에 추가"
- **근거**: iOS 16.4부터 홈화면 웹앱에 **웹 푸시** 지원 → 알림 요구도 충족.
  맥/Xcode/인증서/만료가 전부 사라짐
- **재검토 조건**: 위젯, 백그라운드 위치 등 네이티브 전용 기능이 정말 필요해지면

### D-2. 알림 봇 → 대시보드 *(v3에서 부분 개정 → D-9)*
- **처음 생각**: UI 없이 텔레그램 봇으로 "자리 팔렸음" 알림만
- **문제**: 사용자가 원한 건 통보가 아니라 **직접 판단**.
  어느 좌석으로 옮길지, 아예 지하철로 갈아탈지를 스스로 결정하고 싶어함
- **결정**: **좌석 × 구간 매트릭스**를 핵심 화면으로. 알림은 보조
- **파급**: 프로젝트 성격이 "알림 스크립트"에서 "의사결정 대시보드"로 바뀌고 프론트엔드가 필수가 됨
- **주의**: 이 결정이 v2 문서에서 **알림을 과하게 축소**하는 부작용을 낳았다 → D-9에서 교정

### D-3. 역 정보 하드코딩 금지
- **문제**: 단일 통근 구간만 쓸 거라 역 목록을 상수로 박기 쉬운데,
  그러면 나중에 다른 구간 지원 시 로직 전반을 뜯어야 함
- **결정**: 정차역을 **열차번호에서 조회 시점에 동적 파생**
- **효과**: 확장이 사실상 공짜. 새 구간 = 프리셋 행 추가

### D-4. Spring Boot + Python 사이드카 → **Python 단일 스택** *(v2 핵심 변경)*
- **v1 구성**: 백엔드는 익숙한 Spring Boot, 코레일 연동만 파이썬 사이드카로 분리
- **분리했던 이유**: 코레일 공식 좌석조회 API가 없고 역공학 결과물이 파이썬 `korail2`뿐이라,
  Java로 직접 포팅하려면 세션 쿠키/파라미터 구조를 전부 뜯어야 했음
- **깨달은 것**: **사이드카는 언어 불일치 때문에 생긴 컴포넌트지, 설계상 필요한 게 아니었다**
- **부수 효과**:
  - 메모리 400~600MB → 150~250MB → **인스턴스를 micro에서 nano로** (D-6과 연결)
  - JVM 콜드스타트 20~30초 제거
  - 구간 병렬 조회가 `asyncio.gather` + `Semaphore` 몇 줄로 끝남
- **잃은 것과 회복**: Java 정적 타입 → **Pydantic v2**로 상당 부분 회복 (record가 거의 1:1 이식)
- **유지한 것**: **Port 추상화.** 프로세스 경계에서 `Protocol` 클래스로 형태만 바뀜
- **재검토 조건**: 성능 병목이 파이썬 때문이라고 실측되면 (1인 트래픽에선 거의 없을 일)

### D-5. 바이브코딩 채택 + 테스트 범위 한정
- **맥락**: v2를 바이브코딩으로 빠르게 만들기로 함
- **우려**: 이 프로젝트는 **언젠가 반드시 깨진다** (코레일 API 변경).
  그날 아침 열차 안에서 스택트레이스를 읽어야 하는데, 읽을 수 없는 코드를 매일 의존하는 게 실제 리스크
- **결정**: 영역을 나눈다. 어댑터·프론트는 자유롭게 생성하되,
  **판정 로직과 알림 변화 감지는 단위 테스트로 반드시 잠근다**
- **근거**: 어댑터가 깨지면 **에러가 나서 바로 안다**.
  판정·알림 로직이 틀리면 **조용히 틀린다**

### D-6. 배포처 선정: EC2 t4g.nano (서울)
- **제약 1 — 항상 켜져 있어야 함**: 스케줄러가 역 도착 전 스스로 조회해야 하므로
  **유휴 시 잠드는 무료 티어(Render 무료, Fly scale-to-zero)는 탈락**
- **제약 2 — 예산 월 5,000원 미만**
- **제약 3 — 사용자가 EC2 경험 보유** (운영 학습비용 절감)
- **검토 후보**:
  | 후보 | 판정 |
  |---|---|
  | Oracle Always Free ARM (무료, ~24GB) | 스펙은 압도적이나 **ARM 용량 확보 난항 + 유휴 계정 회수 이력** → 매일 쓰는 도구엔 부적합 |
  | Hetzner CAX11 (월 6천원, 4GB) | 한국까지 **250ms+**. 구간 다회 호출이라 지연 누적 → 탈락 |
  | Lightsail 2GB (월 9,800원) | 단순하지만 예산 초과 |
  | 라즈베리파이 5 | D-7 |
  | **EC2 t4g.nano (서울)** | **채택** |
- **micro → nano로 내린 이유**: D-4로 메모리 요구가 반토막.
  micro는 1년 SP를 걸어야 예산에 들어왔지만 **nano는 온디맨드로도 예산 내**.
  약정 없이 가는 게 개인 프로젝트엔 유리

### D-7. 라즈베리파이 검토 → 신규 구매는 보류
- **비용**: Pi 5 4GB 본체 10만원 안팎 + 어댑터/케이스/저장장치 = **13~15만원**.
  전기 상시 5W ≈ 월 1,000~1,500원
- **계산**: 2년 상각 시 월 7,500원 → **VPS보다 비쌈**. 3년차부터 전기값만 남아 유리
- **더 큰 문제**: 집 인터넷 재부팅/정전 시 **통근 당일 아침에 서비스가 죽는다**
- **결정**: 이걸 위해 새로 사지 않음. **이미 갖고 있다면 Phase 1~2 개발용으로는 최적**

### D-8. 인증 구현 대신 Tailscale 네트워크 격리 *(v3에서 개정 → D-10)*
- **맥락**: 1인용이라 로그인 체계가 과하고, 그렇다고 공개 노출은 위험
- **당시 결정**: 서버를 인터넷에 열지 않고 Tailscale로만 접근. **애플리케이션 인증은 생략**
- **중요 디테일 (v3에서도 유효)**: `tailscale serve`의 `*.ts.net` 도메인은
  **신뢰되는 HTTPS 인증서**를 제공한다. 자체서명으로는 **PWA 홈화면 추가와 웹 푸시가 동작하지 않는다**
- **확인됨**: 아이폰 Tailscale은 LTE에서도 붙으므로 열차 안에서 그대로 사용 가능
- **개정 사유**: 인증 생략 부분만 뒤집힘 → D-10. **네트워크 격리 자체는 그대로 유지**

### D-9. 알림을 정식 목표로 승격 *(v3, D-2 개정)*
- **문제**: D-2에서 "알림 봇 → 대시보드"로 방향을 틀면서, 문서상 알림이 지나치게 축소됐다.
  하지만 실사용에서는 **열차 안에서 계속 화면을 들여다볼 수 없다.**
  내 자리가 팔린 것 정도는 먼저 알려줘야 대시보드를 열 타이밍을 안다
- **결정**: 알림을 목표로 승격하되 범위를 고정 (8절. 종류 구성은 v6에서 재설계 → D-16)
- **경계선**: D-2는 여전히 유효하다. **알림은 "앱을 열 시점"을 알리는 장치이고,
  판단은 매트릭스 화면에서 한다.** 알림만 보고 결정하게 만들지 않는다
- **설계 반영**:
  - 원칙 6 신설 — **상태 변화에만 발송**. 매 폴링 발송은 알림 피로를 만들고, 무시하는 알림은 없느니만 못함
  - 알림 문구에 **항상 다음 행동**을 포함 ("7A 판매됨 → 1B로 이동")
  - `FETCH_FAILED` 추가 — 조용히 갱신이 멈추는 게 가장 위험. 낡은 데이터를 믿고 앉아있게 됨
- **채널 이중화**: iOS 웹푸시는 조용히 실패하는 일이 잦아
  `NotifierPort`로 추상화하고 보조 채널을 둔다. `/api/push/test`도 필수
  (테스트 버튼이 없으면 알림 미수신이 버그인지 iOS 문제인지 구분 불가)
  *(보조 채널로 처음엔 텔레그램을 지정했으나 v4에서 디스코드로 교체 → D-11)*
  *(종류별 리드타임은 v5에서 폐지 → D-12, 알림 종류 구성은 v6에서 재설계 → D-16)*

### D-10. 계정(회원) 계층 도입 *(v3, D-8 개정)*
- **문제**: v2는 1인용이라는 이유로 인증을 생략하고 Tailscale 격리에만 의존했다.
  그러나 **서버가 사용자를 식별하지 못하는 구조**에는 실무적 문제가 있었다:
  - 코레일 자격증명을 `.env`에 굽는 수밖에 없음 → 이미지·레포에 섞일 위험
  - 푸시 기기(폰/아이패드)를 **누구의 것**으로 저장할지 귀속 대상이 없음
  - 프리셋·구독이 전역 테이블이 되어, 나중에 지인 1명만 추가돼도 **스키마를 전부 갈아야 함**
- **결정**: 이메일+비밀번호 **세션 쿠키 인증**을 도입하고,
  모든 도메인 테이블에 `user_id` FK를 **처음부터** 심는다
- **왜 처음부터인가**: 인증을 나중에 끼우면 **모든 엔드포인트·스키마·쿼리를 고쳐야 한다.**
  지금 넣으면 컬럼 하나 값이지만, 나중에 넣으면 마이그레이션 + 전면 수정이다
- **왜 JWT가 아닌 세션 테이블인가**: 1~2인 규모에서는 세션 테이블이 더 단순하고,
  기기 분실 시 **즉시 무효화**되며, 리프레시 토큰 로직이 통째로 불필요
- **왜 소셜 로그인이 아닌가**: OAuth 콜백·리디렉트 설정이 Tailscale 내부망과 궁합이 나쁘고,
  1인용에 얻는 게 없음
- **가입은 잠근다**: `ALLOW_SIGNUP` 플래그로 부트스트랩 1회만 허용 후 `false`.
  *(v8에서 개정 — 잠금을 env가 아니라 DB의 관리자 토글로 옮김 → D-24. 기본 잠김은 유지)*
  공개 노출을 안 하더라도 **열어둘 이유가 없는 엔드포인트는 닫는다**
- **부수 효과 (의도치 않게 좋았던 점)**:
  코레일 자격증명이 `.env`에서 **DB의 user 행 + Fernet 암호화**로 이동하면서,
  비밀이 배포 아티팩트에서 완전히 분리됐다 *(v6: Phase 0 결과에 따라 저장 자체가 불필요해질 수 있음 → D-14)*
- **D-8과의 관계**: Tailscale 격리를 **대체하는 게 아니라 겹쳐 쓴다**.
  네트워크 계층(Tailscale) + 애플리케이션 계층(세션) = 이중 방어.
  Tailscale이 꺼지거나 잘못 설정된 날에도 인증이 남는다
- **확장성 측면**: 이제 "지인에게 계정 하나 열어주기"가 **행 추가**로 끝난다.
  이는 원칙 3의 연장선이며, 비목표에 있는 "공개 서비스"와는 다르다

### D-11. 보조 채널: 텔레그램 → 디스코드 웹훅, opt-in 2단계 *(v4, D-9 개정)*
- **문제**: D-9에서 웹푸시 폴백으로 텔레그램을 지정했으나, **사용자가 텔레그램을 아예 쓰지 않는다.**
  쓰지 않는 앱을 알림 때문에 설치하는 건 본말전도
- **결정**:
  1. **iOS 웹푸시를 기본이자 유일한 상시 채널**로 한다
  2. 디스코드는 사용자가 **① 웹훅을 연동하고 ② 토글을 켠 경우에만** 발송 (opt-in 2단계)
- **봇이 아니라 웹훅인 이유**: 개인용 수신 전용이라면 웹훅이 압도적으로 단순하다.
  봇은 토큰 발급·서버 초대·권한 관리가 필요하지만, 웹훅은 채널 설정에서 URL 하나 만들어
  붙여넣으면 끝이고 서버 코드도 `httpx.post(url, json=...)` 수준.
  양방향(명령어 수신)이 필요해지면 그때 봇으로 승격 — 현재 요구는 수신뿐
- **"폴백"이 아니라 "병행"인 이유**: iOS는 푸시 수신 실패를 서버에 알려주지 않는다.
  즉 서버는 "웹푸시가 실패했는지"를 확신할 수 없어, 실패 시에만 쏘는 폴백 구조는
  오히려 알림 구멍을 만든다. 켜져 있으면 그냥 양쪽에 보내는 게 안전
- **저장 위치**: 웹훅 URL은 알면 누구나 그 채널에 쓸 수 있는 사실상의 자격증명 →
  env가 아니라 **DB user 행에 Fernet 암호화** 저장 (사용자별 설정이기도 함, D-10과 일관)
- **검증 UX**: 웹훅 저장 시 즉시 테스트 메시지를 발송해 URL 오타를 그 자리에서 잡는다
- **재검토 조건**: iOS 웹푸시가 실사용에서 충분히 신뢰돼 디스코드를 켤 일이 없다면
  그대로 두면 되고(끄면 그만), 반대로 웹푸시가 계속 유실되면 디스코드를 상시 채널로 승격

### D-12. 열차 지연 대응: DelayPort + 정차역당 2회 조회 *(v5)*
- **문제**: 스케줄러의 조회 타이밍이 전부 **시각표 기준**이었다.
  열차가 10분 지연되면 "도착 5분 전" 조회가 실제로는 15분 전에 나가고,
  그 사이에 팔린 좌석을 놓친다
- **후보 검토**:
  | 방안 | 판단 |
  |---|---|
  | 공공데이터 실시간 위치/지연 API | **최선일 수 있으나 미검증.** ITX 커버 여부·갱신 주기·지연'분' 직접 제공 여부가 불확실. 위치만 주는 API라면 지연 역산이 필요해 난이도 급상승 |
  | korail2 응답 내 지연 정보 | 있다면 외부 API 자체가 불필요한 **최고 시나리오**. *(v6: Phase 0-4로 앞당김 → D-14)* |
  | 조회 횟수 보강 | 외부 의존 없이 흔한 지연(10분 내)을 커버. 즉시 적용 가능 |
- **결정 (3개 묶음)**:
  1. `DelayPort` 추상화 + `ZeroDelayAdapter` 기본 — 검증 전이라도 **설계는 지금 열어둔다**.
     지연 정보를 못 얻어도 시스템은 기존대로 동작 (우아한 성능 저하)
  2. **정차역당 2회 조회(-10분/-4분)를 기본값**으로 — 지연 API 없이도 견고해지는 보완.
     조회 빈도 원칙(1~2회)의 상한 내라 제재 리스크 무증가
  3. 지연 소스 검증을 명시 — korail2 응답 우선 확인 *(v6에서 Phase 0으로 이동)*
- **부수 정리 — 알림 리드타임 체계 폐지**: v3의 종류별 리드타임(5분/10분)은
  조회 시점과 모순이었다 (조회가 없으면 알림도 없는데, -7/-2분 조회로는 10분 전 알림이 불가능).
  **"알림 시점 = 조회 시점"**으로 정리하고, 조회를 -10/-4분에 배치해
  `ALL_SOLD`(환승 결정, 시간 필요)는 -10분 조회가, 막판 발권은 -4분 조회가 담당
- **재검토 조건**: 지연 API 채택 시 2회 조회를 1회로 줄이는 것 검토 가능

### D-13. 현재 위치: 시각표 추정 기본 + GPS 포그라운드 보정 *(v5, v6에서 판정 방식 구체화)*
- **문제**: 노선 진행바의 현재 위치(`current_seg_idx`)가 시각표 추정이라
  지연 시 실제보다 앞서간 위치를 표시
- **통찰**: **사용자가 열차 안에 있으므로 폰 GPS = 열차의 현재 위치.**
  GPS는 셀룰러와 무관해 열차 안 회선이 끊겨도 동작
- **한계 (역할 분담의 근거)**: PWA는 **백그라운드 위치를 못 쓴다** (네이티브 전용 → D-1 재검토 조건).
  따라서 GPS는 스케줄러의 기준이 될 수 없다
- **결정 — 역할 분담**:
  | 상황 | 위치 소스 | 용도 |
  |---|---|---|
  | 스케줄러 (앱 닫힘) | 시각표 + DelayPort | 알림 타이밍 |
  | 앱을 연 순간 | **GPS 실측으로 덮어씀** | 화면 정확도 — "지금 판단하려는 순간"이라 실측 가치가 가장 큼 |
- **구현**: `/matrix`에 선택 파라미터 `lat/lng`. **위치 권한 거부 시에도 전 기능 정상 동작**
- **판정 방식 (v6 구체화 → D-17)**: 역 '점' 최근접 비교는 역간 거리가 짧은 도심 구간과
  1호선 병주 구간에서 애매하다. **`stops` 내 인접 두 역을 잇는 선분에 GPS를 투영**해
  진행률로 구간을 확정하고, 후보를 `stops` 내 역으로 한정해 타 노선 오매칭을 차단
- **안전장치 2개**:
  - GPS가 노선(선분)에서 크게 벗어나면(탑승 전/하차 후) 무시하고 추정값 사용
  - `last_verdict_hash`는 **스케줄러만 기록** — GPS 보정된 화면 조회가
    알림 변화 감지 상태를 오염시키지 않도록 격리

### D-14. Phase 0 실현 가능성 검증 신설 *(v6)*
- **문제**: 실사용 관점 리뷰에서 **프로젝트 성립 자체에 걸리는 미검증 가정 2개**가 드러났다:
  1. **코레일 세션 충돌** — 서버가 사용자 계정으로 korail2 로그인 시, 코레일이 동시 세션을
     허용하지 않으면 **검표 순간 폰의 코레일 앱이 로그아웃**될 수 있다.
     통근 도구가 통근(정기권 제시)을 방해하는 최악의 역설
  2. **좌석맵 조회의 순수성** — korail2의 좌석 선택이 예매 흐름 안에 있다면,
     조회가 예약 프로세스 개시(임시 홀드)를 수반할 수 있다. 그러면 정차역당 2회 ×
     구간 다회 호출의 부하·흔적이 완전히 다른 차원의 문제가 됨
- **결정**: 이 둘 + 부수 검증 3개(비로그인 가능 여부 / korail2 지연 정보 / 정차역 파생)를
  **Phase 2에 묻어두지 않고 Phase 0으로 분리**. 반나절짜리 일회성 스크립트로 go/no-go 판정
- **분기 설계**:
  - 비로그인 조회 가능 → 자격증명 저장 설계 통째로 삭제 (최선. 시스템이 오히려 단순해짐)
  - 로그인 필수 → **조회 전용 부계정** 사용 (정기권 본계정과 분리, 세션 충돌 원천 차단)
  - 순수 조회가 아님 → **프로젝트 재검토**
- **근거**: 나머지 설계 개선은 "다듬기"지만 이 둘은 **검증 결과에 따라 프로젝트 형태가 바뀐다.**
  검증 없이 Phase 1~2를 진행하면 매몰 비용만 쌓인다

### D-15. 구독 상태 기계: 입석/착석 구분 + 상태 전이 입력 *(v6)*
- **문제 2개**:
  1. v5까지 구독은 `my_car/my_seat_no`가 항상 있다고 가정 — **입석으로 자리를 찾는 중**인
     상태를 표현할 수 없었다. 실제 통근의 시작 상태가 입석인데
  2. **자리를 옮긴 후 갱신 경로가 없었다** — 알림 받고 3-7A→4-1B로 옮기면, 이후
     `MY_SEAT_SOLD`는 **이미 떠난 자리** 기준으로 울리고 지금 앉은 자리가 팔리는 건 놓친다.
     옮기는 행위가 이 앱의 핵심 루프인데 그 행위가 시스템에 반영되지 않는 구멍
- **결정**:
  - `subscription.status = STANDING | SEATED`. SEATED일 때만 좌석 정보 보유
  - 전이는 `PATCH /api/subscriptions/{id}` 단일 엔드포인트:
    앉음(STANDING→SEATED) / 이동(SEATED 좌석 변경) / 일어남(SEATED→STANDING)
  - UI는 매트릭스 좌석 행 선택 → **"이 자리에 앉음" 버튼 하나**로 앉음·이동을 모두 커버
  - 알림 문구에 "이동했으면 앱에서 내 자리 갱신" 유도 포함
- **파급**: `Verdict`의 my_seat 필드가 옵셔널이 되고, 판정 함수가 status를 명시적 입력으로
  받는다 (순수 함수 유지). 상태 전이 직후 `last_cells_snapshot` 무효화 필요 (→ D-16)

### D-16. 알림 체계 재설계: 상태 기반 5종 + 셀 전이 감지 *(v6, D-9 일부 개정)*
- **배경**: D-15의 상태 기계 도입으로 알림도 상태별로 재정의 필요.
  동시에 v5까지의 해시 기반 변화 감지에 **스퍼리어스 발송** 함정이 발견됨
- **재설계 내용**:
  1. **`SEATS_AVAILABLE` 신설 (입석)** — "다음 역부터 어디 앉을 수 있나"가 입석 사용자의
     핵심 질문. 원칙 6과의 충돌은 **"입석의 상태에 현재 구간을 포함"**시켜 해소:
     구간 진행 = 상태 변화이므로 정차역당 최대 1회 다이제스트가 원칙 위반이 아니게 됨.
     원칙 6 문구도 "동일 상태 중복 발송 금지"로 정밀화
  2. **`RECOMMEND_CHANGED` 폐지·흡수** — "SEATED인데 SOLD_FROM인 상태"를 준-입석으로 보고,
     그동안만 최상위 추천 변경 시 `MY_SEAT_SOLD` 재발송으로 커버.
     종류 수가 늘지 않고 "팔린 자리에 앉아 대기 중"이라는 실제 상황과 일치
  3. **`SEAT_EXTENDED` 신설 (착석)** — 취소/환불로 내 자리가 연장되면 이동 불필요를 알림
- **`SEAT_EXTENDED` 감지 방식 — 셀 전이 기반 (핵심 함정 회피)**:
  - `clear_until` 증가를 트리거로 쓰면 **열차가 판매 구간을 지나치기만 해도 값이 점프**해
    취소 없이 "연장" 알림이 나간다. 사용자 경험상 취소가 희귀해도 이 정의로는 알림이 흔해짐
  - 따라서 트리거 = **직전 조회 셀 스냅샷 대비 잔여 구간 내 true→false 전이**.
    실제 취소라는 물리적 사건과 1:1 대응, 열차 진행으로는 절대 발화하지 않음
  - 파급: 해시는 "달라졌나"만 답하고 방향을 모르므로 `last_cells_snapshot` 저장 추가
- **발송 하한 — 사용자 결정으로 "모든 확장 발송"**:
  - 처음엔 CLEAR_ALL 도달 시에만 발송(좁게)을 제안했으나, **사용자 실경험상 출발 후
    좌석 취소는 거의 발생하지 않는 희귀 이벤트** → 피로 논리가 성립하지 않음.
    게다가 부분 연장도 "아직 이동하지 마도 됨"이라는 행동 가치가 있음
  - 기본값 `min_extension_segments=1`(전부 발송), 설정값으로 격리해 실사용 후 조정 가능
- **해시 대상 명시 (스퍼리어스 방지)**: Verdict 전체를 해시하면 구간 진행·`move_to`
  정렬 변동만으로 알림이 나간다. 8절 표대로 **상태별 최소 튜플**만 해시하고,
  `move_to` 전체 리스트·정렬은 제외. test_alerts.py 케이스로 잠금

### D-17. 실사용 관점 운영 디테일 확정 *(v6)*
실사용 시뮬레이션 리뷰에서 나온 세부 결정 묶음. 개별 D 항목으로 분리할 규모는 아니라 일괄 기록:
- **스케줄러는 60초 캐시 우회** — 캐시의 존재 이유는 사용자 화면 연타 흡수.
  스케줄러가 캐시를 맞으면 -4분 조회가 낡은 데이터를 볼 수 있음. 항상 실조회
- **uvicorn worker=1 고정** — APScheduler 인프로세스. 2개면 폴링·알림 중복 발사.
  배포 체크리스트에 명시 (12절)
- **FETCH_FAILED 재정의: "3폴링 연속" → "한 조회 시점 내 30초×3 재시도"** —
  조회가 정차역당 2회뿐이라 3폴링 연속 실패는 한 역 반을 지나서야 알림이 옴.
  한 시점 내 즉시 재시도로 바꿔 몇 분 안에 실패를 인지
- **조회 범위를 현재 구간~하차역으로 한정** — 지나온 구간은 판정·표시에 불필요.
  호출량 절반 이하 + 제재 리스크 감소
- **GPS 구간 판정 = 인접역 선분 투영** — 역 점 최근접은 도심 짧은 역간·1호선 병주
  구간에서 애매. `stops` 내 인접역 선분에 투영해 진행률로 확정, 후보를 `stops`로 한정
- **"빈 좌석 ≠ 착석 가능" 한계 명시** — 판매 데이터상 빈 좌석에 입석 승객이 이미
  앉아 있을 수 있음. 시스템이 해결 불가한 한계이며, **추천을 복수 리스트로 유지하는 근거**
- **조정 예정 값은 설정값 가진 순수 함수로 격리** — 추천 랭킹 가중치,
  `min_extension_segments`, 다이제스트 상세도 등은 실사용 몇 주 후 조정이 예정된 값.
  한 줄 수정으로 패치 가능하게 상수/설정으로 분리 (원칙 5 보강)

### D-18. 데이터 정합성 규칙: 좌석 유니버스·인덱스·시각 *(v7)*
- **배경**: 구현자가 임의로 정하게 되는 미정의 구역 3곳. 전부 "조용히 틀리는" 급
- **좌석 유니버스 문제**: 좌석맵 응답이 전체 좌석+상태인지, 구매 가능 좌석만인지에 따라
  병합 방식이 갈린다 → **Phase 0 검증 항목 6번으로 추가**
  - 구매 가능만 주는 경우: 유니버스 = 전 구간 응답의 **합집합**, 특정 구간 부재 = 그 구간 판매
  - **알려진 구멍과 판정 규칙**: 잔여 전 구간에서 팔린 좌석은 유니버스에서 사라진다.
    추천 대상으론 무해하지만 **내 좌석이 사라질 수 있음** →
    "SEATED인데 내 좌석 부재 = 잔여 전 구간 판매, `SOLD_FROM = 다음 역`"으로 고정.
    이 규칙이 없으면 KeyError 아니면 UNKNOWN으로 조용히 빠진다
- **인덱스 규칙**: `get_stops()`는 전체 노선을 준다 (사용자 구간 ≠ 열차 노선).
  모든 인덱스는 전체 노선 기준, **실효 시작 = `max(current_seg_idx, board_idx)`**로 통일.
  부수 효과: 탑승 전 첫 조회가 자연히 "탑승 전 착석 가능 다이제스트"가 됨 —
  "4호차가 비니 승강장 뒤쪽에 서라"는 실사용 가치가 커 **기능으로 명문화**
- **시각 규칙**: 역 정차 중의 현재 구간 = 도착시각만 기준
  (`max i s.t. arrival(stops[i]) ≤ now+지연`). "이번 역에서 탈 사람이 산 자리"를
  판정해야 하므로 정차 중엔 그 역부터의 구간. `estimate_seg` 순수 함수로 분리, `now` 주입
- **부수 수정**: matrix_cache 키에 조회 범위(frm, to) 포함 — 범위 다른 요청 간 오염 방지

### D-19. 스케줄러 재시작 내구성: next_poll_at 포인터 + grace *(v7)*
- **문제**: APScheduler는 인프로세스라 잡 상태가 메모리에만 있다.
  출근 시간에 컨테이너가 재시작(OOM, 배포)되면 폴 포인트를 **중복 실행하거나
  통째로 건너뛰어도 알 방법이 없다.** 매일 아침에 의존하는 도구로서 치명적
- **결정**: 실행할 폴 포인트를 DB에 둔다 — `subscription.next_poll_at`.
  30초 틱은 "`next_poll_at ≤ now`인 구독 실행 후 포인터 전진"만 수행 → **멱등**,
  재시작 시 DB 포인터에서 그대로 이어짐
- **늦은 폴 유예(grace) 2분**: 포인트가 지난 채 살아났을 때 2분 이내면 즉시 실행,
  초과면 스킵하고 다음 포인트로. 낡은 시점의 조회를 뒤늦게 쏘면 다음 조회와 겹칠 뿐
- **지연 갱신 연동**: DelayPort 지연이 바뀌면 남은 폴 포인트 재계산 → `next_poll_at` 반영

### D-20. 알림 발송의 마지막 1미터: 합성·베이스라인·기기 정리·딥링크 *(v7)*
- **합성 규칙 — 폴링 시점당 푸시 최대 1건**: `MY_SEAT_SOLD`와 `ALL_SOLD`가 동시 성립하면
  "이동하라"와 "이동할 곳 없다"는 모순 푸시 2건이 연달아 온다.
  우선순위 `ALL_SOLD > MY_SEAT_SOLD > SEATS_AVAILABLE > SEAT_EXTENDED`로 상위가
  하위를 본문에 흡수해 1건으로 합성
- **첫 폴링 베이스라인 발송**: `last_verdict_hash` NULL인 첫 조회는 항상 1건 발송.
  ① 유용한 초기 상태 확인 ② **알림 파이프라인의 그날 생존 확인** —
  iOS 웹푸시 불신(D-9)의 실전 완화책. 매일 타는 열차에서 첫 알림이 안 오면 그날 푸시가 죽은 것.
  단, 상태 전이(PATCH) 시에는 해시를 유지해 베이스라인 재발송 소음을 방지
- **죽은 기기 정리**: iOS는 푸시 endpoint를 조용히 회전/만료시킨다.
  pywebpush 410/404 응답 시 push_device 행 즉시 삭제 — 안 하면 죽은 기기가 쌓여
  매 발송이 에러를 뿜고 진짜 실패와 구분 불가
- **알림 탭 딥링크**: payload에 구독 식별 정보, `notificationclick`에서 매트릭스 직행.
  "알림은 앱을 열 시점을 알리는 장치"(D-2/D-9)의 마지막 연결 고리
- **다이제스트 상한**: `SEATS_AVAILABLE`은 상위 3석(clear_all 우선) + "외 N석".
  상한은 설정값 격리 (D-17 원칙)

### D-21. 공통 구현 규칙: KST·clock 주입·동기 격리·iOS 제약 *(v7)*
구현자가 임의로 정하면 조용히 틀리는 전역 규칙 묶음 (3절 '공통 구현 규칙'에 본문):
- **KST aware datetime 강제, naive 금지** — `date`는 운행일 기준
- **clock 주입** — 시간 의존 함수는 `now`를 인자로. 없으면 Phase 1 목업으로
  시간 진행 시나리오 테스트가 불가능
- **korail2는 동기 라이브러리** — async에서 직접 호출 시 이벤트 루프가 통째로 멈춰
  병렬 조회 설계가 무력화. 어댑터에서 `asyncio.to_thread` 필수 (가장 확실한 구현 함정)
- **코레일 세션 재사용** — 폴링마다 로그인 = 공격적 트래픽. 만료 시에만 1회 재로그인
- **GPS 신선도** — 좌표의 timestamp/accuracy 동봉, 30초 초과·정확도 과대 시 무시 (D-13 보강)
- **푸시 권한 요청은 사용자 제스처에서만 (iOS)** — 자동 요청 코드는 조용히 실패.
  설정 화면 버튼 탭 핸들러 안에서만

### D-22. Phase 0 최종 판정: GO + 안티봇 우회(PR #54) 의존 확정 *(2026-08-05)*
- **경위**: 0절 검증 중 korail2·letskorail 모두 `MACRO ERROR`(코레일 서버의 안티봇 차단)로
  로그인·조회 자체가 막혀 최초 판정은 NO-GO였다. 이후 korail2 오픈 PR
  [#54 "Implement anti-bot bypass"](https://github.com/carpedm20/korail2/pull/54)
  (`dhfhfk:bypassDynapath`)가 이 차단(앱이 붙이는 `x-dynapath-m-token` 헤더 검증)을
  우회함을 실측으로 확인. 공급망 안전성은 237줄 diff 전체 리뷰로 사전 확인
  (외부 호스트 전송·자격증명 유출 없음, 순수 토큰 생성 알고리즘 재구현).
- **실측 결과**: 항목 3(순수 조회) = YES, 항목 4(지연 정보) = YES(6자리 포맷),
  항목 5(정차역 파생) = NO(외부 소스 필요, 변경 없음), 항목 6(전체 좌석+상태) = YES.
  항목 3은 서로 다른 구간 분할로 2회 재현 — 예약/장바구니/발권대기 어떤 자동·수동 신호도 없음.
- **결정**:
  1. **Phase 0 = GO.** Phase 1 착수 가능.
  2. **6절 자격증명은 "로그인 필수 + 본계정" 갈래로 확정.** 부계정을 끝내 보유하지 못해
     항목 2가 미검증으로 남았지만, 개인용·저빈도·조회 전용 프로젝트 성격상 본계정 사용의
     세션 충돌 리스크(D-14 문제 1)를 **미해소 상태로 인수**하기로 함. 실사용 중 검표 시점
     로그아웃이 관측되면 그때 재검토 — 사전에 부계정을 만들어 막을 만큼의 확실성이 없었다.
  3. **`KorailPort`의 korail2 어댑터는 PR #54 기반으로 구현한다.** 코레일이 명시적으로
     자동화 차단 코드를 배포했다는 사실 자체(우회의 정당성 문제)는 남지만, 본 프로젝트가
     개인 1인·정차역당 1~2회·재시도 상한(10절)의 저빈도 조회 전용이라는 점이 무게추.
     "공식 앱을 흉내 내 통과시키는 방향은 채택하지 않는다"던 최초 NO-GO 시점의 원칙(0절)은
     이 결정으로 **개정**한다 — 다만 호출 예절(Semaphore(3)+지터, 세션 재사용, 실패 시
     재시도 30초×3 상한)은 그대로 유지해 부하 측면의 자제는 지킨다.
  4. **의존성 고정 방식 확정 (2026-08-05 개정): 벤더링.** `git+https://...@bypassDynapath`
     형태의 살아있는 브랜치 의존은 채택하지 않는다 — 원작자의 개인 포크 브랜치라 언제든
     force-push/삭제될 수 있고, 커밋 해시로 고정해도 그 브랜치가 사라지면 GitHub가
     unreachable commit을 가비지 컬렉션할 위험이 남는다. 대신 korail2 본체는 PyPI 정식
     릴리스(`korail2>=0.4.0`)로 그대로 의존하고, **DynaPath 토큰 생성·헤더 부착 로직만
     이 저장소 `adapters/`에 벤더링**한다. 소스는
     `https://github.com/dhfhfk/korail2.git` `bypassDynapath` 브랜치, 고정 커밋
     `4b134266fff097ea0fd54e9f760cb128b6c8f878`(2026-08-05 확인)로 못박는다 — 이 커밋의
     diff는 이미 공급망 검증(237줄 전체 리뷰) 대상이었으므로 벤더링 시점에 재검토가 필요 없다.
  5. **다음 앱 업데이트로 토큰 스킴이 다시 바뀌면 이 벤더 코드는 깨진다** — 원칙 2(Port 격리)
     덕에 파급 범위는 어댑터(벤더 모듈) 교체로 국한되지만, 유지보수 부채로 남는다는 점은
     명시해둔다. 벤더링을 택했으므로 업스트림 커뮤니티가 먼저 고쳐줘도 자동으로 받지 못하고
     직접 반영해야 한다는 트레이드오프도 함께 인수한다.
- **근거**: 항목 3(순수성)이 최우선 게이트였고, 이게 YES로 확정된 이상 나머지는 트레이드오프
  판단의 문제였다. 개인용 도구에서 "서비스가 자동화를 거부하는 신호"의 무게는 공개 서비스와
  다르게 본다 — 이 프로젝트는 처음부터 앱스토어 배포·공개 노출이 없다(2절 비목표, D-1).
### D-23. 로그인 유지 체크박스 — 세션 수명 이원화 *(v8, Phase 1 구현 중)*
- **문제**: v7까지 세션은 무조건 30일 지속 쿠키였다. 내 폰에서는 그게 맞지만,
  공용 PC나 잠깐 빌린 기기에서 한 번 로그인하면 **30일짜리 자격증명이 그 기기에 남는다.**
  Tailscale 내부망이라 노출면이 좁을 뿐, 세션 토큰 자체의 수명은 그대로다
- **결정**: 로그인 폼에 "로그인 유지" 체크박스를 두고 **쿠키와 서버 세션을 함께** 가른다
  - on: `Max-Age` 30일 쿠키 + 서버 세션 30일
  - off(기본): `Max-Age` 없는 브라우저 세션 쿠키 + 서버 세션 **12시간**
- **왜 쿠키만 바꾸지 않는가**: 쿠키만 세션 쿠키로 바꾸면 브라우저에서는 사라져도
  **서버 세션 행은 30일 살아 있다.** 그사이 유출된 토큰은 그대로 유효하므로 반쪽짜리다
- **`session.persistent` 컬럼을 두는 이유**: 슬라이딩 연장 때 어느 수명으로 늘릴지
  알아야 한다. 없으면 임시 세션이 접속할 때마다 30일로 승격돼 규칙이 무의미해진다
- **기본값을 해제로 둔 이유**: 보안 기본값은 안전한 쪽. 매일 쓰는 홈화면 앱에서는
  한 번 체크하면 그만이다
- **재검토 조건**: 홈화면 PWA에서 체크했는데도 세션이 자주 끊기면 수명·슬라이딩 정책 재조정

### D-24. 가입 잠금: env `ALLOW_SIGNUP` → **관리자 토글** *(v8, D-10 개정)*
- **문제**: D-10의 잠금은 "첫 계정 만들고 env를 false로 되돌린다"였다.
  잠금 주체가 **배포 아티팩트**라, 지인에게 계정 하나 열어주려면 env를 고치고
  컨테이너를 재시작해야 한다. 열어둔 뒤 되돌리는 걸 잊으면 그대로 열린 채 남는다
- **결정**:
  1. 가입 허용 여부를 **DB**(`app_setting.signup_enabled`, 기본 false)로 옮긴다
  2. **첫 계정은 부트스트랩으로 항상 허용**(사용자 0명일 때)하고, 그 계정이 **관리자**가 된다
  3. 관리자만 `GET/PATCH /api/admin/settings`로 토글한다. env `ALLOW_SIGNUP`은 삭제
- **D-10과의 관계**: "열어둘 이유가 없는 엔드포인트는 닫는다"는 **그대로 유지**된다.
  바뀐 것은 잠금의 **위치**(배포 아티팩트 → DB)와 **주체**(재배포 → 관리자)뿐이고,
  기본값이 잠김이라는 점도 같다. 오히려 켠 뒤 끄는 비용이 없어져 실제로 더 자주 닫히게 된다
- **관리자 승격 API를 만들지 않는 이유**: 1~2인용에서 권한 관리 화면은 과하다.
  관리자는 첫 계정 자동 부여뿐이고, 바꿀 일이 생기면 DB에서 직접 고친다
- **비목표와의 경계**: 2절의 "회원가입 개방"은 여전히 비목표다. 이 토글은
  **닫힌 상태를 기본으로 두고 필요할 때만 잠깐 여는** 장치이지 공개 가입이 아니다
- **미해결로 남긴 것 (v9 추가)**: 잠긴 상태에서 관리자 계정을 잃으면 앱 안에 탈출구가 없다.
  복구 수단(CLI 승격 등)은 **Phase 4 항목으로 이월**한다 — 11절 Phase 4 참고.
  그때까지는 DB 파일 직접 수정으로 대응한다

### D-25. 열차 선택 UX: 역 드롭다운 + 시각 하한 검색 *(v9, Phase 1 구현 중)*
- **문제**: Phase 1의 탑승 등록 화면은 열차번호·역 이름을 **텍스트로 입력**받았다.
  목업 관통이 목적이라 최소로 만든 것인데, 실사용에서는 성립하지 않는다:
  - 사용자는 정식 역명을 모른다(`서울`인지 `서울역`인지). **오타가 곧 404**다
  - 열차번호를 외워서 다니지 않는다. 통근에서 고르는 것은 "몇 시 차"가 아니라
    **"퇴근하고 탈 수 있는 차"** 다 — 검색의 입력은 시각 **하한**이어야 한다
- **이미 있던 것 / 없던 것**: 7절의 `GET /api/trains/search?...&time=`과
  10절의 "열차 선택 화면"은 v5부터 있었다. 없던 것은 **역 목록의 출처**다 —
  `station` 테이블이 "GPS 보정용"으로만 규정돼 있어 드롭다운 소스가 계획에 없었다
- **결정**:
  1. `station` 테이블의 **용도를 2개로 명시**한다: GPS 보정 좌표(D-13) + **역 선택 드롭다운 소스**
  2. `GET /api/stations` 신설. `KorailPort`에 `list_stations()`를 추가해
     Phase 1은 Mock 노선을, Phase 2는 station 테이블을 소스로 쓴다
  3. `search_trains`에 시각 하한(`time`)을 실제로 구현한다 (스펙에만 있고 구현이 비어 있었다)
  4. **UI 골격은 Phase 1에서 만든다** — Mock 어댑터가 시각대가 다른 열차 여러 편을 주도록 넓혀
     역 드롭다운 → 시각 하한 검색 → 열차 선택 흐름을 눈으로 확정하고,
     Phase 2에서는 **데이터 소스만** 갈아끼운다
- **Phase 2의 선행 과제로 남는 것**: 역 마스터 데이터의 출처. Phase 0 라이브러리 감사에서
  korail2 공개 메서드에 역 목록이 없음을 확인했다(`login/logout/search_train/
  search_train_allday/reserve/tickets/reservations/cancel`). 항목 5(열차번호 → 전체 정차역
  파생 불가)와 **같은 뿌리의 문제**이며, 공공데이터포털 등 외부 소스 검증이 필요하다
- **원칙 1과의 관계**: 역 이름을 드롭다운으로 고르게 하는 것은 하드코딩이 아니다.
  목록은 여전히 **데이터에서 온다**. 도메인 로직은 지금도 "수원"이라는 단어를 모른다

### D-26. `estimate_seg` 지연 보정의 부호 오기 정정 *(v10, Phase 2 구현 중)*
- **문제**: 5절 '현재 구간 추정'이 `arrival(stops[i]) ≤ now + 지연보정`으로 적혀 있었는데,
  9절의 "실효 도착시각 = 시각표 도착시각 + 지연분"과 **부호가 반대**다. 두 표기는 같은
  값을 계산하지 않는다.
- **어느 쪽이 맞나**: 9절이 맞다. 열차가 `delay_min`만큼 **늦으면** 각 역에 실제로 닿는
  시각이 뒤로 밀리므로, 같은 `now`에서 현재 구간은 오히려 **앞(작은 인덱스)** 이어야 한다.
  5절 표기대로 `now`에 지연을 더하면 늦은 열차가 오히려 **더 멀리 간 것**으로 계산돼
  방향이 뒤집힌다 — 지연이 클수록 크게 틀린다.
- **왜 Phase 1에서 안 터졌나**: `ZeroDelayAdapter`가 항상 지연 0을 주어 두 표기가
  같은 값을 냈다. **지연 보정을 실제로 켜는 Phase 2에서야 드러나는 종류의 버그다.**
- **결정**: 5절 문구를 `실효도착(stops[i]) ≤ now`로 고친다. 구현
  (`app/domain/timeline.py`의 `estimate_seg`/`effective_arrival`)은 Phase 1부터 이미
  9절 정의를 따르고 있었으므로 **코드 변경 없음** — 문서만 정정한다.
- **남기는 이유**: 뒤집힌 결정도 지우지 않는다(개정 이력 유지). 같은 함수를 다시 만질
  사람이 5절만 읽고 "구현이 문서와 다르네"라고 되돌리는 일을 막는 것이 이 항목의 목적이다.

### D-27. 좌석맵 호차 범위 + 재시도 정책 이원화 *(v10, Phase 2 구현 중)*
- **문제 (문서가 침묵하던 지점)**: 5절은 `get_seat_map(frm, to)`를 **구간 단위**로 규정하는데,
  실제 코레일 좌석맵(`ResidualSeatsResearch.do`)은 **호차 단위**다. 한 구간을 채우려면
  호차마다 한 번씩 불러야 한다. PLAN에는 "어느 호차를 조회할지"가 어디에도 없었다.
- **호출량**: 인접 구간 1개당 `ScheduleView` 1회 + `TrainResearch` 1회 + 호차 수만큼
  `ResidualSeatsResearch`. 천안→서울(구간 5개) × 일반실 6량이면 **40회**로,
  10절·CLAUDE.md의 "조회는 정차역당 1~2회가 상한"을 4배 넘는다. 그 상한은 좌석맵이
  구간 단위라는 전제로 쓰인 값이며, 전제가 틀렸음이 Phase 0 이후 드러났다.
- **결정 1 — 잔여석 있는 일반실 호차만 조회한다.**
  `TrainResearch`가 호차별 잔여석을 주므로 **먼저 걸러낸다**. 잔여 0인 호차는 좌석맵을
  받아봐야 전 좌석 판매됨이므로 조회하지 않는다.
  - **추천 품질 손실 없음** — 빠진 호차는 어차피 추천 대상이 아니다
  - 매진에 가까운 시간대일수록 절감이 크다 = **호출이 가장 아까운 때에 가장 많이 아낀다**
  - 빠진 호차의 좌석은 매트릭스에 등장하지 않는데, 이는 **내 좌석 부재 규칙**(D-18)이
    이미 처리한다 — 매트릭스에 없으면 잔여 전 구간 판매로 간주. 잔여 0 호차에 앉아
    있었다면 그 판정이 정확히 맞다
  - `h_rest_seat_cnt`를 못 읽으면 **조회 대상으로 남긴다**. 모르는 값을 0으로 보고
    건너뛰면 좌석이 조용히 사라진다 — 호출 한 번을 더 쓰는 편이 낫다
  - 항목 A가 확정돼 `get_stops`가 역코드·운행순번을 함께 주면 구간마다의 `ScheduleView`가
    불필요해져 **5회 → 1회**로 준다 (그때 이 절의 호출량 계산을 갱신할 것)
- **결정 2 — 재시도를 화면/스케줄러로 나눈다.**
  "재시도 30초×3"은 최악 60초 대기라 사용자를 화면 앞에 세워둔다.
  - 스케줄러: `SCHEDULER_RETRY`(3회 × 30초) — 10절 상한 그대로. 8절 `FETCH_FAILED`가
    세는 대상이 이것이다
  - 화면: `SCREEN_RETRY`(2회 × 2초) — 빨리 실패하는 편이 낫다. 새로고침이 곧 재시도다
  - 둘 다 `RetryPolicy` 설정값으로 격리한다 (매직 넘버 인라인 금지, D-17)
- **10절 상한 문구의 지위**: "정차역당 1~2회"는 이제 **구간당 좌석맵 호출 1회**가 아니라
  **구간당 (1 + 1 + 잔여 있는 호차 수)** 로 읽어야 한다. 원문을 지우지 않고 이 항목으로
  개정 이력을 남긴다.
- **지연 정보의 곁가지**: 지연(`h_expct_dlay_hr`)과 열차명은 전용 엔드포인트가 없고
  `ScheduleView` 응답에 실려 올 뿐이다. 이를 위해 따로 조회하면 같은 정보에 호출을 한 번
  더 쓰게 되므로, 좌석맵 조회가 이미 부르는 `ScheduleView`에서 **주워 담아 두고 읽기만**
  한다(`TrainObservations`). 첫 화면 로드에는 관측이 없어 지연이 None(=0)인데, 이는
  Phase 1의 `ZeroDelayAdapter`와 같은 동작이라 퇴행이 아니며 이후 조회에서 자동 보정된다
  (D-12의 "2회 조회가 보완한다" 전제와 일치).

### D-28. 역 마스터 소스 = 공공데이터 CSV 적재 (API 아님) *(v10, Phase 2 구현 중)*
- **결정**: 역 마스터는 런타임 API가 아니라 **CSV를 DB에 적재**해 쓴다
  (`station` 테이블, `scripts/load_stations.py`). 정적 참조 데이터를 요청마다 외부에서
  긁을 이유가 없다 — 쿼터·네트워크 의존이 사라지고, **열차 안에서 네트워크가 나빠도
  역 목록은 항상 뜬다**(10절 '열차 안 네트워크 대응'과 같은 방향).
  부수 효과로 `codes2` API가 불필요해졌다 (`cond[type::EQ]` 유효값을 8가지 시도했으나 전부 0건).
- **적재 소스 2개** (역명으로 병합, 순서 무관):
  - `한국철도공사_철도운영정보_역코드` — 역코드↔역명 **1,255행**. 코드 체계가
    운행정보 API의 `stn_cd`와 **동일함을 실측 확인**(`3900023 서울`, `3900883 광명`)
  - `한국철도공사_역 위치 정보`(15127532) — 역명/위도/경도 **202행**. 역코드 컬럼 없음 → 좌표 축만
- **PK가 `code`가 아니라 `name`인 이유**: 세 소스(운행정보 API / 좌표 CSV / korail2)의
  역코드 체계가 다르고 좌표 CSV에는 역코드가 아예 없다. **역명이 유일하게 확실한 조인 축**이다.
  그래서 `normalize_name`(공백·괄호·`'~역'` 접미)이 이 기능의 핵심이다 — 표기 차이가 남으면
  에러가 아니라 **'좌표 없는 역'으로 조용히** 나타난다.
- **`usable` 플래그가 필요한 이유**: 역코드 CSV 1,255행 중 상당수가 `본청`·`서지청`·
  `구로열차소`·`송도교` 같은 **운영 지점**이다. 그대로 드롭다운에 넣으면 사용자가
  탈 수 없는 역을 고른다. 그 파일만으로는 여객역과 구분할 근거가 없으므로 **코드 사전으로만**
  쓰고(`usable=0`), 다음 두 경로로만 1이 된다 — 둘 다 데이터 근거가 있다(원칙 1):
  1. **좌표를 얻었다** — 15127532는 정의상 간선 여객역 202개다
  2. **시각표에 정차역으로 등장했다** — 열차가 서는 곳이면 여객역이다
  `usable`은 **끄는 방향으로 덮지 않는다**(`MAX`). 코드 사전을 재적재해 0으로 되돌리면
  드롭다운이 조용히 비어버린다.
- **개정 (같은 날, 세 번째 파일을 받고)**: 위 근거 1('좌표를 얻었다')을 **철회한다.**
  `전국_도시철도역사정보`(1,099행)를 받아보니 좌표가 913개 딸려 오는데 그중
  `강남`(신분당선)·`가락시장`(3호선)·부산 도시철도처럼 **ITX가 서지 않는 역이 대부분**이다.
  더구나 코레일 역코드 사전 자체가 이런 지하철역을 이미 포함하고 있어(`--coords-only`로
  기존 행만 갱신했는데 383개가 채워졌다) "코드+좌표 있음"도 필터가 되지 못한다.
  → `usable`은 **추론하지 않고 적재하는 쪽이 명시**한다 (`load_stations.py --passenger`).
  여객역 목록임이 확실한 파일(15127532, 간선 여객역 202개)에만 붙인다.
- **적재 모드 3개** (파일 성격이 달라 한 가지 규칙으로 덮을 수 없다):
  | 파일 | 플래그 | 효과 |
  |---|---|---|
  | 역코드 사전 (1,255행) | 없음 | 코드 축만. `usable=0` |
  | 간선 여객역+좌표 (202행) | `--passenger` | 좌표 + `usable=1` |
  | 전국 도시철도 (1,099행) | `--coords-only` | **기존 역의 좌표만**. 새 역 생성·`usable` 변경 없음 |
  `--coords-only`가 없으면 전국 지하철 913개가 역 테이블로 쏟아진다.
  또한 이 파일의 `역번호`는 `D004` 형식으로 코레일 역코드와 **다른 체계**이므로
  `code`에 매핑하지 않는다 — 섞이면 `code_for()`가 지하철 코드를 돌려준다.
- **적재 실적 (2026-08-05)**: `station` 1,216행 / 좌표 584 / `usable` 201.
  좌표는 세 번째 파일로 201 → 584로 늘어 **통근 경로 전 구간(안양·오산·서정리·성환·
  직산·두정 포함)이 GPS 투영 가능**해졌다. 다만 그 역들은 `usable=0`이라 아직
  드롭다운에 없다 — 시각표 적재(항목 A)가 확정해 줄 몫이다.
- **같은 역명에 역코드가 여러 개인 경우 25건** (`의왕` 3900044/3900447, `원주` 3900142/3901099 …
  폐역·이설로 구/신 코드가 함께 남은 것). CSV만으로는 어느 쪽이 현재 코드인지 알 수 없으므로
  **임의로 고르지 않는다**: 적재는 코드 오름차순 첫 번째로 **결정적으로** 고정하고
  (마지막 행이 이기게 두면 파일 정렬이 바뀔 때 저장 코드도 바뀌어 재현이 안 된다),
  시각표를 적재할 때 **권위 있는 값으로 덮는다**(`mark_usable(codes=...)`) —
  열차가 실제로 운행하는 코드가 정답이다.
- **`/api/stations`는 `usable=1`만 반환**하고, 하나도 없으면 Mock 노선으로 폴백한다.
  미적재 개발 환경에서 화면이 통째로 죽지 않게 하기 위한 것이며 `ADAPTER=mock` 흐름도 유지된다.
- **원칙 1과의 관계**: 목록이 여전히 **데이터에서 온다**. 코드에는 역 이름이 없고
  도메인 로직은 지금도 "수원"이라는 단어를 모른다.

### D-29. `get_stops()` 확정 — 최근 운행일 실적을 열차번호 템플릿으로 캐시 *(v10, Phase 2 구현 중)*
- **Phase 0 항목 5(NO) 해결.** 코레일에는 열차번호로 전체 정차역을 주는 엔드포인트가
  없지만, 공공데이터 '한국철도공사_열차운행정보'(`travelerTrainRunInfo2`)가
  **실적(과거) 데이터**로 정차역+운행순번+시각을 준다. 단, 이 API는 두 가지 제약이 있다:
  1. **실적이라 과거만 있다** (대개 D-1까지). 오늘 탈 열차의 정차역이 오늘 자로는 안 나온다
  2. 필터가 `cond[필드::연산자]` 형식이라(`run_ymd=`가 아니라 `cond[run_ymd::GTE]`)
     표기가 틀리면 파라미터가 **조용히 무시되고 전체 데이터셋이 페이지네이션돼 돌아온다**
     — 에러가 안 나서 3차례 프로브 중 두 번을 이걸로 날렸다(4차 프로브 기록 참고)
- **실측 근거 (4차 프로브)**: 무궁화호 1472의 정차 순서가 화·월·일·**토** 4일 연속
  완전히 동일(16개 정차역, 순번·역코드·시각 일치). 요일 편차까지 덮인 실증이므로
  **정차 순서는 열차번호 단위로 캐시해도 안전하다**는 결론이 나온다.
- **결정: `train_stop` 테이블에 최근 운행일(D-1) 실적을 템플릿으로 캐시한다.**
  절대 시각이 아니라 **시각(time-of-day) + 날짜 오프셋**으로 저장하고, 조회 시점의
  실제 요청 날짜에 재적용한다(`storage/train_stops.get_stops`). 시발역은 도착 기록이
  없으므로 **출발시각으로 대신한다** — `StopInfo.arrival`이 필수 필드이고(5절),
  "그 시각에 그 역에 있다"는 물리적 사실은 동일하다.
- **적재는 `scripts/load_train_stops.py`** (역 마스터 로더와 같은 성격 — 정적 참조가
  아니라 "최근 실적"이므로 **주기적 재적재가 필요**하다. Phase 3에서 스케줄러에
  붙이거나 cron으로 자동화할 수 있다. 지금은 수동 스크립트로 충분).
- **부수 효과 — G(역 usable)와 D-28의 코드 충돌이 여기서 함께 풀린다.**
  이 API의 매 행에 `stn_cd`+`stn_nm`이 있고, 열차가 실제로 서는 역이므로 **여객역인
  것이 확실**하다 — 좌표 유무로 추론하지 않는다는 D-28 개정 원칙을 지키면서
  두 번째 근거(시각표 등장)를 실제로 가동한 것이다. 같은 역명에 역코드가 여럿인
  경우(D-28의 25건, 예: `경주` 3900647/3900895)도 여기서 **권위 있는 값으로 확정**된다
  — 열차가 실제로 쓰는 코드가 정답이다(`stations.mark_usable(codes=...)`).
- **열차번호가 정기 개정으로 바뀔 수 있다 (알려진 리스크).** 익산→용산 노선을
  8/4엔 `1472`가 뛰었는데 8/6 이후 관측에서는 `1472`가 사라지고 `1202~1210`대가
  나타났다 — 같은 노선을 다른 번호가 대체한 것으로 보인다(코레일 정기 시각표
  개정으로 추정, 확인된 사실은 "8/4엔 있었고 8/6엔 없다"까지다). 대응:
  - 캐시에 없는 열차번호는 `TrainStopsNotCached`로 **명확히 실패**한다.
    조용히 빈 매트릭스를 주지 않는다
  - 재적재로 회복된다. 개정 주기가 잦지 않다면(분기 단위로 추정) 일 단위 재적재로 충분
- **알려진 한계 — 저빈도 역은 하루 표본에 안 잡힐 수 있다.** `두정`·`직산`(역코드
  체계상 성환-직산-두정-천안 순으로 인접)이 4일(8/1~8/4)치 어디에도 정차 기록이
  없었다 — 이름 변형(두정역/천안두정 등)으로도 재확인했으나 전부 0건. 그 역에
  현재 서는 열차가 실제로 없거나 극히 드물다는 뜻으로 해석한다. **틀린 게 아니라
  정확한 판정**이다 — 열차가 안 서는 역을 드롭다운에서 빼는 것이 맞다. 나중에
  다른 날짜 적재에서 정차 기록이 나오면 `usable`이 자동으로 켜진다(끄는 방향으로는
  덮지 않으므로 안전하게 누적된다).
- **적재 실적 (2026-08-05, 4일치 누적)**: `train_stop` 731→920편, `station` `usable`
  201→**282**개. 통근 노선(천안~서울) 대부분이 `usable=1`로 확정됨. `codes2` API는
  끝내 쓰지 않았다 — 이 소스 하나로 역 마스터의 코드 축·usable·시각표를 전부 덮는다.

### D-30. GPS 선분 투영 구현 — `domain/geo.py` (v10, 항목 G 후반, D-13/D-21 실구현)
- `domain/geo.py`를 순수 함수로 구현했다. 좌표 조회(station 테이블)는 api 계층
  (`app/api/trains.py`)이 하고 도메인은 계산만 한다 (절대규칙 4).
- **등장방형(equirectangular) 근사**로 위경도를 평면 미터 좌표로 바꿔 투영한다.
  경도 1도의 실거리가 위도의 코사인에 비례해 줄어드는 것을 보정하지 않으면
  남북으로 뻗은 구간일수록 오차가 커진다. ITX 이동거리(최대 수백km)에서
  이 근사의 오차는 무시할 수준이다.
- **후보 구간은 양 끝 역 모두 좌표를 가진 인접 구간으로 한정**한다. 한쪽이라도
  좌표가 없으면 그 구간은 판정에서 빠진다 — 조용히 틀린 구간을 고르지 않는다.
  (G의 결과로 좌표가 없는 역이 아직 있다 — D-28/D-29 참고. 좌표가 채워질수록
  이 함수는 코드 변경 없이 저절로 정확해진다.)
- `GeoConfig`로 조정값(신선도 30초·정확도 100m·노선 이탈 300m)을 격리했다 (D-17).
  수치는 실사용 전 잠정값 — Phase 4 조정 대상.
- **`/matrix`의 GPS 파라미터 4개**(`lat`, `lng`, `gps_accuracy_m`, `gps_fixed_at_ms`)는
  **넷 다 와야 시도한다.** 일부만 오면 신선도를 판단할 수 없으므로 시각표 추정을
  그대로 둔다 (안전한 방향, D-21). `gps_fixed_at_ms`는 ISO8601 문자열이 아니라
  **epoch 밀리초**를 받는다 — 브라우저 `Geolocation.timestamp`가 그 형태이고,
  naive/timezone 표기 논쟁 없이 KST로 직접 변환된다.
- GPS 보정은 `current_seg_idx`를 **`query_range` 계산 전에** 덮어쓴다 — PLAN이
  "현재 위치를 GPS 실측으로 덮어씀"이라 명시했으므로 조회 구간·판정·다음 폴 힌트가
  전부 보정된 위치 기준으로 흘러간다.
- `last_verdict_hash`는 이 경로에서 손대지 않는다 — 애초에 `/matrix`가 그 컬럼을
  건드리지 않으므로 D-13이 요구한 격리가 구조적으로 이미 지켜진다.
- 테스트 28개 (도메인 22 + API 통합 6): 신선도 경계값, 기하 헬퍼(수직 거리·클램프·
  퇴화 선분), 실제 노선 좌표 기반 구간 판정, 오매칭 방지(타 노선 좌표 후보 제외),
  좌표 미확보 시 폴백.
