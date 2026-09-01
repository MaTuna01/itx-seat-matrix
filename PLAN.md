# ITX 자유석 좌석 매트릭스 조회 서비스 — 기획 및 구현 계획

> 개인용 프로젝트. 앱스토어/퍼블릭 배포 없이 사용.
> 이 문서는 Claude Code로 구현할 때 컨텍스트로 사용한다.
>
> **문서 버전: v28**
> - v1: Spring Boot + Python 사이드카, 알림 봇 중심
> - v2: Python 단일 스택으로 전환
> - v3: 알림을 정식 목표로 승격, 계정(회원) 계층 도입
> - v4: 알림 채널을 iOS 웹푸시 기본 + 디스코드 opt-in으로 확정
> - v5: 지연 대응(DelayPort + 정차역당 2회 조회) + GPS 포그라운드 위치 보정
> - v6: Phase 0 실현 가능성 검증 신설 + 구독 상태 기계(입석/착석) + 알림 체계 재설계(셀 전이 기반) + 운영 디테일 확정
> - v7: 구현 디테일 확정 — 좌석 유니버스/부재 추론, 인덱스·시각 규칙, 폴링 멱등성(next_poll_at), 알림 합성·베이스라인·기기 정리, 공통 구현 규칙(KST·clock 주입·to_thread)
> - v8: Phase 1 구현 중 인증 설계 갱신 — 로그인 유지(세션 수명 이원화) + 가입 잠금을 env에서 관리자 토글로
> - v9: 열차 선택 UX 확정 — 역 드롭다운 + 시각 하한 검색, station 테이블 역할 확장
> - v10: Phase 2 구현·실사용 반영 — 정차역 캐시(`get_stops`) 확정, 역 마스터 = 공공데이터 CSV, 좌석맵 호차 범위 + 재시도 이원화, GPS 선분 투영, 매트릭스 표시 범위 = 내 구간, 시크릿 pre-commit 훅 (D-26~D-33)
> - v11: Phase 3 구현·실사용 반영 — 알림 배선에서 문서가 침묵한 4개 지점 확정, 코레일 계정의 사용자별 분리 명문화, 매진을 실패가 아니라 데이터로 흡수, 직전 구간 자동 프리필 (D-34~D-37)
> - v12: **Phase 4 배포 — 접근 경로 A 확정(D-38), 배포 산출물(Dockerfile/compose/DEPLOY.md), 배포가 드러낸 침묵 3개: 앱 로그 유실 / 빌드 머신 / WAL 이관 (D-39~D-41), 인스턴스 OS = 우분투(D-42)**
> - v13: **iOS 재디자인을 Phase 5로 배치 (D-43)** — 피그마 11화면, 백엔드 무변경 전제, 데이터 계약 2건 미정
> - v14: **CI 도입 (D-44)** — 네이티브 arm64 빌드 검증, 시크릿 검사 규칙을 훅과 공유, 워크트리에서 훅의 핵심 방어가 꺼져 있던 구멍 수정. 배포는 건드리지 않는다(CD는 별도)
> - v15: **퇴근길이 드러낸 매진 오판정 (D-45)** — `clear_until`로 매진을 판정해 "시작 구간만 매진"이 "전 구간 매진"으로 뒤집혔고 `ALL_SOLD`까지 발사됐다. 지연 착석 추천은 미정
> - v16: **추천을 두 목록으로 (D-46)** — "지금 앉을 수 있는 자리"와 "몇 정거장 뒤부터". 지연 착석은 지금 앉을 자리가 없을 때만 의사결정에 관여한다(해시·화면 공통)
> - v17: **운행 중인 구간은 조회하지 않는다 (D-47)** — 위치(`estimate_seg`)와 "팔 수 있는 첫 구간"(`sellable_seg_idx`)은 다른 값이다. 출발 직후 모든 폴링이 그 구간을 매진으로 읽어 `ALL_SOLD`가 실제로 발사됐다
> - v18: **한 구간의 조회 실패가 매트릭스 전체를 죽이지 않는다 (D-48)** — 사유를 판별하지 말고 구조로 격리한다. 실패 구간은 매진이 아니라 "알 수 없음"이며, 화면은 색만 쓰지 않고 물음표를 함께 찍는다
> - v19: **내 자리를 매트릭스 최상단에 고정 (D-49)** — 필터로도 감추지 않는다. 최상단의 뜻이 "추천 1순위"에서 "내 자리"로 바뀌므로 구분선으로 가른다
> - v20: **web / iOS 스킨 분리 (D-50)** — 접속 기기로 고른다. 판정 문구와 행 순서는 `core/format.js`가 한 번만 만들고 스킨은 그리기만 한다(갈리면 뒤처진 쪽이 "틀린 정보"가 된다). Phase 5는 `skins/ios/`를 화면 단위로 채운다
> - v21: **CD 도입 (D-51)** — `dev → main` 머지가 곧 배포. 레지스트리 없이 러너를 tailnet에 들여보내는 push 방식(D-40 유지)이고, 재배포 가드는 시각이 아니라 DB의 폴 포인트를 본다. `deploy_check.sh` 실패 시 이미지와 작업 트리를 함께 되돌린다
> - v22: **매트릭스는 좁히지 말고 밀어라 (D-52)** — 구간 열 너비를 균등하게 고정하고, 다 안 들어가면 글자를 줄이는 대신 가로로 스크롤한다(좌석 열은 고정). 좌석 액션 바는 문서 끝이 아니라 화면 하단에 고정한다. 선택한 좌석의 구간 문구도 `core/format.js`로 옮겼다 — 지금 팔린 좌석에 "…까지 빈 좌석"을 찍어 **판정 카드와 다른 말을 하고 있었다**
> - v23: **사용자 관리를 앱에 넣는다 (D-53)** — 11절이 권장하던 CLI를 뒤집어 관리자 화면에서 목록 조회·삭제를 한다. 대가로 방어를 네 겹(관리자 전용 / 비밀번호 재확인 / 자기 자신 금지 / 관리자 계정 금지)으로 두고, 뒤의 둘은 UI가 아니라 서버가 거절한다
> - v24: **미사용 시간대 자동 정지 (D-54)** — 평일 06:00~24:00만 가동한다. 기동은 EventBridge지만 **정지는 조건부다** — 고정 시각으로 끄면 그동안 도래한 폴이 grace를 넘겨 조용히 스킵된다(D-19). 가드가 "다음 기동 전에 폴이 있는가"를 DB에 묻고, 판단이 안 서면 **켜둔 채로 실패한다** (D-51의 배포 가드와 반대 방향)
> - v25: **DB 백업 (D-55)** — S3에 하루 1개·30일. 핵심은 "떴다고 끝이 아니다": 빈 DB도 `.backup`은 성공하므로 `user`·`station`을 검증하고, 성공 기록은 업로드 뒤에만 쓴다. 실패는 새 알림이 아니라 `deploy_check.sh`의 한 줄로 드러낸다
> - v26: **즐겨찾기 노선 (D-56)** — Phase 1부터 잠자던 프리셋을 "즐겨찾기 노선" 칩으로 탑승 등록 화면에 노출한다. 계정당 5개, 상한은 프론트가 아니라 서버가 409로 지킨다. 판정·문구는 `core/favorites.js`가 한 번만 만든다
> - v27: **갭 구간은 마지막 스냅샷으로 보여주고, 출발 -1분에 한 번 더 본다 (D-57)** — D-47이 옳게 조회를 끊은 구간이 화면에서도 통째로 사라졌다. 지금 타고 있는 구간 `[열차 위치, 판매 가능 시작)`은 마지막 성공 조회를 **표시 전용**으로 유지하고, 정차역당 폴을 2회→3회(-10/-4분 도착 + 출발 -1분)로 늘려 스냅샷 신선도를 확보한다. 판정·알림·추천은 D-47 그대로다
> - v28: **정차역 캐시 자동 재적재 + 캐시 불일치 에러 매핑 (D-58, 이슈 #75/#76)** — 2026-09-01 코레일 개편으로 스테일 캐시가 실 장애를 냈다. D-29에서 "지금은 수동으로 충분"으로 유예했던 자동화를 붙였다: 06:05/12:05 KST + 기동 캐치업 + `reload_needed` 게이트. 저장 후 오래된 번호를 퍼지(`train_stop_max_age_days=7`)해 번호 재사용 충돌을 잘라낸다. `TrainStopsNotCached`가 `_compute_next_poll_at`에서 500으로 새던 버그를 봉쇄하고, 노선 불일치 문구를 정보 기준일과 함께 사용자용으로 통일했다
>
> "왜 이렇게 했지?"가 궁금하면 [17. 결정 이력](#17-결정-이력-decision-log)을 먼저 읽을 것.
> 방향을 튼 지점은 전부 거기에 이유와 함께 남겨두었다.
>
> **현재 위치: Phase 3 코드 완료 → Phase 4(배포) 착수 대기.** 진행 상황은 11절,
> 다음 세션에 붙여넣을 프롬프트는 16절에 있다.

---

## 0. 최우선: Phase 0 실현 가능성 검증 (→ D-14)

**아래가 검증되기 전에는 본 구현에 착수하지 않는다.** 반나절짜리 스크립트로 go/no-go를 확인한다.

> **이 절은 종료됐다 — 최종 판정 GO (2026-08-05, → D-22).** 아래는
> NO-GO → 안티봇 우회 발견 → GO로 **두 번 뒤집힌 과정을 시간순으로** 남긴 것이다
> (뒤집힌 판정도 지우지 않는다). 결론만 필요하면 이 절 끝의 **"최종 판정 — GO"** 로 건너뛸 것.

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
- **공개 노출 대안은 검토만 하고 보류했다** — 접근할 기기마다 Tailscale을 깔아야 하는 것이
  부담이 되면 Cloudflare Tunnel + Access로 전환한다. Vercel을 배제한 이유 포함 → D-38

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
    clear_from_idx: int                    # 언제부터 앉을 수 있는가 (→ D-46)
    clear_until_idx: int
    clear_all: bool                        # clear_from_idx부터 하차역까지 계속 빈다

class Verdict(BaseModel):
    sub_status: SubscriptionStatus
    # ── SEATED일 때만 채워짐, STANDING이면 None ──
    my_seat_status: Literal["CLEAR_ALL", "SOLD_FROM", "UNKNOWN"] | None
    my_seat_sold_from: str | None
    my_seat_clear_until_idx: int | None
    # ── 공통 ──
    move_to: list[SeatRecommendation]      # 지금 앉을 수 있는 좌석
    move_to_later: list[SeatRecommendation]  # 몇 정거장 뒤부터 앉을 수 있는 좌석 (→ D-46)
    all_sold_after_current: bool           # True → "지하철 환승 고려"
    current_seg_idx: int

# ── 알림 (→ 8절, D-16) ─────────────────────
class AlertKind(str, Enum):
    SEATS_AVAILABLE = "SEATS_AVAILABLE"  # [입석] 앉을 수 있는 좌석 다이제스트 (지연 착석 포함)
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
- **실효 시작 = `max(sellable_seg_idx, board_idx)`** — 조회 범위·판정·알림은 전부
  `실효 시작 ~ alight_idx`로 통일. 탑승역 이전 구간은 열차가 어디를 달리든 관심 밖
  - *v17 정정 (→ D-47)*: 첫 항은 **열차 위치(`current_seg_idx`)가 아니라 팔 수 있는 첫
    구간(`sellable_seg_idx`)** 이다. 이미 출발한 구간을 실효 시작으로 삼으면 코레일이
    빈 응답을 주고, 그것이 아래 부재 추론을 타고 '전 좌석 판매됨'이 되어 판정이 뒤집힌다
  - `[실효 시작, alight)`가 **빈 범위일 수 있다** — 마지막 구간을 달리는 중이면 팔 수 있는
    구간이 없다. 조회 0회 + `decision_needed=False` (→ D-47)
  - *v27 (→ D-57)*: 조회·판정에서 빠진 **갭 구간 `[max(위치, board), 실효 시작)`** —
    지금 타고 있는 구간 — 은 화면에서 숨기지 않고 `seat_snapshot`의 마지막 성공 조회를
    **표시 전용**으로 그린다 (점선 셀 + "HH:MM 조회" 배지). 판정·알림·추천에는 절대
    유입되지 않는다. `decision_needed=False`여도 스냅샷이 있으면 그 열은 그린다
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

**위치와 "팔 수 있는 첫 구간"은 다른 값이다** *(v17 → D-47)*. 위 규칙은 **위치**만 정한다.
조회·판정의 시작은 별도 함수 `sellable_seg_idx(stops, delay_min, now, position_idx=None)`다:

- **출발했으면 다음 구간, 정차 중이면 그 구간** — 기준은 도착이 아니라 **출발시각**
  (실효 출발 = 시각표 출발 + 지연분). 출발한 구간은 코레일이 팔지 않는다
- `departure`가 없으면 `arrival`로 폴백한다. 실데이터에서 비는 것은 종착역뿐이고
  종착역은 구간의 시작이 될 수 없다 — 캐시가 부실할 때를 위한 방어다
- GPS 보정값도 반드시 이 함수를 거친다(`position_idx`). GPS는 **주행 중인 구간을 정확히
  짚어주므로** 그대로 조회에 쓰면 오히려 팔 수 없는 구간을 확실히 조회하게 된다

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
- **조회에 실패한 구간은 매진이 아니다** *(v18 → D-48)*. 셀은 `bool` 하나라 실패 구간도
  채움값(판매됨)으로 들어가므로, 매트릭스가 `failed_seg_idxs`로 **어디가 관측값이 아닌지**를
  함께 들고 다닌다. 화면은 세 번째 상태로 그리고, `all_sold_after_current`는 실패 구간이
  있으면 무조건 `False`다 — 모르는 것을 매진이라 부르지 않는다.
  `clear_until`은 반대로 실패 구간에서 **멈춘다**(= "여기까지 확인됨").
- **매진 구간은 빈 응답으로 들어온다** *(v11 → D-36)*. 코레일은 매진 구간에 열차 자체를
  주지 않으므로 어댑터가 **빈 좌석맵**을 돌려준다. 위 합집합 규칙이 그 구간을 전 좌석
  판매로 채우므로 별도 처리가 필요 없다 — 다만 **그것을 조회 실패로 취급하면 안 된다.**
  일부 구간만 매진일 때 "중간까지는 앉을 수 있다"가 통째로 사라진다 (D-36에서 수정)

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
- **추천은 두 목록이다** (→ D-46). 합치지 않는다 — 합치면 1순위가 "지금 못 앉는 자리"가
  될 수 있고, 그러면 화면에서 그 구분을 다시 만들어내야 한다
  - `move_to` — **지금** 앉을 수 있는 좌석 (`clear_until > 실효 시작`)
  - `move_to_later` — 지금은 못 앉지만 **몇 정거장 뒤부터** 앉을 수 있는 좌석.
    `longest_free_run(cells, start, alight)`의 **가장 긴 연속 빈 구간** 기준으로 정렬하고,
    길이가 같으면 **일찍 앉을 수 있는 쪽**이 위다 (멀리 있는 구간일수록 그때까지 남아 있을
    가능성이 낮다). 퇴근길처럼 탑승 구간만 매진일 때 `move_to`는 비고 이쪽만 찬다
  - 응답에는 `clear_from_idx`("언제부터")가 **반드시** 실린다. 이 값 없이 추천만
    내보내면 사용자가 지금 앉을 수 있다고 오해한다 — 추천을 안 하느니만 못하다
- `all_sold_after_current = True`의 정의: **남은 구간 `[실효 시작, 하차)` 안에 빈 셀이
  하나도 없을 때** (내 좌석 포함, 전 좌석 × 전 구간). **`clear_until`로 판정하면 안 된다** —
  그 값은 시작 구간부터 *연속으로* 빈 구간만 세므로 "시작 구간만 매진"이 "전 구간 매진"으로
  뒤집힌다. 그러면 앉을 수 있는데 환승을 권하고 `ALL_SOLD`가 발사된다 (→ D-45)
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
GET    /api/admin/users                       → [{ id, email, display_name, is_admin,
                                                   created_at, korail_linked, discord_linked,
                                                   subscription_count }]   # 자격증명 없음 (→ D-53)
DELETE /api/admin/users/{id} { password }     → 204                        # 관리자 본인 비밀번호 재확인.
       # 자기 자신·관리자 계정은 400 (승격 API가 없어 관리자가 사라지면 복구 불가) (→ D-53)
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
       프론트 노출명은 "즐겨찾기 노선". 계정당 최대 5개 — 초과 POST는 409 (→ D-56)

POST   /api/subscriptions
       { train_no, date, board_at, alight_at, status, my_car?, my_seat_no? }
       → 오늘 탑승 세션 등록. status=SEATED면 my_car/my_seat_no 필수 (422 검증)
PATCH  /api/subscriptions/{id}   { status?, my_car?, my_seat_no? }   ★ 상태 전이 (→ D-15)
       → "여기 앉았음" (STANDING→SEATED), "자리 옮겼음" (좌석 변경), "일어났음" (SEATED→STANDING)
DELETE /api/subscriptions/{id}                    # 하차/취소

GET    /api/push/config     → { vapid_public_key, configured }   # 공개키만. 비밀키는 env (→ D-34)
GET    /api/push/devices    → [{ id, label, created_at }]        # endpoint·키는 응답에 없다
POST   /api/push/devices    { endpoint, keys, label }    → 기기 등록 (endpoint UPSERT)
DELETE /api/push/devices/{id}
POST   /api/push/test                                    → 테스트 발송 ★
       → { sent, devices, errors[] }. 발송 실패도 200이다 — 실패 이유를 화면에
         그대로 보여주는 것이 이 엔드포인트의 목적이다 (→ D-9)
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
    "move_to": [
      { "car": 4, "seat_no": "1B", "clear_from_idx": 1, "clear_until_idx": 5, "clear_all": true }
    ],
    "move_to_later": [
      { "car": 5, "seat_no": "2A", "clear_from_idx": 3, "clear_until_idx": 5, "clear_all": true }
    ],
    "all_sold_after_current": false,
    "decision_needed": true,
    "start_seg_idx": 1
  },
  "failed_seg_idxs": [],
  "snapshots": [
    { "seg_idx": 0, "as_of": "2026-08-05T08:02:00+09:00",
      "seats": [ { "car": 3, "seat_no": "7A", "sold": true } ] }
  ],
  "next_poll": { "station": "수원", "offset_min": 4, "basis": "arrival" },
  "fetched_at": "2026-08-05T08:14:02+09:00"
}
```

> `snapshots`는 갭 구간(지금 타고 있는 구간)의 **마지막 성공 조회**다 (v27 → D-57).
> 표시 전용 — `verdict`·알림·추천에는 유입되지 않는다. `next_poll.basis`는
> `"arrival"`(도착 -N분) | `"departure"`(출발 -N분) — 문구 분기는 `core/format.js`가 한다.

## 8. 알림 설계 *(v6 전면 재설계 → D-16)*

### 발송 조건 (이것만. 늘리지 말 것)

| 종류 | 상태 | 트리거 | 문구 예시 |
|---|---|---|---|
| `SEATS_AVAILABLE` | 입석 | 구간 진행(정차역 진입) 시 착석 가능 좌석 존재. **지금 앉을 수 있는 좌석이 없고 지연 착석만 있어도 보낸다** (→ D-46) — 폴링이 도착 10분/4분 전이라 미리 그 호차로 이동해 대기할 수 있다. **정차역당 최대 1회 다이제스트**, 같은 역의 -10분/-4분 조회 사이엔 내용이 달라졌을 때만 갱신 발송 | "수원부터 착석 가능: 4-1B (서울까지) 외 2석" |
| `MY_SEAT_SOLD` ★ | 착석 | 내 좌석이 **잔여 이용구간 내** 어디서든 판매됨. SOLD_FROM 상태가 지속되는 동안은 준-입석으로 취급해 **최상위 추천이 바뀌면 재발송** (구 `RECOMMEND_CHANGED` 흡수) | "3-7A 수원부터 판매됨 → 4호차 1B로 이동" / "1B 판매됨 → 4호차 4B로 변경" |
| `SEAT_EXTENDED` | 착석 | 내 좌석의 잔여 구간 셀 중 **판매(true)→빈자리(false) 전이** 발생. 실제 취소/환불과 1:1 대응 (하단 '감지 방식' 참고) | "3-7A 안양까지로 연장됨 (이동 불필요)" / "3-7A 서울까지 확보 — 이동 불필요" |
| `ALL_SOLD` | 공통 | 남은 구간에 앉을/옮길 좌석 전무 | "수원 이후 잔여 없음 → 1호선 환승 고려" |
| `FETCH_FAILED` | 공통 | **한 조회 시점 내 30초 간격 3회 재시도 모두 실패** (→ D-17). 재시도해도 같은 결과인 실패(자격증명 미연동, 정차역 캐시 없음)도 같은 게이트로 1회 (→ D-34) | "좌석 정보 갱신 실패 · 화면 데이터 낡음 (원인)" |

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
| STANDING | `(start_seg_idx, 최상위 추천 좌석 키, 지연 착석 1순위, all_sold_after_current)` |
| SEATED | `(my_seat_status, my_seat_sold_from, my_seat_clear_until_idx, 최상위 추천 좌석 키, 지연 착석 1순위, all_sold_after_current)` |

- `move_to` **전체 리스트와 정렬 순서는 해시에서 제외** — 하위 추천의 미세 변동으로 알림이 나가면 안 됨
- **지연 착석 1순위는 `move_to`가 비었을 때만 해시에 넣는다** (`좌석키@clear_from_idx`, → D-46).
  무조건 넣으면 **지금 앉을 자리가 있는데도** 지연 목록 변동으로 알림이 나간다 — 앉을 수 있으면
  그냥 앉으면 되므로 그 변동은 의사결정과 무관하다. 즉 **지연 착석은 지금 앉을 자리가 없을 때만
  의사결정에 관여한다.** 반대로 아예 넣지 않으면 퇴근길에는 알림이 영원히 안 온다
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
- 다이제스트의 좌석 문구에는 **"언제부터"가 반드시 들어간다** (지연 착석일 때
  `4-1B(수원부터 서울까지)`). 빠지면 지금 앉을 수 있다고 오해한다 (→ D-46).
  제목도 지연 착석만 있을 때는 "다음 역"이 아니라 **실제로 앉을 수 있는 역**을 쓴다
- `SEATS_AVAILABLE` 다이제스트는 **상위 3석**(clear_all 우선)까지만 + "외 N석" —
  상한은 설정값으로 격리 (→ D-17, D-20)
- 하차역 도착 시각 경과 시 구독 자동 만료 → 알림 자동 중단
- `FETCH_FAILED`는 1회 발송 후 복구까지 재발송 없음 (실패 알림 스팸 방지).
  게이트는 `subscription.fail_count`다 — 실패 +1 / 성공 0 리셋 / **`0→1` 전이에서만 발송** (→ D-34)
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

### 정차역 캐시 자동 재적재 *(v28 → D-58)*
30초 폴 틱과 같은 인프로세스 `AsyncIOScheduler`에 **두 번째 잡**을 붙였다:
- **cron `stops_reload_hours=6,12` · `stops_reload_minute=5`** — 평일 06:00 EC2 기동
  (D-54) 직후 06:05, 그리고 낮 12:05 복구 창구. `data_go_kr_service_key` 미설정이면
  잡 등록 자체를 건너뛴다 (mock/dev 무영향).
- **기동 60초 후 캐치업 1회** — 배포/주말 수동 기동을 커버.
- **`reload_needed(latest, now)` 게이트로 세 호출 멱등** — 이미 D-1 실적을 반영했으면
  네트워크 없이 스킵. 첫 성공만 fetch한다.
- **실패 = 로그만.** 알림 5종 불변 — FETCH_FAILED는 구독 단위이며 poller가 이미
  캐시 실패를 D-34 게이트로 1회 발사한다.
- **트랜잭션과 퍼지**: `apply_day`가 명시적 `BEGIN…COMMIT/ROLLBACK`으로 감싸(연결이
  autocommit이라 per-train 교체 사이의 순간을 폴 틱이 읽던 위험을 잘라낸다),
  저장 후 `source_run_ymd < run_ymd - train_stop_max_age_days(7)`를 퍼지한다 —
  이슈 #75의 원인(번호 재사용 충돌)을 시간으로 해소한다.

### 재시작 내구성 — next_poll_at 포인터 *(v7 → D-19)*
APScheduler는 인프로세스라 잡 상태가 메모리에 있다. 출근 시간에 컨테이너가 재시작되면
(OOM, 배포) 폴 포인트를 **중복 실행하거나 통째로 건너뛰어도 알 방법이 없다.** 따라서:
- **실행할 폴 포인트를 DB에 둔다**: `subscription.next_poll_at`
- 구독 생성/갱신 시 시각표에서 폴 포인트 목록(각 정차역 실효 도착시각 - [10, 4]분
  + **실효 출발시각 - 1분**, v27 → D-57)을 계산해 첫 포인트를 `next_poll_at`에 기록
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
- `next_poll_at` 도래 시 (정차역당 최대 3회 — -10/-4분 도착 + 출발 -1분, v27 → D-57):
  1. 매트릭스 재조회 — **60초 캐시를 우회하고 항상 실조회** (캐시는 화면 트래픽 전용 → D-17).
     조회 범위는 실효 시작~하차역 (5절, → D-18). 성공한 구간은 `seat_snapshot`에도 기록 (→ D-57)
  2. `Verdict` 계산 — 구독의 `status`(STANDING/SEATED)를 입력으로.
     판정 시작은 `sellable_seg_idx(stops, delay, now)` **시각표+지연 추정** 기준
     (위치 추정 `estimate_seg`와 다른 값이다 → D-47. GPS는 화면 전용 → D-13)
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
- **조회 빈도 원칙: 정차역당 2~3회 (+실패 재시도)** *(v27 개정 → D-57. 원문 "1~2회")*.
  비공식 API 자동화는 약관 회색지대다. 공격적 폴링 금지.

## 10. 프론트엔드 (PWA)

- React (Vite) + 바닐라 CSS, FastAPI `StaticFiles`로 서빙
- **프로토타입 완성본: `seat-matrix.jsx`** (레포에 포함) — 매트릭스 화면 확정
  - 상단: 열차 배지 + 노선 진행바 (현재 위치 펄스)
  - 판정 카드: 내 자리 상태 / 이동·착석 추천 / 지하철 환승 제안
  - 좌석 × 구간 매트릭스: **내 자리 최상단 고정**(착석 시, → D-49) → `clear_until` 내림차순,
    END 태그, "하차역까지 빈 좌석만" 필터, 지나온 구간 흐림 처리
  - **내 자리는 필터 대상이 아니다** (→ D-49). 필터를 켜는 상황이 곧 "내 자리가 팔려서 대안을
    찾는" 상황인데 내 자리는 `clear_all`이 아니므로 바로 그때 사라진다 — 비교 기준이 없어진다
  - **표시 범위는 내 구간(탑승~하차)뿐이다** — 매트릭스와 노선 진행바 양쪽.
    서버는 전체 노선 `stops`를 주지만(D-18) 그 밖은 조회하지 않아 셀이
    `UNQUERIED_CELL`로 채워져 있어서, 그리면 관측하지 않은 값이 관측값처럼 보인다 (→ D-31)
  - **구간 열은 너비가 모두 같다. 다 안 들어가면 줄이지 말고 가로로 스크롤한다** (→ D-52).
    좌석 열은 왼쪽에 고정하고, 넘칠 때는 넘친다고 글자로 말한다 —
    못 본 구간을 안 판 자리로 착각하면 판단 자체가 틀어진다
- 구현 시 변경점: 목업 상수(`STATIONS`, `SEATS`, `CURRENT_SEG`, `MY_DEST`)를
  `/matrix` 응답으로 대체
- **iOS 재디자인본이 따로 있다** (피그마, 11화면) — 적용은 **Phase 5**, 배경은 D-43.
  `seat-matrix.jsx`는 재디자인 후에도 **verdict 규칙의 참조 구현으로 남는다** (시각 디자인의
  참조가 아니다 — 그 구분을 D-43에 적어뒀다)

### 스킨 — web과 iOS를 둘 다 유지한다 *(v20 → D-50)*

접속 기기에 따라 한 번들 안에서 스킨을 고른다. **기준은 "iOS 기기냐 아니냐"다** —
아이폰·아이패드만 `ios`를 받고 **그 외 전부**가 `web`이다(맥·윈도우·리눅스 데스크탑,
**안드로이드 폰 포함**). `?ui=ios` / `?ui=web` / `?ui=auto`로 강제하며 `localStorage`에 고정된다.

> **폼팩터(모바일 vs 데스크탑)로 가르지 않는다.** `ios` 스킨은 "모바일"이 아니라 **iOS
> 관용구**(세이프 에어리어·홈 인디케이터·iOS 스위치·바텀시트)라, 안드로이드에 주면 크기는
> 맞고 관용구는 틀린 화면이 된다. 그리고 `web` 스킨은 `max-width: 480`이라 **480px가 곧 폰
> 폭**이다 — Phase 1~4 내내 아이폰에서 쓰던 그 화면이므로 안드로이드에서도 멀쩡하다.
> `pointer: coarse` + 폭으로 가르면 데스크탑 창을 좁힐 때 스킨이 튀는 부작용도 있다.
> **안드로이드를 실제로 쓰게 되면 `ios`에 얹을 게 아니라 `skins/android/`를 만든다.**

- **`core/`는 스킨을 모르고, 스킨은 서버 응답을 해석하지 않는다.** 판정 문구와 매트릭스 행
  순서는 `core/format.js`가 **문장 조각 배열**(`[{t, em}]`)로 돌려주고, 스킨은 강조를 어떻게
  그릴지만 정한다. 스킨이 각자 문장을 조립하면 두 벌이 갈리고, 그러면 뒤처진 쪽이 "못생긴"
  상태가 아니라 **"틀린 정보를 보여주는" 상태**가 된다 — D-43 결정 ③이 경고한 실패다
- `App.jsx`는 스킨을 모른다. 화면 5개(`Loading`/`ErrorScreen`/`Login`/`Setup`/`SeatMatrix`/
  `Settings`)를 스킨에서 받아 쓸 뿐이라, **iOS가 탑승 등록을 네 단계로 쪼개도 여기는 그대로다**
  — 하위 단계는 스킨 안의 상태다
- **web은 "동결"이 아니라 "기능 패리티 유지"다.** 동결이라 부르면 조용히 썩고, 정작 맥에서
  디버깅할 때 못 쓰게 된다. 배포 전 `?ui=web`으로 한 번 눈으로 본다
- `core/format.js`는 `web/test/format.smoke.mjs`가 분기별 문자열로 고정한다 (`npm run smoke`).
  프론트 자동 테스트가 0개인데 이 파일만은 **두 스킨이 같이 틀릴 수 있는 자리**라서 예외를 뒀다

### 탑승 상태 전이 UI (→ D-15)
- 탑승 등록 시 **입석/착석 선택**, 착석이면 좌석 지정
- 매트릭스에서 좌석 행 선택 → **"이 자리에 앉음" 버튼 하나**로 세 전이를 커버:
  - STANDING → SEATED (첫 착석)
  - SEATED → SEATED (자리 이동)
- **"일어남" 버튼** 별도 (SEATED → STANDING, 자리 뺏김/자발적 기립)
- 내부적으로 전부 `PATCH /api/subscriptions/{id}` 한 엔드포인트
- 옮기는 행위가 이 앱의 핵심 루프다 — **전이 입력이 없으면 이후 모든 알림이 이미 떠난 자리를 기준으로 울린다.** 알림 문구에도 갱신 유도 포함 (8절)

- 추가 화면: 로그인 / 프리셋 선택 / 열차 선택 /
  설정(코레일 연동, 알림 기기, 디스코드 웹훅 연동 + on/off 토글, 테스트 발송)
  - 코레일 연동은 **필요로 확정**됐다 — Phase 0 항목 1 = NO(비로그인 조회 불가)이므로
    연동 화면을 없앨 수 있는 갈래는 사라졌다 (D-14, D-22). Phase 2에서 구현 완료:
    미연결이면 아이디·비밀번호 폼, 연결됐으면 "연결됨" + 해제. 저장된 자격증명은
    API가 되돌려주지 않으므로 화면도 연결 여부만 안다 (절대규칙 9)

### 열차 선택 화면 — 역은 고르는 것이지 입력하는 것이 아니다 *(v9 → D-25)*
탑승 등록의 첫 화면이다. 코레일 앱과 같은 순서로 좁혀 들어간다:
1. **출발역 / 도착역을 목록에서 선택** — 자유 입력을 그대로 받지 않는다.
   오타가 곧 404이고, 사용자는 정식 역명(`서울역`인지 `서울`인지)을 모른다.
   소스는 `GET /api/stations` (→ 5절 station 테이블, D-25)
   - 여객역이 282개라 통짜 드롭다운으로는 못 고른다. **타이핑으로 목록을 좁히는
     콤보박스**(초성 검색 포함)를 쓰되, 확정되는 값은 언제나 목록에서 고른 역이다 (→ D-32)
2. **운행일 + 검색 기준 시각** — "오후 5시 이후 열차"처럼 **하한 시각**을 준다.
   통근은 "몇 시 차"가 아니라 "퇴근하고 탈 수 있는 차"를 고르는 일이다
3. **열차 목록에서 선택** — `GET /api/trains/search`. 열차명/번호 + 출발·도착 시각
4. 입석/착석 선택(착석이면 좌석 지정) → 구독 생성 → 매트릭스
- **1단계의 구간은 직전에 탄 구간으로 미리 채워져 있다** (v11 → D-37). 매일 같은 구간을
  타는데 "탑승 종료"마다 역을 다시 고르게 되던 것을 없앤다. 운행일·시각은 채우지 않는다
- 프리셋이 있으면 1~2단계를 건너뛴다 (자주 쓰는 구간 = 행 추가, 원칙 1·3).
  프론트는 "즐겨찾기 노선" 칩으로 붙었다 — 계정당 5개, 칩 탭 = 구간 채움 (v26 → D-56)
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
  → **2026-08-06 달성.** `ADAPTER=korail2`로 설정 화면에서 실 계정 연결 → 열차 검색 →
  구독 등록 → 좌석 매트릭스 렌더까지 브라우저에서 관통 확인. pytest 279 통과.

### Phase 3 — 알림 + 자동화
- `NotifierPort` + WebPush 어댑터(기본) + Discord 웹훅 어댑터(opt-in), `/api/push/test`
- APScheduler 폴링 — `next_poll_at` 포인터 + grace 2분 (재시작 내구성 → D-19)
- 해시 + 셀 스냅샷 이중 변화 감지, 우선순위 합성(폴링당 푸시 1건), 첫 폴링 베이스라인 (8절)
- 8절 5종 알림 구현 (상태별 분기 포함), 410/404 죽은 기기 정리
- PWA manifest/service worker/푸시 핸들러(딥링크 포함) + 오프라인 캐시
  (푸시 권한 요청은 설정 화면 버튼 탭에서만 — iOS 제약)
- ✅ 완료 기준: 탑승 등록 → 역 접근 시 자동 갱신 → [입석] 착석 가능 다이제스트 수신 /
  [착석] 내 자리 판매 시 폰에 알림 수신 → 앱에서 "이 자리에 앉음" → 이후 알림이 새 자리 기준으로 발송
  → **2026-08-06 코드 완료** (이슈 #8 / PR #11). pytest 349 통과, 프론트 빌드 성공.
  A~F 전부 구현: `NotifierPort`+웹푸시/디스코드, APScheduler 30초 틱, 폴링 사이클 배선,
  구독 자동 만료, `/api/push/*`+설정 UI, PWA(manifest/sw/딥링크/오프라인).

  **① 배달 경로 — 2026-08-06 실기기 검증 완료.** 아이폰(홈화면 설치 PWA)에서
  `POST /api/push/test` 수신 확인. 로컬 iMac을 `tailscale serve`로
  `https://imac.<tailnet>.ts.net → 127.0.0.1:8000` 프록시해 신뢰 HTTPS를 만들었다
  (12절이 배포용으로 적어둔 경로를 개발에 그대로 쓴 것). 이로써 VAPID → APNs →
  service worker → iOS 권한 흐름이 전부 살아있음이 확인됐다.
  도중에 막힌 지점 2개는 각각 D-34와 코드 수정으로 정리했다:
  `.env`를 고쳐도 재시작 전에는 반영되지 않는다(`get_settings`는 `lru_cache`,
  `--reload`는 `.py`만 감시), `VAPID_SUBJECT`는 **`mailto:` 스킴이 필수**다.

  **② 스케줄러 → 알림 경로는 아직 실기기 미검증.** 로직은 `now` 주입 테스트로
  잠갔지만, "역 접근 시 자동 갱신 → 알림 수신"을 실제 출근길에서 한 번 통과시켜야
  완료 기준이 닫힌다. 전제: `ADAPTER=korail2` + 활성 구독 + **맥이 깨어 있을 것**
  (잠들면 틱이 멈춘다 — Phase 4 배포가 필요한 실질적 이유가 이것이다).

  **③ 실사용 중 발견한 버그 1건은 별도 이슈로 처리했다** — 일부 구간만 매진일 때
  매트릭스 전체가 조회 실패로 떨어지던 것 (이슈 #9 / PR #10 / D-36). 스케줄러도 같은
  `fetch_matrix`를 쓰므로 **고치기 전에는 매진 구간이 낀 구독이 폴링마다
  `FETCH_FAILED`만 보냈다** — Phase 3 신뢰도와 직결돼 먼저 머지했다.

### Phase 4 — 배포 + 개선

**완료 기준 (착수 시 합의, 2026-08-06)**: EC2에서 서비스가 상시 동작하고 **실제 출근길에
폰으로 알림이 도착한다.** 배포와 Phase 3 완료 기준 마감이 이 Phase의 코어이고,
아래 개선 항목(2회 이동 조합 / 좌석 점유 이력 통계 / D-17 손잡이)은 **포함하지 않는다** —
설계가 문서에 없고 스키마·화면이 따라오므로 합의 후 별도 이슈로 간다.

- **A. 배포 산출물 — 코드 완료** (이슈 #17): `Dockerfile`(멀티스테이지·arm64) +
  `docker-compose.yml`(컨테이너 1개·루프백 퍼블리시·로그 로테이션) + `.dockerignore` +
  `DEPLOY.md`(12절 실행 절차서) + `scripts/deploy_check.sh`.
  **AWS 프로비저닝은 소유자가 직접 한다** (실 과금) → DEPLOY.md 1절
- **B. 스케줄러 → 알림 실기기 검증 — 미완**. Phase 3의 남은 완료 기준이다.
  A가 끝나 EC2가 24시간 깨어 있어야 비로소 가능하다 → DEPLOY.md 10절
- C. D-36 후속 — **코드값 확보·등재 완료** (배포 첫날 EC2 로그에서 `ERI411321` 관측 →
  `SOLD_OUT_CODES`에 등재, `tests/test_korail_sold_out.py`). 남은 것은 **스케줄러 레벨
  회귀 테스트**(부분 매진 구독이 `FETCH_FAILED` 대신 정상 알림을 내는지) — 별도 이슈
- D. 관리자 복구 수단 (아래 항목, D-24 후속) — 방식 미확정, 합의 후 별도 이슈
- **F. 퇴근길이 드러낸 판정 문제 — 완료** (이슈 #30/#34, → D-45/D-46).
  매진 오판정(잘못된 환승 권유 + `ALL_SOLD` 오발송) 수정 + 지연 착석 추천 신설.
  **출근길만 검증한 로직이 반대 방향에서 틀렸다** — 방향이 뒤집히면 데이터 모양도 뒤집힌다
- **E. CI — 완료** (이슈 #21, → D-44). `.github/workflows/ci.yml`: 테스트 / 네이티브
  arm64 이미지 빌드 + 스모크 / 시크릿 검사. **배포는 하지 않는다** — CD는 별도 이슈 #22.
  이미지 쪽 불변식(arm64·KST·uid 1000·healthz·스케줄러 기동 로그)을 CI가 잡고,
  호스트 쪽은 `scripts/deploy_check.sh`가 잡는다 — 둘이 짝이다
- **G. CD — 완료** (이슈 #22, → D-51). `.github/workflows/cd.yml`: `main` 푸시에서
  CI를 게이트로 부르고, 통과하면 `tag:ci` 임시 노드로 tailnet에 붙어 손으로 하던
  `docker save | ssh docker load`를 대신 친다. **레지스트리는 여전히 쓰지 않는다**(D-40 유지).
  재배포 가드는 시각이 아니라 `next_poll_at`을 보고(`scripts/deploy_guard.py`),
  `deploy_check.sh`가 실패하면 이미지와 작업 트리를 함께 되돌린다
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

  > **여전히 미해결이다** (2026-08-07). D-53으로 **일반 사용자**의 목록 조회·삭제가 앱에
  > 들어왔지만 그건 관리자만 부를 수 있으므로 **관리자 계정 자체를 잃는 경우는 그대로 남는다.**
  > 위 후보 2개도 그대로다. 다만 D-53이 "CLI가 권장"이라는 판단을 한 번 뒤집었으므로
  > (실사용에서 폰 접근성이 이겼다) 이 항목을 정할 때 그 선례를 함께 볼 것.
- **가입 토글 자동 재잠금** (→ D-53 범위 밖으로 명시). 원치 않는 가입의 **원인**은 "지우는
  수단이 없다"가 아니라 "열어둔 것을 잊는다"다. 열면 N분 뒤 자동으로 잠기게 하면 사후
  삭제가 필요할 일이 거의 사라진다. 값(N)과 UI 표시 방식이 미정이라 별도 이슈로 간다

### Phase 5 — iOS 재디자인 (프론트 전면)

**착수 조건**: Phase 4 B(출근길 실기기 검증)가 닫힌 뒤. 진행 중인 화면을 갈아엎으면
검증 실패의 원인이 배포인지 디자인인지 분리되지 않는다.

별 세션에서 피그마 MCP로 만든 **iOS 전용 재디자인본**을 적용한다 (iPhone 14 Pro
393×852pt 기준, 11화면 + iOS 심볼 세트). 파일: `ITX-Matrix-web`, 페이지 `ios`
(node `19:2`). 배경·미정 항목은 **D-43**.

> **피그마는 D-45~D-48까지 동기화돼 있다** *(이슈 #42)*. Phase 4 실사용으로 판정이
> 네 번 바뀌었고 그 네 건이 전부 화면 문구와 셀 상태를 바꾼다. 재디자인본이 그 앞에 멈춰
> 있으면 **"디자인대로 그렸는데 판정이 틀린" 결과**가 나온다 — D-43 결정 ③이 경고한 실패다.
> 심볼 2개가 이때 늘었다: **`iOS/Chip-Later`**(지연 착석의 "언제부터", → D-46 결정 ③)와
> **`iOS/Cell-Failed`**(조회 실패 구간 `?`, → D-48). 색은 `SeatMatrix.jsx`의 실제 값이다.

**전제: 백엔드 무변경.** 11화면이 기존 7개 컴포넌트와 1:1로 대응하고 새 API 표면이 없다.
`/matrix` 스키마(7절)를 건드리게 되는 순간 그건 이 Phase의 범위가 아니라 별도 합의 사항이다.

| 피그마 화면 | 현재 파일 |
|---|---|
**적용 대상은 `web/src/skins/ios/`다** (→ D-50). web 스킨은 남는다 — 아래 표는 "무엇을 보고
무엇을 만드는가"이지 "무엇을 갈아엎는가"가 아니다. 채우지 않은 화면은 web으로 폴백하므로
**화면 하나씩 켤 수 있다.**

| 피그마 화면 | 참고할 web 스킨 파일 | 만들 파일 |
|---|---|---|
| 01 로그인 | `skins/web/Login.jsx` | `skins/ios/Login.jsx` |
| 02 탑승 등록 / 04 열차 선택 | `skins/web/Setup.jsx` | `skins/ios/Setup.jsx` |
| 03 역 검색 (모달 시트) | `skins/web/StationPicker.jsx` | 〃 (Setup 내부 단계) |
| 05 지금 상태 (바텀시트) | `skins/web/Setup.jsx` | 〃 (Setup 내부 단계) |
| 06·07 매트릭스 / 08 오프라인 / 09 조회 실패 | `skins/web/SeatMatrix.jsx` | `skins/ios/SeatMatrix.jsx` |
| 10·11 설정 | `skins/web/Settings.jsx` | `skins/ios/Settings.jsx` |

> iOS는 탑승 등록을 `02 → 03 → 04 → 05` 네 단계로 쪼갠다. 그 하위 단계는 **`Setup` 안의
> 상태다** — 공유 라우팅(`App.jsx`)의 `phase`는 5개 그대로다 (→ D-50).

**06·07·08의 판정 표시는 두 그룹으로 갈린다** (→ D-46). 이 세 화면만 다른 화면과 성질이
다르다 — 나머지는 레이아웃 이식이지만 이쪽은 **도메인 규칙의 시각화**다.

- 응답에 `move_to`(지금)와 `move_to_later`(몇 정거장 뒤부터)가 **둘 다** 온다. 합치지 않는다
- 좌석 라벨에 `clear_from_idx`("언제부터")를 **반드시** 붙인다 — 빠지면 지금 앉을 수 있다고
  오해하고, 그건 추천을 안 하느니만 못하다 (D-46 결정 ③)
- 지연 목록 접두어는 `move_to`가 비었는지로 갈린다: 있으면 `지금은 아니지만 뒤 구간에 빈 자리`,
  비었으면 `빈 자리`. 착석 상태에서 옮길 곳이 없으면 `지금 옮길 자리는 없음 · {역}부터 …`
- 문구의 기준역은 `stops[start]`다. 한 역 뒤를 가리키면 그 역에서 앉을 기회를 놓친다 (D-47)
- 환승 권유는 `all_sold_after_current`일 때만. `clear_until`로 판정하면 안 된다 (D-45)
- `decision_needed = false`면 매트릭스를 그리지 않는다. 빈 표는 "전부 매진"으로 읽힌다 (D-47)
- 실패한 구간은 `iOS/Cell-Failed`(`?`)로 그린다. 매진과 **색만으로** 구분하지 않는다 (D-48)

규칙과 문구 분기는 피그마 `31:200`(iOS 설계 규칙) 아래쪽 **"판정 표시"** 섹션에 정리해 뒀다.
**부분 실패(`failed_seg_idxs`) 화면은 아직 피그마에 없다** — 06의 변형으로 이 Phase에서 그린다.

**진행**: **11화면 모두 `skins/ios/`로 채웠다** (이슈 #25). 폴백 중인 화면은 없다.
`...web` 전개는 그대로 둔다 — 앞으로 web에 화면이 추가되면 iOS가 비는 것보다 폴백되는 편이
낫고, `skins/ios/index.js`가 "무엇이 iOS로 덮였는지"의 목록 역할을 한다.
**실기기 확인에서 6건이 나왔고 고쳤다** (이슈 #48 → D-52): 매트릭스 구간 열 정렬, 좌석 선택
액션 바 위치, 네 글자 역 이름, 스크롤 중 내비바, 진행바 역 이름 겹침, 그리고 **레이아웃이
아니라 문구였던 한 건** — 지금 팔린 좌석에 "…까지 빈 좌석"을 찍어 판정 카드와 다른 말을
하고 있었다. **여섯 건 다 정차역이 많은 노선에서만 드러났다** — 나머지 화면은 이상 없었다.

**화면마다 눈으로 확인한다 — 폰이 없으면 `web/preview.html`로 본다.** 백엔드 없이 스킨 화면
하나만 렌더하는 개발 전용 하네스다 (`npm run dev` → `/preview.html?screen=Login`).
빌드 산출물에는 들어가지 않는다(vite 엔트리는 `index.html`뿐). 실기기 확인을 대체하지는
못하지만, **배포를 기다리는 동안 레이아웃이 깨진 채로 쌓이는 것**은 막는다.

**적용 순서 — 위험이 낮은 것부터.** 01 로그인 → 10·11 설정 → 02·03·04 → **06·07 매트릭스는
마지막.** 매트릭스는 도메인 규칙(5절 verdict)의 시각화라 잘못 그리면 조용히 틀리고,
로그인·설정은 도메인과 독립이라 되돌리기 쉽다. 각 단계마다 폰에서 눈으로 확인한다 —
프론트 자동 테스트가 0개이므로 안전망은 "빌드가 되는가"와 사람의 눈뿐이다.

**배포 시 `web/public/sw.js`의 `CACHE` 버전을 올린다** (D-46에서 `v2`, D-49에서 `v3`,
D-50에서 `v4`, Phase 5에서 `v5`·`v6`까지 올라갔다 — **화면을 켤 때마다 올린다**).
올리지 않으면
iOS 홈화면 PWA가 앱을 완전히 종료할 때까지 옛 화면을 계속 보여줘서, "재배포했는데 안 바뀐다"로
시간을 버린다. 확인할 때도 앱을 스와이프로 완전히 종료한 뒤 다시 연다.

✅ **완료 기준**: 11화면이 폰에서 재디자인대로 보이고, **매트릭스의 판정 표시가 5절 규칙과
일치하며**(입석/착석 양쪽 + 내 좌석 부재 규칙 + **두 목록이 분리돼 있고 좌석마다 "언제부터"가
붙어 있는지**), `uv run pytest`와 프론트 빌드가 통과한다.

> 미착수로 남은 다른 개선 항목(2회 이동 조합 추천 / 좌석 점유 이력 통계 / 관리자 복구 수단 /
> D-17 손잡이 조정)과의 **선후 관계는 미정이다** — 소유자가 정한다. 이 절은 "재디자인을 할 때
> 무엇을 지켜야 하는가"만 확정한 것이다.

## 12. 배포 상세 (AWS EC2)

> **실행 절차서는 `DEPLOY.md`다** (Phase 4에서 작성). 이 절은 "무엇을/왜"이고,
> DEPLOY.md는 "어떤 순서로"다 — 콘솔 화면 값, 명령어, 실패 시 볼 로그까지 그쪽에 있다.

### 인스턴스
- **t4g.nano (ARM/Graviton), ap-northeast-2(서울)**, EBS gp3 10GB
- 온디맨드 월 5,500원 안팎, 1년 Savings Plan 시 3~4천원대
- ※ 2026년 5월 기준 개략치. 요금·환율은 콘솔에서 재확인할 것
- **평일 06:00~24:00만 가동한다** — 주말·심야는 자동 정지 (→ D-54).
  기동은 EventBridge Scheduler, **정지 판단은 박스 안의 가드**가 한다.
  **EBS는 정지 중에도 과금되므로** 줄어드는 것은 컴퓨트뿐이다

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
- [ ] **`SECRET_KEY`는 로컬에서 쓰던 값을 그대로 옮긴다.** DB만 옮기고 키를 새로 만들면
      `korail_pw_enc`·디스코드 웹훅 복호화가 전부 깨진다 (→ D-35). 조용히 죽지는 않고
      `FETCH_FAILED`가 1회 나가며 화면의 "연결됨" 표시가 꺼진다
- [ ] **VAPID 키쌍도 그대로 옮긴다.** 바꾸면 기존 `push_device` 등록이 전부 무효가 되어
      기기마다 알림을 다시 켜야 한다 (→ D-34). `VAPID_SUBJECT`는 `mailto:` 스킴 필수
- [ ] `.env`의 `KORAIL_ID`/`KORAIL_PW`는 **옮기지 않는다** —
      `scripts/phase0_feasibility.py` 전용 잔재이고 앱은 읽지 않는다 (→ D-35)
- [ ] `.gitignore`에 `.env`, `*.db` 확인
- [ ] **`ADAPTER=korail2` / `COOKIE_SECURE=true` / `LOG_LEVEL=INFO`** — 세 값 다 기본값이
      개발용이다. `mock`이면 가짜 좌석으로 알림이 오고, `LOG_LEVEL`이 INFO가 아니면
      폴링 틱 로그가 사라져 **스케줄러가 도는지 확인할 방법이 없어진다** (→ D-39)
- [ ] **`data/`를 uid 1000 소유로 먼저 만든다.** 컨테이너는 비루트(uid 1000 = 우분투 기본 사용자 `ubuntu`)로
      돈다. 디렉터리가 없으면 docker가 root 소유로 만들고 SQLite가 쓰기에서 죽는다

### 빌드 호스트와 이미지 전송 *(Phase 4 → D-40)*

**ARM64 이미지는 "빌드 옵션"이 아니라 "빌드 머신"의 문제다.** 개발기가 Intel 맥이므로
거기서 빌드하면 x86 이미지가 나오고 t4g에서 `exec format error`로 죽는다.
`--platform linux/arm64`로 강제하면 QEMU 에뮬레이션이 붙어 `npm ci`·vite 빌드가 몇 배로 느려진다.

- **Apple Silicon 맥에서 빌드한다** (네이티브 arm64). Intel 개발기는 개발 전용으로 남긴다
- **레지스트리를 쓰지 않는다.** `docker save | gzip | ssh … docker load`로 tailnet 위로 밀어 넣는다 —
  ECR 과금·자격증명 관리가 없고, 인바운드 0개 전제와도 맞는다
- 인스턴스에서 직접 빌드하는 경로는 폴백으로만 둔다 (0.5GB RAM에서 node 빌드 = 스왑 의존 + T 크레딧 소모)

### 데이터 이관 — **DB는 WAL이다** *(Phase 4 → D-41)*

`data/itx.db`만 복사하면 **최근 커밋이 조용히 사라진다.** `journal_mode = WAL`이라
가장 최근 쓰기가 아직 `itx.db-wal`에 있고, `itx.db` 단독으로도 파일은 정상적으로 열린다 —
앱이 잘 뜨는데 **방금 등록한 코레일 자격증명이나 푸시 기기만 없는** 상태가 된다.

- **`.backup`(SQLite 온라인 백업 API)으로 단일 일관 스냅샷을 만들어 옮긴다.**
  `sqlite3 data/itx.db ".backup '/tmp/out.db'"` 또는 `sqlite3.Connection.backup`
- station·train_stop 캐시도 이 파일에 함께 온다 — 소스 CSV는 `data/`가 gitignore라
  저장소에 없으므로 **DB를 옮기는 편이 스크립트 재적재보다 확실하다**
- 같은 이유로 **백업도 파일 복사가 아니라 `.backup`이다** (운영 중 스냅샷)

### 접근 경로 설정 (Tailscale) — 순서를 뒤집으면 스스로 잠긴다

Tailscale은 **EC2 호스트에** 설치한다. 컨테이너 사이드카가 아니다 — `tailscale serve`가
호스트에서 `443 → 127.0.0.1:8000`을 프록시해야 하고, 22번을 닫으려면 Tailscale SSH가
먼저 살아 있어야 한다. 앱 컨테이너는 `127.0.0.1:8000`만 바인딩하면 된다 (`0.0.0.0` 불필요).

1. 보안그룹 22번을 **아직 열어둔 채로** SSH 접속 → `curl -fsSL https://tailscale.com/install.sh | sh`
2. `sudo tailscale up --ssh --hostname=itx`
   (비대화형은 `--authkey=tskey-auth-...`. **auth key는 시크릿 — `.env`·커밋 금지, 1회 쓰고 버린다**)
3. `sudo tailscale serve --bg 8000` → `https://itx.<tailnet>.ts.net`. `tailscale serve status`로 확인
4. **다른 기기에서 Tailscale SSH 접속이 되는 것을 확인한 뒤에** 22번 인바운드를 닫는다

- [ ] **MagicDNS + HTTPS Certificates 둘 다 켠다** (admin 콘솔). 안 켜면 `*.ts.net` 신뢰
      인증서가 안 나오고, 자체서명으로는 PWA 홈화면 추가·웹푸시가 동작하지 않는다 (→ D-8)
- [ ] **이 노드의 key expiry 비활성화** — 기본값은 180일 후 재인증이다. 걸려 있으면
      **반년 뒤 어느 날 조용히 접근이 끊기고 스케줄러 알림도 함께 멈춘다**
- [ ] 인바운드 전부 차단이어도 붙는다 (NAT traversal 실패 시 DERP 릴레이 경유).
      직접 연결을 원하면 UDP 41641만 열면 되지만, 개인용 조회 도구에는 릴레이로 충분
- [ ] 첫 재부팅 후 `tailscale serve status`를 한 번 확인. `tailscaled`는 systemd로 자동
      시작되고 serve 설정도 상태에 저장되지만, 눈으로 확인해 두는 편이 싸다

폰은 같은 tailnet에 로그인만 되어 있으면 된다. LTE에서도 붙는다 (→ D-8).
**접속 주소가 바뀌면 PWA를 다시 홈 화면에 추가하고 알림도 다시 켜야 한다** —
푸시 구독은 오리진 단위이며, VAPID 키를 그대로 옮기는 것과는 별개 문제다 (→ D-34).

### 접근 경로 — Phase 4 배포 시점 최종 확정: **A 유지** *(2026-08-06)*

D-38이 "배포 시점에 한 번에 결정"으로 남겨둔 항목을 **A(Tailscale serve) 유지**로 확정했다.
커스텀 도메인 계획이 없으므로 푸시 재등록을 두 번 할 이유가 없다.

**그래도 재등록은 한 번 필요하다.** 개발 중 폰이 보던 주소는 개발기의 `serve`
(`https://imac.<tailnet>.ts.net`)이고 배포 주소는 `https://itx.<tailnet>.ts.net`이다.
**푸시 구독은 오리진 단위**라 기존 `push_device` 행은 새 주소에서 쓸 수 없다 —
VAPID 키를 그대로 옮기는 것과는 별개 문제다 (→ D-34). 홈 화면 재추가 + 알림 재등록 1회.

### 접근 경로 대안 (지금은 채택하지 않음 → D-38)

Tailscale 방식의 유일한 비용은 **접근할 기기마다 Tailscale 설치 + tailnet 참여**다.
지인에게 열어줄 때 앱 가입(D-24) 위에 tailnet 초대가 하나 더 붙는다.
그게 부담이 되는 시점에 **Cloudflare Tunnel + Access**로 전환한다 —
인바운드 포트 0개와 단일 오리진을 유지하므로 앱 코드는 `cookie_secure=true` 하나만 바뀐다.
Vercel을 배제한 이유와 전환 트리거는 D-38에 있다. **지금은 현행(Tailscale)을 유지한다.**

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
| `scripts/secret_scan.py` | 필수 (막을 것 / **통과시킬 것** 양쪽) | 훅과 CI가 공유하는 규칙(D-33·D-44). 느슨해지면 `--no-verify`가 습관이 되고 그게 훅이 죽는 실제 경로다 |

바이브코딩으로 진행하더라도 위 표의 "필수" 세 줄만은 테스트를 붙인다. (→ D-5)

**CI가 매 푸시에서 이 테스트를 돌린다** (D-44). 로컬 `uv run pytest`가 여전히 완료 선언의
전제이고, CI는 "돌리는 것을 잊었을 때"의 그물이다 — 순서가 바뀌면 안 된다.

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
├── DEPLOY.md                 # 배포 실행 절차서 (12절의 실행편, Phase 4)
├── pyproject.toml            # uv
├── docker-compose.yml        # 컨테이너 1개 고정 (→ D-17)
├── Dockerfile                # 멀티스테이지 (web 빌드 → deps → runtime), arm64
├── .dockerignore             # .env·*.db가 이미지 레이어에 박히는 것을 막는다
├── .env.example
├── .github/
│   └── workflows/
│       ├── ci.yml            # 테스트 / arm64 빌드+스모크 / 시크릿 검사 (→ D-44)
│       └── cd.yml            # main 푸시 → CI 게이트 → EC2 배포 + 자동 롤백 (→ D-51)
├── scripts/
│   ├── phase0_feasibility.py # Phase 0 일회성 검증 스크립트
│   ├── load_train_stops.py   # 정차역 캐시 적재 (D-29)
│   ├── gen_vapid.py          # VAPID 키페어 생성 (일회성, → D-34)
│   ├── gen_icons.py          # PWA 아이콘 생성 (일회성)
│   ├── deploy_check.sh       # 배포 상태 점검 (12절 체크리스트, 호스트에서 실행).
│   │                         #   ✗가 있으면 종료 코드 1 — CD의 롤백 판정이다 (→ D-51)
│   ├── deploy_guard.py       # 재배포 가드 — 임박한 폴 포인트가 있으면 배포 보류 (→ D-51).
│   │                         #   호스트에서 stdin으로 실행되므로 표준 라이브러리만 쓴다
│   ├── env_fingerprint.sh    # `.env` 시크릿 지문 대조 — 값 노출 없이 (→ D-35, DEPLOY.md 4절)
│   ├── secret_scan.py        # ★ 시크릿 검사 **규칙** — 훅과 CI가 공유한다 (D-33, D-44)
│   └── hooks/pre-commit      # 위 규칙을 "스테이지된 것"에 적용하는 얇은 껍데기
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── auth.py
│   │   ├── admin.py          # 가입 허용 토글 (D-24) + 사용자 목록/삭제 (D-53)
│   │   ├── me.py             # 코레일 자격증명 + 디스코드 웹훅
│   │   ├── stations.py
│   │   ├── trains.py         # ★ /matrix
│   │   ├── presets.py
│   │   ├── subscriptions.py  # CRUD + PATCH 상태 전이
│   │   └── push.py           # 기기 등록 + VAPID 공개키 + 테스트 발송
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
│   │   ├── korail_client.py      # korail2 래핑 + DynaPath 우회 (D-22)
│   │   ├── korail_dynapath.py
│   │   ├── seatmap_fetcher.py    # 구간 병렬 조회 + 재시도 (화면/스케줄러 공용)
│   │   ├── delay_port.py
│   │   ├── delay_zero.py         # 기본: 항상 None (지연 0 간주)
│   │   ├── notifier_port.py      # Port + Notification/NotifyTargets/CompositeNotifier
│   │   ├── webpush_notifier.py   # 기본 채널. 410/404 → 죽은 기기 보고 (D-20)
│   │   ├── discord_notifier.py   # 보조 채널 (웹훅, opt-in 2단계)
│   │   └── notify.py             # 채널 조립 + 대상 적재 + 죽은 기기 정리
│   ├── scheduler/
│   │   ├── poller.py             # ★ 폴링 사이클 (전부 now 주입 — 테스트 대상)
│   │   └── service.py            # APScheduler 수명주기. 실제 시계를 읽는 유일한 지점
│   └── storage/
│       ├── db.py
│       ├── creds.py              # Fernet — 코레일 비밀번호 + 디스코드 웹훅
│       ├── push.py               # push_device (endpoint UPSERT + 죽은 기기 삭제)
│       ├── stations.py
│       ├── train_stops.py
│       ├── matrix_cache.py       # 60초 TTL, 화면 전용 (D-17)
│       └── migrations/
├── tests/
│   ├── test_verdict.py       # ★ 핵심
│   ├── test_matrix.py
│   ├── test_alerts.py        # ★ 핵심 — 13절 케이스 5종 필수
│   ├── test_scheduler.py     # ★ 핵심 — 배선 5종 (침묵/베이스라인/1건/멱등)
│   ├── test_push_api.py      # 기기 등록 + 디스코드 opt-in 2단계
│   ├── test_geo.py
│   ├── test_timeline.py      # 구간 추정 + 폴 포인터/grace
│   ├── test_secret_scan.py   # 시크릿 검사 규칙 (D-44)
│   ├── test_deploy_guard.py  # 재배포 가드 — 막아야 할 때/막지 말아야 할 때 (D-51)
│   └── test_admin_users.py   # 사용자 삭제 — 거절해야 할 때 거절하는지가 코어 (D-53)
└── web/                      # Vite + React
    ├── public/               # Vite가 해시 없이 그대로 복사한다
    │   ├── manifest.webmanifest
    │   ├── sw.js             # 푸시 수신 + 딥링크 + 오프라인 셸 (/api는 캐시 금지)
    │   └── icon-*.png        # scripts/gen_icons.py 생성
    ├── test/
    │   └── format.smoke.mjs  # core/format.js 분기 고정 (`npm run smoke`, 의존성 없음)
    ├── preview.html          # 개발 전용 화면 프리뷰 — 빌드에 포함되지 않는다 (vite 엔트리는 index.html뿐)
    └── src/                  # 3층: 라우팅 / core / 스킨 (→ D-50)
        ├── App.jsx           # 라우팅·세션·딥링크. **스킨을 모른다**
        ├── core/             # ★ 기능 개선은 여기서 끝난다 (스킨 무관)
        │   ├── api.js  hangul.js
        │   ├── admin.js      # 삭제 가능 판정 — 두 스킨이 갈리지 않게 한 벌만 (D-53)
        │   ├── push.js       # 구독. 권한 요청은 버튼 탭 핸들러에서만 (D-21)
        │   ├── format.js     # ★ 판정 문구·행 순서. 두 스킨의 유일한 원천
        │   └── skin.js       # UA 판별 + `?ui=` 강제 + localStorage 고정
        ├── preview.jsx       # 개발 전용. 백엔드 없이 스킨 화면 하나만 렌더한다
        └── skins/
            ├── web/          # 480px. 맥 기본값이자 디버깅 경로 (기능 패리티 유지)
            │   ├── SeatMatrix.jsx  Login.jsx  Settings.jsx
            │   ├── Setup.jsx  StationPicker.jsx  Boot.jsx
            │   └── styles.js       # 스킨마다 따로 갖는다
            └── ios/          # 393pt. Phase 5에서 화면 단위로 채운다 (미채움분은 web 폴백)
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

### Phase 2 이어받기 *(2026-08-05 중단 지점 → **2026-08-06 완료**. 기록으로 남긴다)*

> 아래 블록의 "남은 일"은 전부 끝났다. 실조회 검증 중 발견해 고친 것:
> ① 계정 미연결/정차역 캐시 미스가 500으로 새던 것 → 409/404 매핑 (3f2c10d)
> ② 코레일 연결 UI 부재 → 설정 화면에 연결/해제 추가 (ce97e01)
> ③ 조회 실패 화면이 막다른 골목 → 설정/다른 열차 탈출구 (98c9c34)
>
> 남은 관찰: 지난 날짜 구독이 계속 활성으로 남는다. PLAN 9절의
> "하차역 실효 도착시각 경과 시 `active = false`"를 실행할 스케줄러가 Phase 3이기
> 때문이다. Phase 3에서 자동 해소되므로 앞당겨 구현하지 않았다.

```
PLAN.md 11절 Phase 2(코레일 실연동)를 이어서 한다. **코드는 A~G 전부 구현됐고,
남은 건 실조회 검증 하나다.** 상태:

- 이슈 #5(OPEN), 브랜치 feat/korail-integration. dev 대비 18커밋, **원격 브랜치 없음 = 전부 미푸시**.
  Phase 1 PR도 아직 dev에 안 갔다. 푸시·머지는 내가 한다.
- pytest 279 통과. 마지막 커밋 3f2c10d(실조회 중 발견한 500 누출 수정).
- 항목 A~G 완료, 결정 이력 D-26~D-30 기록됨. 16절 Phase 2 블록의 "열린 항목"(5절 부호 오기)은
  D-26으로 해소됐다.
- .env: ADAPTER=korail2, SECRET_KEY 채워짐, DATA_GO_KR_SERVICE_KEY 있음.
- 개발 DB(data/itx.db): station 1235행(usable 282), train_stop 920개 열차/10060행,
  user 1, subscription 2. **korail 계정 연결 0 = 이게 유일한 블로커다.**

## 남은 일 (완료 기준 그 자체)

1. **코레일 계정 연결.** 설정 화면에 연결 폼이 있다(ce97e01) — curl 불필요.
   저장 시점에는 코레일을 호출하지 않으므로, 자격증명이 틀렸다면 2번에서 드러난다.
2. 서버 기동(ADAPTER=korail2) 후 실조회 성공 확인. 호출은 최소 횟수만.
   - 캐시에 있고 통근 노선(천안→평택→수원→안양→영등포→서울)을 그대로 지나는 열차 = **1160번**.
   - **먼저 GET /api/trains/search로 그 번호가 오늘 실제로 도는지 확인해라** — D-29의 번호 개정
     리스크 때문에 캐시된 번호가 이미 폐기됐을 수 있다. 없으면 검색 결과의 번호로 바꿔 진행하되,
     그 번호가 train_stop 캐시에 없으면 404가 정상 동작이다(scripts/load_train_stops.py 재적재).
   - GPS 보정까지 보려면 lat/lng/gps_accuracy_m/gps_fixed_at_ms 4개를 다 넘긴다
     (일부만 오면 무시가 정상, D-30). position_source="gps"가 나와야 성공.
3. 검증 끝나면 **.env를 ADAPTER=mock으로 되돌린다** (평소 개발은 Mock, CLAUDE.md 10).
4. 그 다음 PR: .github/PullRequestTemplate.md, base dev, 제목 "[#5] Phase 2 코레일 실연동",
   본문에 Closes #5. 푸시·머지는 내가 한다.

## 실조회에서 터질 만한 것 (에러 → 원인)

- 409 → 코레일 계정 미연결 (위 1번)
- 404 + "정차역이 캐시에 없다" → 번호 개정 or 미적재 열차 (D-29)
- MACRO ERROR → DynaPath 우회가 깨졌다. 고정 커밋 4b13426의 알고리즘이 코레일 쪽 변경으로
  무효화된 경우다. **여기서 멈추고 보고해라** — 우회 재분석은 내 승인이 필요하다.
- 500 → 남은 에러 매핑 누락이다. 3f2c10d에서 CredentialsRequired/TrainStopsNotCached는 잡았지만
  다른 경로가 있을 수 있다.

## 지킬 것 (Phase 2 블록과 동일 — 재확인)

- 실 코레일 API를 루프로 때리지 마라. 개발·디버깅은 ADAPTER=mock.
- 실 자격증명·우회 코드를 건드리는 스크립트는 네가 실행하지 말고 명령만 알려줘라.
- 개발 DB(data/itx.db)를 삭제·초기화하지 마라. 내 계정이 들었고 가입이 잠겨 복구가 번거롭다.
- 시크릿은 .env에만. **커밋 전 .env.example diff를 반드시 확인해라** — 실 키가 새어든 사고가 2회 있었다.
- Phase 3 영역(NotifierPort/웹푸시/디스코드/APScheduler 폴링/PWA service worker)은 만들지 않는다.
```

### Phase 3 — 알림 + 자동화 *(2026-08-06 코드 완료. 기록으로 남긴다)*

> A~F 전부 구현됐다 (이슈 #8 / PR #11). 아래 블록에서 어긋난 것 두 가지:
> ① 착수 전 확인 항목("PR #6이 dev에, dev가 main에")은 둘 다 머지된 것으로 확인됐다.
> ② "이미 있는 것 — 다시 만들지 마라"는 그대로 유효했다. 판정 로직은 손대지 않았고
>   `app/scheduler/`를 채우는 것이 실제 작업이었다.
>
> 진행 중 문서가 침묵한 4개 지점 → **D-34**. 실사용 질문 하나 → **D-35**.
> 실사용 중 발견한 버그 하나는 별도 이슈로 분리 → **D-36**(이슈 #9 / PR #10).
> **남은 완료 기준은 실기기 스케줄러 경로 검증 하나뿐이다** (11절 Phase 3 ②).

```
PLAN.md 11절 Phase 3(알림 + 자동화)를 시작한다.
Phase 2는 완료됐다 — 이슈 #5, PR #6, ADAPTER=korail2로 실제 매트릭스 조회 성공, pytest 279 통과.

착수 전:
1. PR #6이 dev에, dev가 main에 머지됐는지 확인해라. 안 됐으면 알려줘 — 머지는 내가 한다.
2. feature 템플릿으로 새 이슈를 발급하고 dev에서 feat/<이름>으로 분기해라.
   커밋만 하고 push는 내가 한다. 커밋 전 .env.example diff 확인은 pre-commit 훅이 대신한다 (D-33).

## 이미 있는 것 — 다시 만들지 마라

**판정 로직은 Phase 1에서 이미 끝났고 테스트도 통과한다.** Phase 3의 일은
"무엇을 보낼지 결정하는 것"이 아니라 **그 결정을 스케줄러와 전송에 배선하는 것**이다:
- `domain/alerts.py` — `evaluate()`(5종 판정 + 우선순위 합성 + 첫 폴링 베이스라인),
  `verdict_hash()`, `count_extensions()`, `AlertConfig`. 테스트 15개 통과
- `domain/timeline.py` — `compute_poll_points()`, `first_poll_at()`, `resolve_poll()`(grace 2분),
  `is_ride_over()`
- `adapters/seatmap_fetcher.py` — `fetch_matrix(cache=None, retry=SCHEDULER_RETRY)`가 스케줄러 경로다.
  **cache를 넘기지 마라** — 캐시된 값으로 판정하면 상태 변화를 놓쳐 알림이 조용히 안 온다 (D-17).
  이걸 지키는 회귀 테스트가 이미 있다
- `subscription.next_poll_at` 컬럼, `last_verdict_hash`, `last_cells_snapshot` 컬럼

`app/scheduler/`는 __init__.py만 있는 빈 패키지다. 여기가 이번 작업의 중심이다.

## 착수 순서 (앞이 뒤의 전제다)

A. **NotifierPort + 저장소.** `push_device` 테이블 신설(마이그레이션 006).
   WebPushNotifier(기본, 항상 발송) + DiscordNotifier(웹훅, 연동+토글 둘 다 켰을 때만, D-11).
   웹훅 URL은 사실상 자격증명이므로 Fernet 암호화 + API 미노출 (절대규칙 9, storage/creds.py 재사용).
   410/404 응답이면 죽은 기기로 보고 삭제한다 — iOS는 endpoint를 조용히 회전시킨다 (D-20).
B. **스케줄러 루프.** APScheduler 30초 틱. 하는 일은 하나다:
   `next_poll_at <= now`인 활성 구독을 실행하고 포인터를 다음 포인트로 전진 (D-19).
   `resolve_poll()`이 grace 2분 판정과 전진을 이미 해준다 — 시각 계산을 새로 짜지 마라.
   **uvicorn --workers 1 고정** (2개면 알림이 중복 발사된다).
C. **폴링 사이클 배선.** 조회 → `evaluate()` → 발송 → `last_verdict_hash`/`last_cells_snapshot` 기록.
   **이 컬럼들을 쓰는 것은 스케줄러뿐이다** (절대규칙 5, D-13/D-17). /matrix는 지금도 안 건드린다.
   조회 3회 실패 시 FETCH_FAILED 1회 발송 후 그 시점 포기하고 포인터 전진 (D-17).
D. **구독 자동 만료.** 하차역 실효 도착시각 경과 시 active = false (9절).
   `is_ride_over()`가 있다. **Phase 2에서 이게 없어 지난 날짜 구독이 계속 살아났다** —
   프론트의 "다른 열차" 탈출구는 임시방편이었고 여기서 제대로 닫힌다.
E. **/api/push/test** + 설정 화면의 알림 기기 등록 UI.
   **푸시 권한 요청은 버튼 탭 핸들러 안에서만** — 페이지 로드 시 자동 요청은 iOS에서 조용히 실패한다 (D-21).
F. **PWA** — manifest + service worker + 푸시 수신 핸들러 + notificationclick 매트릭스 딥링크 (D-20)
   + 오프라인 캐시. 로컬 매트릭스 캐시는 이미 api.js에 있다.

## 지킬 것

- **실 코레일 API를 루프로 때리지 마라.** 스케줄러 개발·디버깅은 ADAPTER=mock으로 한다.
  30초 틱이 실 API에 붙으면 호출 예절(10절)을 순식간에 넘긴다 — 이번 Phase에서 가장 위험한 지점이다.
  시간은 now 주입으로 시나리오를 만들고 sleep/실제 시계를 쓰지 마라.
- 알림 종류는 **5개로 고정**이다. 새 종류를 추가하지 않는다 (8절 "이것만. 늘리지 말 것").
- 실 자격증명·우회 코드를 건드리는 스크립트는 네가 실행하지 말고 명령을 알려줘라.
- 개발 DB(data/itx.db)를 삭제·초기화하지 마라. 계정이 들어 있고 가입이 잠겨 복구가 번거롭다.
- 시크릿은 .env에만. 웹훅 URL은 DB에 Fernet으로.
- PLAN.md와 충돌하거나 문서가 침묵하는 지점을 만나면 멈추고 보고해라. 합의된 변경은 본문 수정 + D-항목.

## 테스트 (13절)

`test_alerts.py`의 7개 케이스가 이 Phase의 핵심이다 — **침묵해야 할 때 침묵하는지**가 요점이다.
이미 15개가 있으나 스케줄러 배선 후 다음이 추가로 잠겨야 한다:
- 구간만 진행됐을 때(SEATED) 알림이 나가지 않는다
- 하위 추천 순서만 바뀌었을 때 침묵한다
- 첫 폴링은 항상 1건 발송한다 (베이스라인, 생존 확인)
- 폴링 시점당 푸시는 최대 1건이다 (우선순위 합성)
- 스케줄러 재시작 후 포인터에서 이어진다 (멱등)

완료 기준: 탑승 등록 → 역 접근 시 자동 갱신 → [입석] 착석 가능 다이제스트 수신 /
[착석] 내 자리 판매 시 폰에 알림 수신 → 앱에서 "이 자리에 앉음" → 이후 알림이 새 자리 기준으로 발송.
```

### Phase 4 — 배포 + 개선 *(다음 세션에서 이 블록을 그대로 붙여넣는다)*

```
PLAN.md 11절 Phase 4(배포 + 개선)를 시작한다.
Phase 3은 코드 완료다 — 이슈 #8, PR #11, pytest 349 통과, 아이폰 실기기로 테스트 푸시 수신 확인.
실사용 중 발견한 매진 버그(이슈 #9, PR #10, D-36)도 함께 머지됐다.

착수 전:
1. PR #10·#11이 dev에, dev가 main에 머지됐는지 확인해라. 안 됐으면 알려줘 — 머지는 내가 한다.
2. feature 템플릿으로 새 이슈를 발급하고 dev에서 feat/<이름>으로 분기해라.
   커밋만 하고 push는 내가 한다.

## 먼저 알아야 할 것

**Phase 3의 완료 기준 절반이 아직 열려 있다.** "역 접근 시 자동 갱신 → 알림 수신"을
실제 출근길에서 통과시키지 못했다 — 맥이 잠들면 30초 틱이 멈추기 때문이다.
**배포가 그 검증의 전제다.** 그래서 A(배포)가 최우선이고 개선 항목은 전부 그 뒤다.

인스턴스 사양·리전 선택 이유·체크리스트는 12절에 이미 있다. 새로 정하지 말고 그걸 따라라.

## 착수 순서 (앞이 뒤의 전제다)

A. **배포.** Dockerfile + docker-compose + Tailscale serve. 12절 체크리스트를 그대로 소화한다.
   조용히 틀리는 3개를 특히 확인해라: ARM64 이미지 / 스왑 2GB / **uvicorn --workers 1**
   (2개면 알림이 중복 발사된다).
   - **AWS 리소스를 네가 만들지 마라.** 실 과금이고 내 계정이다. 프로비저닝은 내가 한다 —
     필요한 명령과 콘솔 절차를 정리해서 알려줘라.
   - `.env` 이관은 12절 체크리스트의 SECRET_KEY / VAPID 항목을 반드시 먼저 읽어라.
     키를 새로 만들면 자격증명 복호화와 기존 기기 등록이 **조용히** 무효가 된다 (D-34, D-35).
   - 데이터 이관: station / train_stop 캐시는 스크립트 재적재로 충분하고,
     user·subscription은 DB 파일을 옮긴다. **개발 DB(data/itx.db)를 지우지 마라.**

B. **스케줄러 → 알림 실기기 검증.** A가 끝나면 EC2가 24시간 깨어 있으므로 비로소 가능해진다.
   실제 출근길 한 번으로 Phase 3 완료 기준을 닫는다. 타는 건 내가 한다 —
   무엇을 확인해야 하고 실패 시 어느 로그를 봐야 하는지 정리해줘라.

C. **D-36 후속 — 코드값은 확보·등재됐다** (`ERI411321`, 배포 첫날 EC2 로그 → D-39 항목의
   결과 주석). 남은 것은 부분 매진 구독이 FETCH_FAILED 대신 정상 알림을 내는지 확인하는
   **스케줄러 레벨 회귀 테스트** — #9 작업 때 test_scheduler.py가 다른 브랜치에 있어
   넣지 못했다.

D. **관리자 복구 수단** (D-24 후속). 11절에 후보 2개가 있고 CLI 한 줄이 권장안으로 적혀
   있지만 **확정된 결정이 아니다 — 구현 전에 물어봐라.**
   D-53(사용자 관리)은 이것과 **다른 문제다.** 그쪽은 관리자가 남을 지우는 것이고,
   이건 관리자가 사라졌을 때 푸는 것이다. D-53의 API로는 풀리지 않는다.

E. 나머지 개선 항목(2회 이동 조합 추천 / 좌석 점유 이력 통계 / D-17 조정 손잡이)은
   **설계가 문서에 없다.** 앞의 둘은 스키마와 화면이 따라오므로 임의로 만들지 말고
   설계를 먼저 제시해 합의해라. D-17 손잡이 조정은 실사용 몇 주치 데이터가 전제다.

## 지킬 것

- 실 코레일 API를 루프로 때리지 마라. 개발·디버깅은 ADAPTER=mock (CLAUDE.md 10).
- **AWS·실 자격증명을 건드리는 명령은 네가 실행하지 말고 알려줘라.** 내가 직접 돌린다.
- 개발 DB(data/itx.db)를 삭제·초기화하지 마라. 계정이 들어 있고 가입이 잠겨 복구가 번거롭다.
- 시크릿은 .env에만. pre-commit 훅이 기계적으로 막지만(D-33) 훅을 믿고 방심하지 마라.
- 알림 종류는 5개로 고정. 통계 기능을 붙이더라도 늘리지 않는다 (8절).
- PLAN.md와 충돌하거나 문서가 침묵하는 지점을 만나면 멈추고 보고해라. 합의된 변경은 본문 수정 + D-항목.

완료 기준 — **11절에 명시가 없다. 아래는 제안이니 착수 전에 확정하자**:
EC2에서 서비스가 상시 동작하고, **실제 출근길에 폰으로 알림이 도착한다.**
E의 개선 항목은 포함하지 않는다 — 배포와 Phase 3 완료 기준 마감이 이 Phase의 코어다.
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
- *v27 개정 (→ D-57)*: 출발 -1분 폴 1회가 추가되어 정차역당 최대 3회가 됐다.
  조회 빈도 원칙도 "정차역당 2~3회"로 함께 개정. -10/-4분의 역할 분담(다이제스트/막판 발권)은
  그대로고, 출발 -1분은 **갭 구간 스냅샷의 신선도**를 담당한다

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
  붙이거나 cron으로 자동화할 수 있다. 지금은 수동 스크립트로 충분). **→ D-58에서 자동화됨**
  (2026-09-01 개편이 이 유예의 대가를 실제 장애로 보여줬다). 스크립트는 얇은 CLI로
  남고 로직은 `app.adapters.train_run_info`에 있다.
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

### D-31. 매트릭스 표시 범위 = 내 구간(탑승~하차) *(v10, Phase 2 실사용 중 발견)*

**문제**: 화면이 전체 노선(기점~종점)의 구간을 전부 그리고 있었다. 실노선(부산~서울
28정차)에서 내 구간이 천안~영등포면 나머지 22구간이 함께 나온다.

단순한 과다 표시가 아니다. 내 구간 밖은 **애초에 조회하지 않으므로**
`domain/matrix.py`의 `UNQUERIED_CELL = True`(판매됨)로 채워져 있다. 판정에는 안전한
방향이지만(좌석을 권하지 않는다), 화면에서는 **관측하지 않은 값이 관측값과 구분되지
않는다.** 특히 하차역 이후 구간은 흐림 처리도 걸리지 않는다 — 흐림 조건이
`seg.idx < startIdx`인데 `startIdx`(실효 시작)는 항상 하차역보다 앞이기 때문이다.
결과적으로 하차역 이후가 "실제로 조회해 보니 전부 매진"처럼 읽힌다.

**목업이 이 결함을 구조적으로 가리고 있었다.** Mock 노선이 천안~서울이라
전체 노선 = 사용자 구간이었고, Phase 1 내내 두 범위가 우연히 일치했다.
실연동으로 긴 노선이 들어오고 나서야 드러났다.

**결정**: 표시 범위를 `[board_idx, alight_idx]`로 한정한다. 매트릭스 구간 헤더·셀과
노선 진행바 양쪽에 적용한다(28정차 진행바는 모바일 폭에서 역 이름이 뭉개지기도 한다).

- **인덱스는 전체 노선 기준을 그대로 쓴다** — 슬라이스하면서 재번호를 매기지 않는다.
  `cells[seg.idx]`, `clear_until`, 흐림 조건이 전부 D-18 기준으로 맞물려 있어
  재번호를 매기는 순간 조용히 어긋난다.
- 서버는 계속 전체 노선 `stops`를 준다. D-18(인덱스는 전체 노선 기준)이 도메인 계약이고,
  자를 곳은 표시 계층이다.
- 탑승역~실효 시작 사이(이미 지나온 내 구간)는 기존대로 흐림 처리로 남긴다 —
  PLAN 10절 "지나온 구간 흐림 처리"가 이 범위를 뜻하게 된다.

### D-32. 역 선택은 필터형 콤보박스 — 초성 검색 포함 *(v10, Phase 2 실사용 중 발견)*

**문제**: D-25가 세운 역 드롭다운이 실데이터에서 무너졌다. Mock 노선은 **6개**였고
`station` 테이블 여객역은 **282개**다. 282개를 네이티브 `<select>`로 훑어 고르는 건
실사용에서 성립하지 않는다. D-31과 같은 구조의 발견 — **목업이 규모를 가리고 있었고,
그 소스를 갈아끼운 Phase 2가 드러냈다.**

**결정**: 타이핑으로 목록을 좁히는 콤보박스(`web/src/StationPicker.jsx`).

- **D-25는 유지된다.** 타이핑은 목록을 좁히기만 하고 **확정되는 값은 언제나 목록에서
  고른 역**이다. 자유 입력이 그대로 API로 가지 않으므로 "오타가 곧 404"는 그대로 막힌다.
  D-25의 반전이 아니라 확장이다.
- **클라이언트 측 필터링.** 282개는 이미 한 번에 받아온 몇 KB다. 서버 `?q=` 검색은
  왕복이 늘고, 회선이 불안정한 화면(10절)에서 손해다.
- **정렬**: 앞에서 걸린 것 → 짧은 이름 → 가나다순. 두 번째 기준이 없으면 "천안"에
  천안아산이 천안보다 먼저 온다.
- 채택하지 않은 것: `<datalist>`. iOS Safari 지원이 들쭉날쭉하고 자유 입력이 새어나가
  위의 보장을 깬다.

**초성 검색 (`web/src/hangul.js`)** — 이 결정의 핵심이자 조용히 틀리기 쉬운 부분:

- 순진하게 초성만 비교하면 **IME 조합 중간 상태에서 목록이 빈다.** "천안"을 치면
  ㅊ → 처 → 천 → 천ㅇ → 천아 → 천안을 실제로 거치는데, "천아"는 초성 비교로도
  완성형 비교로도 걸리지 않는다(아 ≠ 안). 타이핑 도중 결과가 깜빡인다.
- 그래서 글자를 **자모로 분해해 접두 비교**한다. 질의 글자의 자모열이 이름 글자의
  자모열의 접두면 일치: `아[ㅇㅏ] ⊂ 안[ㅇㅏㄴ]`, `ㅊ[ㅊ] ⊂ 천[ㅊㅓㄴ]`.
  초성 검색·조합 중간 상태·완성형이 **규칙 하나로 통일**된다.
- 겹모음(ㅘ=ㅗ+ㅏ)·겹받침(ㄳ=ㄱ+ㅅ)도 분해한다. 안 풀면 "고"로 과천에 닿지 못한다 —
  이것도 조합 중간 상태다(ㄱ → 고 → 과).
- 매칭 로직은 컴포넌트에서 분리해 순수 함수로 뒀다. 실제 역 이름 282개로 조합 전
  과정(ㅊ/처/천/천ㅇ/천아/천안)에서 결과가 비지 않는지 확인했다.

**남는 것**: 매일 같은 구간을 타는 반복은 콤보박스가 아니라 **프리셋**이 없앤다
(10절·D-25에 이미 있고 API도 구현돼 있으나 프론트 미사용). 새 기능이므로 Phase 4에 둔다.

### D-33. 시크릿 유출 방지 pre-commit 훅 *(v10, Phase 2 실사용 중)*

**문제**: 실 자격증명이 추적되는 `.env.example`에 들어간 사고가 **세 번** 났다
(Phase 0 코레일 계정, Phase 2 data.go.kr 키 2회). 세 번 다 커밋 전에 잡았지만
**전부 사람 눈에 의존한 포착**이었다. 같은 사고가 세 번 반복됐다는 것은 습관으로
막을 수 없다는 뜻이다 — 한 번만 통과하면 공개 이력에 영구히 남는다.

**결정**: `scripts/hooks/pre-commit`으로 기계가 막는다. 세 겹:

1. **`.env.example`의 시크릿성 키에 값이 있는가** — `PUBLIC_KEYS`(DB_PATH·ADAPTER 등
   시크릿이 아닌 것)만 값을 허용하고 **나머지는 기본 차단**한다. 허용 목록 방식이라
   앞으로 추가되는 키는 자동으로 보호 대상이 된다. 워킹트리가 아니라 **스테이지된
   내용**(`git show :파일`)을 검사한다 — 실제로 커밋되는 건 그쪽이다.
2. **`.env`의 실제 값이 스테이지된 내용에 나타나는가** — 파일 종류를 가리지 않는다.
   1번은 `.env.example`만 보지만 이건 코드·문서·어디에 붙여넣든 잡는다. 실제 사고를
   가장 직접적으로 막는 검사다. 시크릿을 훅에 적어두지 않고 **실행 시점에
   `.env`(gitignore됨)에서 읽는다**. 짧은 값(12자 미만)은 건너뛴다 — `mock`/`false`
   같은 설정값이 코드에 흔히 등장해 오탐이 된다.
3. **커밋 금지 경로** — `.env`, `*.db`, `scripts/phase0_results/`.
   `.gitignore`가 이미 막지만 `git add -f`를 뚫고 들어올 수 있다.

- **설치**: `git config core.hooksPath scripts/hooks`. `.git/hooks/`에 두면 추적되지
  않아 새 클론에서 사라진다 — 훅을 레포에 두고 경로만 가리킨다.
- 우회는 `git commit --no-verify`. 막을 수단은 아니고, 오탐일 때의 탈출구다.
- 오탐 확인까지 검증했다 — 시크릿과 무관한 정상 커밋은 막지 않는다.

> **v14 개정 (→ D-44)**: 위 세 겹의 **규칙은 `scripts/secret_scan.py`로 옮겼고**
> (`PUBLIC_KEYS`·금지 경로 포함) 훅은 그것을 "스테이지된 것"에 적용하는 껍데기가 됐다.
> **CI가 같은 규칙을 추적 파일 전체에 돌린다** — 훅을 켜는 것을 잊어도 ①·③은 막힌다.
> 다만 **②는 CI에서 불가능하다**(러너에 `.env`가 없다). 그리고 **워크트리에서는 ②가
> 조용히 꺼져 있었다** — `.env`가 없으면 그냥 통과했다. 둘 다 D-44에서 다뤘다.

### D-34. Phase 3 착수 시 문서가 침묵한 4개 지점 *(v11, Phase 3 구현 중)*

Phase 3(알림 + 자동화)은 8·9절이 "무엇을 보낼지"를 이미 정해뒀지만, **배선에 필요한
결정 4개가 문서에 없었다.** 임의 구현 대신 멈추고 합의했다 (CLAUDE.md 규칙).

**① VAPID 키 = `.env` 3개 + 공개키만 API 노출**
- 8절은 pywebpush를 전제하면서 키 관리·공개키 전달 경로를 말하지 않았다.
  브라우저는 `pushManager.subscribe({applicationServerKey})`에 **공개키**가 필요하고,
  서버는 발송에 **비밀키**가 필요하다.
- 결정: `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` / `VAPID_SUBJECT`를 `.env`에.
  공개키만 `GET /api/push/config`로 나간다. 생성은 `scripts/gen_vapid.py` (일회성).
- **탈락한 안**: 첫 부팅에 자동 생성해 `app_setting`에 저장. 설정 파일을 손댈 일이
  없어 편하지만 시크릿이 DB로 들어가 백업·이관 경로가 하나 더 생긴다. "시크릿은
  `.env`로만"(절대규칙)이 이미 답을 정해뒀다.
- **주의**: 키를 바꾸면 기존 `push_device` 등록이 전부 무효다 (브라우저 구독이 옛
  공개키에 묶여 있다). 기기마다 알림을 다시 켜야 한다.
- `VAPID_SUBJECT`는 훅의 `PUBLIC_KEYS`에 넣었다 — `mailto:` 연락처일 뿐 발송 권한이
  아니고, 권한을 쥔 `VAPID_PRIVATE_KEY`는 목록에 없으므로 값이 채워지면 차단된다 (D-33).

**② `fail_count` = FETCH_FAILED 게이트. 재시도 불가 실패도 같은 게이트로 1회 발송**
- 5절 스키마에 `fail_count`가 있는데 8·9절은 쓰는 법을 말하지 않았다. 또 8절의
  FETCH_FAILED 정의는 "30초×3 재시도 모두 실패"뿐인데, **재시도해도 같은 결과인
  실패**(자격증명 미연동, 정차역 캐시 없음)는 그 정의에 해당하지 않는다.
- 결정: 실패 시 `fail_count += 1`, 성공 시 `0`으로 리셋, **`0→1` 전이에서만 발송**.
  이것이 "1회 발송 후 복구까지 재발송 없음"(8절)의 구현이다. 재시도 불가 실패도 같은
  게이트로 1회 보낸다 — 안 보내면 알림이 조용히 죽은 것을 폰에서 알 방법이 없다.
- 5종을 늘리지 않으므로 원인은 `fetch_failed_alert(reason=...)`로 **본문에** 담는다.
  자격증명 미연동과 코레일 장애는 취할 행동이 전혀 다른데 둘 다 "갱신 실패"로만
  오면 앱을 열어봐도 알 수 없다.
- 리셋을 빼먹으면 다음 장애 때 FETCH_FAILED가 영구히 침묵한다 — 테스트로 잠갔다.

**③ 만료 안전망 — 정차역을 모르면 지난 운행일 구독은 만료시킨다**
- 9절의 "하차역 실효 도착시각 경과 시 `active = false`"는 `is_ride_over()`에 정차역이
  필요하다. 그런데 korail2 어댑터는 캐시가 비면 `TrainStopsNotCached`를 던진다(D-29)
  → **만료 판정 자체가 불가능해져 어제 구독이 영원히 후보로 남아 매 틱 실패한다.**
- 결정: 정차역 해석 실패 + `date < 오늘`이면 만료. Phase 2에서 겪은 "지난 날짜 구독이
  계속 살아나는" 문제(프론트의 "다른 열차" 탈출구로 임시 대응)를 여기서 닫는다.
- 포인터가 빈(`next_poll_at IS NULL`) 구독도 틱 후보에 넣는다 — 마지막 폴 포인트를
  지나면 포인터가 비는데, 그때 하차역 통과를 확인할 주체가 없으면 만료가 안 된다.

**④ 알림 이력 테이블은 만들지 않는다**
- 5절 스키마에 `alert` 테이블이 없고 `last_notified_at`만 있다. "오늘 뭐가 왔나"를
  조회하려면 편하지만, 스키마 개정 + 조회 API + 화면이 줄줄이 따라온다.
- 결정: 만들지 않는다. 8절 "늘리지 말 것" 정신에 맞추고 Phase 3 범위를 지킨다.
  진단은 서버 로그(`TickReport`)로 한다. 실사용에서 정말 필요해지면 Phase 4.

**부수 결정 — 발송 성공 여부와 상태 기록을 분리한다**
- 발송에 실패해도 `last_verdict_hash`/`last_cells_snapshot`은 기록한다.
  상태는 "관측한 것"이고 발송은 "알린 것"이라 섞으면 **발송 실패가 상태 오염으로
  번진다.** 애초에 iOS는 배달 성공을 서버에 알려주지 않으므로 "발송 성공"이 신뢰
  가능한 신호가 아니다 (8절이 폴백 방식을 거부한 것과 같은 이유).
  `last_notified_at`만 실제로 한 채널이라도 받아들였을 때 기록한다.
- 기기 미등록으로 알림이 새는 구멍은 `/api/push/test`가 막는다 (D-9).

**부수 결정 — `NotifierPort`는 `Alert`가 아니라 `Notification`을 받는다**
- `/api/push/test`의 생존 확인 핑은 **알림 종류가 아니다.** `Alert`로 감싸려면 5종 중
  하나를 거짓으로 붙여야 하고, 그러면 "종류를 늘리지 말 것"이 다른 방식으로 무너진다.
- 전송 계층은 `Notification(title, body, payload)`만 다루고, `Alert → Notification`
  변환은 `adapters/notify.py`가 한다.

### D-35. 다중 사용자 — 코레일 계정은 **사용자마다 각자** *(v11, Phase 3 실사용 중)*

**질문**: 가족·지인 1~2명을 추가로 가입시키면 그 사람들도 내 코레일 계정으로 조회하게
되는가? 그렇다면 계정을 `.env`가 아니라 DB에 사용자별로 두는 편이 낫지 않은가?

**답**: **이미 그렇게 돼 있다.** D-10(사용자 귀속 데이터는 DB에)과 D-22(로그인 필수 +
Fernet 암호화)의 결과이며, 이 절은 그 사실을 명시적으로 못박기 위해 남긴다.
세 층 전부에서 사용자별로 갈린다:

| 층 | 분리 방식 |
|---|---|
| 저장 | `user` 행마다 `korail_id` + `korail_pw_enc` (Fernet). `.env`가 아니다 |
| 조회 | `load_korail_cred(conn, user_id)` — `user_id`는 **세션에서만** 온다 (절대규칙 9) |
| 코레일 세션 | `korail_client.get_client()`이 `(korail_id, korail_pw)`를 키로 캐시 |

마지막 줄이 특히 중요하다. 어댑터(`Korail2Adapter`)는 프로세스 싱글턴이지만 **로그인
세션은 자격증명별로 따로 잡힌다.** 하나의 세션을 돌려 쓰는 구조였다면 A의 로그인으로
B가 조회되는 사고가 났을 것이다. 스케줄러도 구독의 `user_id`로 매번 꺼내 쓴다.

- `.env`의 `KORAIL_ID`/`KORAIL_PW`는 **`scripts/phase0_feasibility.py` 전용 잔재**다.
  `config.Settings`에 필드조차 없어서 앱은 그 값을 읽지 못한다 (`extra="ignore"`).
- UI(`PUT /api/me/korail`)로 저장해도 `.env`는 바뀌지 않는다. **`.env`에 쓰는 코드는
  코드베이스에 없다.** 앱은 기동 시 한 번 읽기만 한다.

**따라오는 제약 — 가족도 각자 코레일 계정이 있어야 한다.** Phase 0 결론이 로그인
필수(D-14/D-22)이므로 계정 없는 사람은 조회 자체가 안 된다. 한 계정을 나눠 쓰는 것은
기술적으로는 가능하지만(각자 같은 자격증명을 입력) **권하지 않는다** — 약관 회색지대이고,
같은 계정으로 동시 세션이 뜨면 안티봇 관점에서 위험하다 (10절 호출 예절).

**추가 절차**: 설정에서 회원가입 허용을 잠깐 켜고(D-24) → 가입 → 다시 잠금 →
그 사람이 자기 폰에서 자기 코레일 계정 연결 + 알림 기기 등록.

**배포 시 주의 (→ Phase 4)**: `korail_pw_enc`는 `SECRET_KEY`로 암호화돼 있다.
DB 파일만 옮기고 키를 새로 만들면 복호화가 깨진다. 그때 **조용히 끊기지 않도록**
복호화 실패를 `None`으로 떨어뜨려 `FETCH_FAILED`가 1회 나가게 했고, 화면의 "연결됨"
표시도 복호화까지 성공해야 켜지게 바꿨다 (`korail_linked()`).
`.env`의 `KORAIL_ID`/`KORAIL_PW`는 EC2로 옮길 필요가 없다.

### D-36. 매진은 실패가 아니라 데이터다 *(v11, Phase 3 실사용 중 발견 → 이슈 #9)*

**증상**: 천안→영등포 구독에서 천안~수원은 빈자리가 있고 수원~영등포만 매진일 때,
매트릭스가 아예 그려지지 않고 `조회 실패`가 떴다. **가장 쓸모 있는 정보("수원까지는
앉을 수 있다")가 통째로 사라진다.**

**원인**: 매트릭스는 인접 구간을 하나씩 조회하는데(`fetch_segment_maps`), 매진 구간은
코레일 `ScheduleView`가 결과를 주지 않는다. `_seat_map_sync`가 그것을 **"열차가 존재하지
않는다"**로 읽고 `ValueError`를 던졌다 — 그러면 앞 구간에서 이미 성공적으로 받아온
좌석표까지 함께 버려진다.

```python
# 고치기 전
train = client.find_train(d, frm, to, train_no)
if train is None:
    raise ValueError(f"{frm}→{to} 구간에 열차 {train_no}가 없다")
```

**결정**: 매진을 **에러가 아니라 '전 좌석 판매됨'이라는 데이터**로 흡수한다.
빈 좌석맵을 돌려주면 D-18의 유니버스 합집합이 그 구간을 판매로 채운다 — 병합 로직은
이미 올바랐고 어댑터만 연결이 안 돼 있었다.

- **D-27이 같은 판단을 이미 호차 단위로 내려뒀다**: "잔여 0인 호차는 좌석맵을 받아봐야
  전부 판매됨이다". 그 논리를 **구간 단위**에 적용하지 않은 것이 이번 누락이다.
- 실패 경로가 둘이라 **양쪽 다 처리**했다 (실측 로그로 어느 쪽인지 확정하지 못했다):
  - ① `ScheduleView`가 `NO_RESULT_CODES`로 답 → `find_train`이 None → 빈 좌석맵
  - ② 그 밖의 코드로 FAIL → `KorailSoldOut`(신설, `KorailApiError` 하위형) → 빈 좌석맵.
    **재시도 대상이 아니다** — 30초 뒤에 물어도 매진은 매진이다 (D-17 재시도 정책)
- `KorailSoldOut` 판별은 **코드 우선, 없으면 문구**(`잔여석`/`매진`/`좌석이 없`)다.
  코드값을 실측하지 못해 문구를 함께 본다. 문구 매칭은 취약하지만 **놓쳤을 때의
  대가(조회 전체 실패)가 오탐의 대가(매진으로 표시 → 추천에서 빠짐)보다 크다.**
  실측되면 `SOLD_OUT_CODES`에 넣고 문구 의존을 줄인다.
- 호차 단위 매진도 흡수한다 — 한 호차가 팔렸다고 예외를 올리면 **다른 호차의 빈자리까지
  함께 사라진다.**

**"없는 열차번호"를 조용히 삼키지 않나?** 그 경우는 여기까지 오지 않는다 —
`get_stops()`(정차역 캐시, D-29)가 먼저 `TrainStopsNotCached`로 막고, 열차 선택 화면도
실제 검색 결과에서 고르게 한다. 만에 하나 전 구간이 비면 **전부 판매된 매트릭스**가
그려지는데, 이는 `ALL_SOLD`("환승 고려")로 이어져 그 자체로 올바른 표시다.

**알림에 미치는 영향이 더 컸다.** `scheduler/poller.py`도 같은 `fetch_matrix`를 쓰므로,
고치기 전에는 매진 구간이 낀 구독이 **폴링마다 실패하고 `FETCH_FAILED`만 발송**했다.
정작 필요한 "수원까지는 앉을 수 있다"는 영영 오지 않는다 — **매진에 가까운 시간대일수록
알림이 무용해진다**는 뜻이라 Phase 3 신뢰도와 직결된 버그였다.

### D-37. 직전 구간 자동 프리필 — 프리셋보다 먼저 *(v11, Phase 3 실사용 중 발견 → 이슈 #12)*

**증상**: "탑승 종료"로 매트릭스를 빠져나오면 탑승 등록 화면이 빈 폼으로 돌아간다.
매일 같은 구간을 타는데 출발·도착역을 매번 다시 골라야 했다.
`Setup.jsx`가 마운트마다 `{ from: "", to: "" }`로 초기화하는데, 값이 화면 상태에만
있었으므로 남을 곳이 없었다.

**D-32가 이 불편을 이미 지목하고 답을 프리셋으로, 시점을 Phase 4로 적어뒀다.**
이 항목은 그 배치를 **자동 프리필에 한해** 앞당기는 개정이다 (프리셋 자체는 Phase 4에 유지).

**결정: 새 저장소를 만들지 않고 지난 구독을 그대로 쓴다.**

- "탑승 종료"는 하드 삭제가 아니라 `active = 0`이다 (스케줄러가 `active`만 보므로
  알림이 자동으로 멈춘다). **지난 구독 행이 board_at/alight_at을 그대로 들고 남아 있다.**
- `GET /api/subscriptions?active_only=false`가 이미 `created_at DESC`로 그걸 준다 →
  **첫 행이 곧 직전 구간이다. 백엔드 변경 0줄, 새 테이블 없음.**
- localStorage를 쓰지 않은 이유: 서버 데이터를 쓰면 기기를 바꿔도 따라오고,
  `user_id`로 갈려 있어 남의 구간이 새지 않는다 (절대규칙 9).

**프리셋을 먼저 만들지 않은 이유**: 프리셋은 사용자가 "저장"이라는 동작을 해야 값어치가
생기고 목록 UI가 따라붙는다. 자동 프리필은 **사용자가 하는 일이 0**이고 프론트 초기값
로직 하나로 끝난다. 1인용 통근 도구에서 실제로 반복되는 구간은 사실상 하나다.
출근/퇴근처럼 구간이 둘 이상 필요해지면 그때 프리셋 프론트를 붙인다.

**채우지 않는 것**: 운행일·검색 기준 시각·열차번호·좌석. 특히 **운행일은 채우면 안 된다** —
어제 날짜가 들어가 있는 편이 빈 칸보다 훨씬 나쁜 버그다. 통근은 "몇 시 차"가 아니라
"지금 탈 수 있는 차"를 고르는 일이므로 시각도 항상 현재 기준이다 (10절).

**조용히 틀릴 수 있어 잠근 것**:
- **프리필은 실패해도 되는 부가 기능이다.** 구독 조회 실패를 삼켜 탑승 등록 자체를
  막지 않는다. 역 목록 조회만 필수로 남긴다.
- **사용자가 이미 역을 골랐으면 덮어쓰지 않는다.** 조회가 늦게 도착했을 때 방금 한
  입력을 지우는 쪽이 훨씬 나쁘다.
- **역 목록에 없는 이름은 건너뛴다.** 채워 놓아도 검색이 실패해 빈 칸보다 나쁘다.
- `active_only` 기본값과 정렬에 테스트를 붙였다 (`test_api.py`). 기본값이 뒤집히면
  **끝난 열차의 매트릭스가 뜨고**, 정렬이 바뀌면 엉뚱한 구간이 채워진다 — 둘 다 조용하다.
### D-38. 접근 경로 — 현행 Tailscale 유지, 공개 노출은 옵션으로 보류 *(Phase 4 착수 전 검토)*

**맥락**: Tailscale 방식은 **접근할 기기마다 Tailscale을 깔고 tailnet에 참여**해야 한다.
1인용일 때는 비용이 0에 가깝지만, 지인에게 열어주려면(D-24의 가입 토글) 앱 가입 위에
tailnet 초대가 하나 더 얹힌다. 그래서 Vercel 같은 공개 배포 방식을 함께 검토했다.

**먼저 정리된 것 — 갈림길은 "Vercel이냐"가 아니라 "API를 공개하느냐"다.**
프론트를 Vercel에 올려도 브라우저는 결국 API를 호출한다. API가 tailnet 안에 있으면
정적 파일만 공개되고 **앱은 동작하지 않는다.** 반대로 API를 공개하기로 하면 그 서버가
이미 정적 파일도 서빙하므로(10절, `StaticFiles`) Vercel이 추가로 주는 것이 거의 없다.
백엔드를 Vercel로 옮기는 것은 애초에 불가능하다 — APScheduler 30초 인프로세스 틱(9절)은
상시 실행 프로세스를 전제하고 서버리스에는 그런 게 없다. **EC2는 어떤 선택지에서도 남는다.**

**검토한 4개**

| | 클라이언트 설치 | 인바운드 포트 | 코드 변경 | 이중 방어(D-10) | 지인 추가 |
|---|---|---|---|---|---|
| **A. Tailscale (현행)** | 필요 (앱 + tailnet 초대) | 0 | 없음 | 유지 | tailnet 초대 + 앱 가입 |
| **B. Cloudflare Tunnel** | 없음 | 0 | `cookie_secure`만 | **네트워크 계층 소실** | 앱 가입만 |
| **B+. Tunnel + Access** | 없음 | 0 | `cookie_secure`만 | 복원 (Access 게이트) | Access 화이트리스트 + 앱 가입 |
| **C. Vercel + 공개 API** | 없음 | 443 개방 | CORS + `SameSite=None` + CSRF | 네트워크 계층 소실 | 앱 가입만 |

**결정: A를 유지한다. 전환이 필요해지면 B+로 간다. C는 배제한다.**

- **C를 배제한 이유**: 오리진이 갈리면 지금 구현이 단일 오리진 전제라 세 곳이 깨진다 —
  세션 쿠키가 `samesite="lax"`라 크로스 사이트로 실려가지 않고(`api/auth.py`),
  `SameSite=None; Secure`로 바꾸면 `Lax`가 공짜로 주던 CSRF 최소 보호가 사라져 토큰을
  따로 붙여야 하며, `CORSMiddleware`가 없으니 `allow_credentials` + 오리진 화이트리스트를
  더해야 한다(프리뷰 배포 도메인까지 관리 대상이 된다). Vercel `rewrites`로 프록시하면
  이 작업은 피하지만 **매트릭스 조회가 정차역 수만큼 코레일을 병렬 호출**하므로(3절)
  응답이 수 초 걸려 프록시 실행 시간 제한에 걸릴 위험이 있고, 세션 쿠키와 좌석 트래픽이
  엣지를 한 번 더 경유한다. **B의 보안 프로필에 작업량만 더한 형태다.**
- **B+가 B보다 나은 이유**: 공개 노출은 2절 비목표·D-1이 못박은 "공개 노출 없음"과
  충돌한다. korail2 우회 사용의 정당성을 평가할 때도 **"이 프로젝트는 처음부터 앱스토어
  배포·공개 노출이 없다"를 무게추로 삼았다**(D-22). 그 전제를 근거로 리스크를 낮게 봤다. **인증 없는 공개 URL이 되면 그 논거가 약해진다** —
  Access 게이트(이메일 OTP·구글)가 네트워크 계층 방어를 되살려 이 논거를 유지시킨다.
- **전환 비용이 낮은 것이 A를 먼저 택한 근거다.** B/B+는 단일 오리진을 유지하므로
  앱 코드는 `config.cookie_secure`(이미 그 자리를 비워뒀다) 하나뿐이고, 호스트에
  `cloudflared`를 하나 더 띄우는 일이다. Tailscale과 병행도 된다.

**전환 트리거** (하나라도 걸리면 B+를 다시 꺼낸다)
- 지인·가족에게 실제로 열어주게 된다 (tailnet 초대가 반복 작업이 된다)
- 내 기기가 아닌 곳에서 급히 봐야 하는 상황이 반복된다

**전환 시 미리 아는 대가**: 도메인이 필요하다(Cloudflare에 위임된 것, `trycloudflare.com`
임시 URL은 재시작마다 바뀌어 PWA·푸시에 부적합). 그리고 **오리진이 바뀌므로 기기마다
알림을 다시 켜야 한다**(→ D-34). 커스텀 도메인을 쓸 생각이 이미 있다면 `ts.net`으로
한 번 붙였다가 옮기는 대신 **Phase 4 배포에서 한 번에 가는 편이 낫다** — 그러면
재등록이 두 번이 아니라 한 번이다.

### D-39. 앱 로그가 한 줄도 나오지 않고 있었다 *(v12, Phase 4 배포 준비 중 발견)*

**증상**: `scheduler/service.py`가 매 폴링마다 찍는 `log.info("폴링 틱: 조회 %s · 알림 %s …")`가
**한 번도 출력된 적이 없다.** "폴링 스케줄러 시작"도 마찬가지다.

**원인**: 앱에 `logging` 설정이 아예 없었다. uvicorn은 `uvicorn`/`uvicorn.error`/
`uvicorn.access` 로거만 설정하고 **root는 비워둔다.** 그 상태에서 `app.*` 로거의 INFO는
핸들러가 없어 사라지고, WARNING 이상만 `logging.lastResort`를 타고 포맷 없이 stderr로
새어나온다. 그래서 **실패는 (거칠게라도) 보이고 정상 동작은 완전히 침묵하는** 조합이었다.

**지금까지 문제가 안 됐던 이유**: 개발 중에는 브라우저 화면으로 확인했다. 스케줄러가
도는지도 화면의 갱신으로 짐작할 수 있었다.

**배포하면 이게 관측 수단의 전부가 된다.** `docker compose logs`밖에 없는데 그 로그에
정상 동작이 안 찍히면 "알림이 안 온다"의 원인을 좁힐 수 없다 — 스케줄러가 안 떴는지,
폴 포인트가 안 왔는지, 조회는 됐는데 침묵이 정상인지(원칙 6)를 구분할 방법이 사라진다.
**Phase 3의 남은 완료 기준이 실기기 검증이라 이건 배포의 전제다.**

**결정: `main.configure_logging()` 하나로 root에 핸들러를 붙인다. 레벨은 env `LOG_LEVEL`(기본 INFO).**

- **`lifespan`에서 호출한다** — uvicorn이 자기 로깅을 세팅하는 시점이 앱 임포트보다 먼저라,
  그 뒤에 덮어야 한다. `force=True`로 확정적으로 덮고, 두 번 호출돼도 핸들러가 겹치지 않게 한다
- `--log-config` 파일을 쓰지 않은 이유: 배포에서만 필요한 설정이 아니라 **앱이 자기 로그를
  내보내는 것 자체가 기본값**이어야 한다. env 하나로 끝나는 쪽이 재현·설명이 쉽다
- 컨테이너에 `TZ=Asia/Seoul`을 넣는 것도 이 결정의 일부다. `logging`은 aware datetime을
  모르고 `localtime`을 쓰므로, TZ가 UTC면 **로그 타임스탬프만 9시간 어긋나** 출근길에
  폰의 알림 시각과 대조할 수 없다 (도메인 시각은 전부 KST aware라 영향 없다 — 로그만의 문제다)
- 같은 맥락으로 `PYTHONUNBUFFERED=1`도 넣었다. 없으면 `docker logs`가 뭉쳐서 늦게 나온다
- **`apscheduler` 로거는 WARNING으로 내린다.** 켜자마자 드러난 문제인데, APScheduler가
  틱마다 "Running job"/"executed successfully" 두 줄을 INFO로 찍어 **30초 틱이면 하루
  5천 줄**이 쌓인다. 신호(폴링 틱 1줄)를 잡음이 덮으면 로그를 켠 목적이 사라진다.
  잡이 죽는 경우는 WARNING 이상으로 남으므로 잃는 것이 없다

**함께 넣은 것 (로직 변경 없음)**: 매진 로그에 `[h_msg_cd=…]`를 붙였다. `SOLD_OUT_CODES`가
비어 있어 한국어 문구 매칭에 기대는 상태인데(D-36), 실 코드값이 없어서 그렇다.
출근길 검증 한 번에서 그 값이 함께 잡히면 D-36 후속을 **또 한 번 열차를 타지 않고** 닫을 수 있다.

> **결과: 출근길을 기다릴 필요도 없었다.** 배포 첫날(2026-08-06 16:18 KST) 브라우저에서
> 열차를 한 번 검색하자 EC2 로그가 바로 값을 내놨다 — 수원→영등포 호차 조회에서
> `[h_msg_cd=ERI411321] 잔여석이 없습니다.` `SOLD_OUT_CODES`에 등재하고
> `tests/test_korail_sold_out.py`로 고정했다. 문구 힌트("잔여석")로도 잡히던 건이지만,
> 코드가 있으면 코레일이 문구를 바꿔도 견딘다. **이 로그 한 줄은 동시에 `SECRET_KEY`
> 이관이 end-to-end로 성공했다는 증거이기도 하다** — 실 API를 호출했다는 것은 DB의
> `korail_pw_enc`가 복호화됐다는 뜻이다 (D-35, D-41).

### D-40. 빌드 머신을 결정으로 승격 — Apple Silicon + `docker save`, 레지스트리 없음 *(v12, Phase 4)*

12절 체크리스트의 첫 줄은 "ARM64 이미지로 빌드"였지만 **어디서 빌드하는지는 침묵했다.**
착수 시점에 개발기가 Intel iMac(x86_64)임이 드러나 그 침묵이 곧바로 문제가 됐다.

- `--platform`을 빠뜨리면 x86 이미지가 나와 t4g에서 `exec format error` (12절이 경고한 함정)
- 붙이면 QEMU 에뮬레이션이 걸려 `npm ci`·vite 빌드가 몇 배 느려진다. **틀리지는 않지만
  매 배포마다 비용을 내는 구조**다

**결정: Apple Silicon 맥에서 네이티브 arm64로 빌드하고, `docker save | gzip | ssh … docker load`로 올린다.**

- **레지스트리를 쓰지 않는다.** ECR은 과금과 자격증명 관리가 붙고, Docker Hub는 이미지를
  공개 저장소에 올리거나 유료 프라이빗을 써야 한다. 1인용 도구에 둘 다 과하다.
  tailnet은 이미 있고 SSH도 이미 있으므로 전송 경로가 공짜다 (압축 후 100MB 안팎)
- **인스턴스 빌드는 폴백으로만 남긴다** (`docker-compose.yml`의 `build:`). 0.5GB RAM에서
  node 빌드는 스왑에 의존하고, T 계열 크레딧을 크게 쓰며, 10GB EBS에 빌드 캐시가 쌓인다
- 함께 확정한 컨테이너 쪽 세부:
  - **비루트 uid 1000 고정.** 호스트의 기본 사용자(우분투 `ubuntu`)가 uid 1000이라 바인드 마운트한 `data/`
    소유자와 맞아떨어진다. 어긋나면 SQLite가 `readonly database`로 죽는다(500으로 드러난다)
  - **퍼블리시는 `127.0.0.1:8000`.** 컨테이너 내부는 `0.0.0.0`이지만 호스트 노출은
    루프백으로 묶는다 — 앞단은 호스트의 `tailscale serve`이고, 보안그룹 하나에만
    의존하지 않는다 (이중 방어, D-10)
  - **`tzdata`를 명시적으로 설치한다.** slim 이미지에 들어 있는지에 기대면
    `ZoneInfo("Asia/Seoul")`이 `ZoneInfoNotFoundError`로 죽는다 (절대규칙 1이 전부 이것에 걸려 있다)
  - **`--provenance=false`로 빌드한다.** 기본값(provenance 부착)이면 `docker save` 산출물이
    index 안에 index가 있는 중첩 구조가 되고, containerd 이미지 스토어를 쓰지 않는 데몬
    (도커 CE의 기본값 — 우분투에 apt로 넣는 `docker-ce`도 여기 해당한다)에서 `docker load`가
    이를 못 읽을 수 있다. 이미지 내용은
    동일하다(config digest 동일). **하필 전송을 다 마친 뒤에 실패하는 자리다**

**검증 상태(v12)**: amd64 네이티브로 시험 빌드해 전 단계(`npm ci`·vite·`uv sync`·`tzdata`·
`useradd`) 통과와 컨테이너 기동(uid 1000 / `--workers 1` 단일 프로세스 / healthcheck healthy /
`+09:00` / 마운트한 `data/`에 DB 생성)을 확인했다. **arm64 빌드 자체는 M4의 첫 빌드가 첫 실행이다** —
베이스 이미지 3개가 linux/arm64를 제공하는 것만 레지스트리 API로 확인해 뒀다.
  - **로그 로테이션** (`max-size: 10m`, `max-file: 3`). 10GB 디스크에 30초 틱 + 액세스 로그가
    무제한으로 쌓이면 디스크가 차고, **그때 먼저 죽는 것은 SQLite 쓰기다** — 알림이 조용히 멈춘다

### D-41. DB 이관은 파일 복사가 아니라 `.backup` — WAL 때문에 최근 데이터가 조용히 사라진다 *(v12, Phase 4)*

11절 Phase 4는 "user·subscription은 DB 파일을 옮긴다"고 적었고 12절도 "SQLite 파일"이라고만
썼다. **그런데 `db.py`가 `PRAGMA journal_mode = WAL`을 걸어둔다** — `data/`에는
`itx.db` 외에 `itx.db-wal`, `itx.db-shm`이 있고 **가장 최근 쓰기는 아직 `-wal`에 있다.**

`itx.db` 하나만 복사해도 파일은 정상적으로 열리고 앱도 잘 뜬다. **다만 방금 등록한
코레일 자격증명이나 푸시 기기가 없다.** 이관 실패로 보이지 않고 "왜 다시 등록해야 하지?"로
보이기 때문에 원인을 엉뚱한 곳(SECRET_KEY, VAPID)에서 찾게 된다 — 가장 나쁜 종류의 조용한 실패다.

**결정: SQLite 온라인 백업 API(`.backup`)로 단일 일관 스냅샷을 만들어 옮긴다.**

- 세 파일을 다 복사하는 방식도 되지만 앱이 살아 있으면 시점이 어긋날 수 있고, 무엇보다
  **사람이 `-wal`을 빠뜨리기 쉽다.** 단일 파일로 만들어 버리면 실수할 여지가 없다
- `wal_checkpoint(TRUNCATE)` 후 복사도 가능하지만 원본을 건드린다 —
  **개발 DB는 읽기만 한다**(계정이 들어 있고 가입이 잠겨 복구가 번거롭다)
- **운영 백업도 같은 이유로 `.backup`이다.** 파일 복사로 뜬 백업은 복원 시점에 최근
  데이터가 비어 있을 수 있는데, 그걸 알아차리는 시점은 이미 복원한 뒤다
- station·train_stop 캐시도 같은 파일에 있으므로 스크립트 재적재가 필요 없다.
  소스 CSV는 `data/`가 gitignore라 저장소에 없다 — **DB를 옮기는 편이 확실하다**

---

### D-42. 인스턴스 OS는 우분투 24.04 LTS (arm64) — 소유자 선택 *(v12, Phase 4)*

절차서 초안은 Amazon Linux 2023을 전제로 썼다. 소유자가 익숙한 우분투를 택했고,
**바꿔도 되는 선택이다.** 근거와 함께 무엇이 바뀌고 무엇이 그대로인지 남긴다.

**바뀌지 않는 것 — 컨테이너 쪽 가정은 전부 살아남는다.**

- **uid 1000.** 우분투 클라우드 이미지의 기본 사용자 `ubuntu`도 uid 1000이다. 바인드
  마운트한 `data/`의 소유자와 컨테이너 사용자가 계속 맞아떨어진다 (D-40). 그래도 가정에
  기대지 않고 절차서에서 `id -u`로 한 번 확인한다
- arm64/t4g, 스왑 2GB(`dd` + `/etc/fstab`), `tailscale up --ssh` + `serve`,
  `--provenance=false`, `restart: unless-stopped` — 전부 그대로

**바뀌는 것.**

- SSH 사용자가 `ec2-user` → **`ubuntu`**
- 도커는 **공식 apt 저장소**(`docker-ce` + `docker-compose-plugin`). AL2023에 없던
  compose 플러그인을 aarch64 바이너리로 손수 내려받는 단계가 **없어진다** — 절차가 짧아졌다.
  저장소 줄의 arch는 `dpkg --print-architecture`로 받아 오타 여지를 없앤다
- **snapd를 지운다.** 0.5GB에서 100MB 안팎을 상주로 쓰는 건 아깝다. 캐노니컬 AWS 이미지는
  SSM 에이전트를 snap으로 넣지만, 이 인스턴스에는 IAM 인스턴스 프로파일을 붙이지 않아
  **SSM은 애초에 쓸 수 없다** — 잠겼을 때의 탈출구는 키 페어다(1절)
- `unattended-upgrades`가 기본으로 켜져 있다. 자동 재부팅은 기본값이 꺼짐이라 인스턴스가
  사라질 일은 없고, 도커 갱신 시 컨테이너가 한 번 재시작되며 폴링이 한 틱 빠질 수 있다.
  `next_poll_at`이 DB에 있어 재시작에 강하므로 알림 정확성에는 영향이 없다 (D-17)
- `dmesg`가 기본 제한(`dmesg_restrict`)이라 OOM 확인은 `sudo dmesg`다 —
  `deploy_check.sh`의 안내 문구를 그렇게 고쳤다

**기각**: 우분투 자체 패키지(`docker.io` + `docker-compose-v2`)는 설치가 두 줄로 끝나지만
버전이 배포판 주기에 묶인다. 공식 저장소는 줄이 길어지는 대신 도커가 직접 지원하는 버전을
쓴다 — 1인용 서버라 어느 쪽도 위험하지 않지만, 재현성이 나은 쪽을 택했다.

**개정 *(2026-08-10, 리전 이관 시 재구축)*: 실제로 올라간 것은 26.04 LTS(`resolute`)다.**
콘솔 기본값이 옮겨갔고, 24.04로 되돌릴 이유가 없어 그대로 썼다. **버전은 이 결정의 본질이
아니었다** — 고른 것은 "AL2023이 아니라 우분투"이고, 위의 "바뀌지 않는 것/바뀌는 것"은
버전과 무관하게 전부 유효하다. 확인한 것:

- `docker-ce`·`tailscale` 모두 `resolute` 저장소를 제공한다
- `deploy_guard.py`·`shutdown_guard.py`는 표준 라이브러리만, `deploy_check.sh`는
  `uname -m`만 쓴다 — 호스트 파이썬 버전에 묶이지 않는다
- 앱은 컨테이너 안 `python:3.12-slim`이라 호스트와 무관하다

그래서 절차서는 **버전을 박지 않고 "콘솔 기본값 LTS"로** 바꿨다. 위가 예고한
`unattended-upgrades`는 실제로 부팅 직후 dpkg 잠금을 잡아 설치를 한 번 막았다 —
대기 방법을 DEPLOY.md 2절에 적었다.

---

### D-43. iOS 재디자인을 채택하고 Phase 5로 분리한다 *(v13, Phase 4 종료 무렵)*

별 세션에서 피그마 MCP로 **iOS 전용 재디자인본**을 만들었다 (iPhone 14 Pro 393×852pt,
11화면 + iOS 심볼 세트: StatusBar/NavBar/HomeIndicator, Btn-Primary·Secondary·Destructive,
FieldRow/ListRow/Switch/Segment, **Cell-Empty·Sold·Past**, **Chip-Navy·Warn·OK·Muted·Red**).
문서가 프론트 재디자인을 예상하지 않았으므로 착수 전에 위치와 제약을 정한다.

**결정 ①: Phase 5로 분리한다 — Phase 4에 끼워 넣지 않는다.**
Phase 4의 코어는 배포와 **출근길 실기기 검증**이다. 검증 중에 화면을 갈아엎으면 실패했을 때
원인이 배포인지 디자인인지 분리되지 않는다. 재디자인은 하루면 되돌릴 수 있지만 출근길은
하루에 한 번뿐이다 — **되돌리기 비싼 쪽을 먼저 닫는다.**

**결정 ②: 백엔드 무변경이 전제다.** 11화면이 기존 7개 컴포넌트와 1:1로 대응하고 새 API
표면이 없다는 것이 검토에서 확인됐다. `/matrix` 스키마(7절)나 도메인 규칙(5절)을 건드려야
하는 요구가 디자인에서 나오면 **그건 Phase 5의 범위가 아니라 별도 합의 사항**이다.

**결정 ③: `seat-matrix.jsx`의 지위를 좁힌다.** 지금까지 이 파일은 "매트릭스 화면
프로토타입이자 verdict 규칙의 참조 구현"이었다(CLAUDE.md 참조 파일). 재디자인 후에는
**verdict 규칙의 참조로만 남는다** — 시각 디자인의 참조는 피그마다. 둘을 구분하지 않으면
"프로토타입과 다르게 생겼다"가 버그로 오해되고, 반대로 **판정 규칙이 달라진 것을 디자인
차이로 흘려보내게 된다.** 후자가 훨씬 위험하다.

**미정 — 착수 시 확인해야 하고, 임의로 정하지 않는다.**

- **`08 오프라인 캐시 (마지막 성공 조회)`의 데이터 출처.** 서버의 `last_cells_snapshot`을
  읽으려는 의도라면 **절대규칙 위반이다** — 그 값은 스케줄러만 기록·소비한다(D-13, D-17).
  현재 구현은 `api.js`가 `localStorage`에 캐시하고 `SeatMatrix.jsx`가 `stale` 플래그로
  `⚠ 오프라인 캐시`를 띄우는 방식이라 이미 적법하다. **그 구조를 재현하는 것이면 문제없다.**
- ~~**`05 지금 상태 (바텀시트)`가 새 데이터를 요구하는지.**~~ **답: 요구하지 않는다**
  *(이슈 #42)*. 이 화면에는 판정 요약이 아예 없다 — 입석/착석 세그먼트와 좌석 입력뿐이라
  D-46의 두 목록에도 영향을 받지 않는다. 범위 안이고 결정 ②에 걸리지 않는다.
  **판정 표시는 06·07·08 세 화면에만 있다.**
- ~~**iOS 전용 조정을 어디까지 허용할지.**~~ **답: 제한하지 않는다 — 대신 web 스킨을 남긴다**
  *(v20 → D-50)*. "393pt 고정으로 가면 맥 브라우저에서 확인하기 나빠진다"가 걱정이었는데,
  **맥이 기본으로 web 스킨을 받으므로** iOS 스킨은 393pt에 완전히 맞춰도 된다.
  맥에서 iOS를 눈으로 볼 때는 `?ui=ios`를 붙인다.

**함께 확정한 실무 제약**: 배포 시 `web/public/sw.js`의 `CACHE`를 올린다(`itx-shell-v1` →
`v2`). 올리지 않으면 iOS 홈화면 PWA가 옛 화면을 계속 보여줘 "재배포했는데 안 바뀐다"로
시간을 버린다. 그리고 **프론트 자동 테스트가 0개**이므로(전부 백엔드 테스트다) 안전망은
빌드 성공과 사람의 눈뿐이다 — CI(#21)의 `build` 잡이 Dockerfile 1단계에서 `vite build`를
돌리므로 그것이 최소선이고(별도 프론트 잡은 두지 않았다 → D-44), 화면 단위로 쪼개서
적용하는 이유도 이것이다.

### D-44. CI를 도입하고, 시크릿 검사 규칙을 훅과 공유한다 *(v14, Phase 4 E)*

**맥락**: Phase 4에서 손으로 겪은 실패가 세 개 있었고 전부 "자동으로 돌지 않아서" 생겼다.
① Docker Desktop이 꺼져 있어 Dockerfile 미검증 구간이 길어지고 결국 **M4의 첫 빌드가
첫 실행**이 됐다 ② 테스트 355개가 로컬에서만 돌았다 ③ 시크릿 훅(D-33)은
`git config core.hooksPath scripts/hooks`를 실행해야 켜지고, **켜는 것을 잊으면 아무것도
막지 못한다.** 훅을 만든 계기 자체가 `.env.example`에 시크릿이 채워진 사고 세 번이었다.

**결정 ①: CI만 도입하고 배포는 건드리지 않는다.** 이미지를 레지스트리에 밀지 않고 러너를
tailnet에 붙이지도 않는다(CD는 #22). 배포 경로를 바꾸는 것은 D-40 개정이 필요한 사안이고,
**출근길 검증이 끝나기 전에 배포 경로를 흔들면 안 된다.**

**결정 ②: arm64는 네이티브로 검증한다.** 저장소가 public이라 `ubuntu-24.04-arm` 러너가
무료다. x86 러너 + QEMU로 가면 느린 것보다 **실제로 배포하는 아키텍처가 아니게 된다는 것**이
문제다(t4g = Graviton, x86 이미지는 `exec format error`로 죽는다 → D-42).
`--provenance=false`도 배포와 같은 조건으로 붙인다(→ D-40).

**결정 ③: 불변식을 CI와 배포 점검이 나눠 갖는다.** 이미지 쪽(arm64 / `ZoneInfo("Asia/Seoul")`가
사는지 / uid 1000 / `/healthz` 200 / `"폴링 스케줄러 시작"` 로그)은 CI가, 호스트 쪽(스왑,
루프백 퍼블리시, tailscale, 재시작 횟수)은 `scripts/deploy_check.sh`가 본다.
스케줄러 기동 로그는 **양쪽이 같은 문자열을 찾는다** — 그 줄이 사라지면 배포 점검
스크립트가 조용히 늑대소년이 되므로 CI가 함께 고정한다.

**결정 ④: 검사 규칙을 `scripts/secret_scan.py`로 뽑아 훅과 CI가 공유한다.** 훅은
"스테이지된 것"을 넘기는 얇은 껍데기가 되고 `PUBLIC_KEYS`·금지 경로는 그쪽으로 옮겼다.
규칙에 테스트를 붙였다 — **막아야 할 것을 막는지와 통과시켜야 할 것을 통과시키는지 양쪽**을
본다. 후자가 무너지면 훅이 짜증나서 `--no-verify`가 습관이 되고, 그게 훅이 실제로 죽는 경로다.

**★ CI는 훅을 대체하지 못한다.** 훅의 3겹 중 **핵심인 ②(`.env`의 실제 값이 커밋 내용에
들어갔는가)는 러너에 `.env`가 없어 원리적으로 불가능하다** — 대조할 원본이 없다.
CI는 그 검사를 건너뛰고 **건너뛴 사실을 출력한다**(조용히 통과시키지 않는다). 대신 CI는
스테이지가 아니라 **추적 파일 전체**를 보므로 "훅이 꺼진 클론에서 이미 들어와 버린 것"을
잡는다. 둘은 대체가 아니라 보완이다. `.env` 실제 값 쪽을 기계로 더 막고 싶으면 GitHub
Secret scanning / Push protection(public 저장소 무료)을 켜는 쪽이고, 그건 코드가 아니라 설정이다.

**작업 중 드러난 것 두 개 — 둘 다 D-33이 조용히 새던 구멍이다.**

1. **워크트리에서 훅의 핵심 검사가 꺼져 있었다.** `.env`는 gitignore 대상이라
   `git worktree add`로 만든 디렉터리에 복사되지 않고, 예전 코드는 파일이 없으면 **그냥
   통과**했다. **Phase 4 배포 작업을 전부 워크트리에서 했으므로 그 기간 ② 방어가 없었다.**
   이제 `--git-common-dir`로 메인 체크아웃의 `.env`를 찾고, 그래도 못 찾으면 침묵하지 않고
   경고한다. (실제 유출은 없었다 — 지문 대조로 옮겼고 값을 파일에 쓴 적이 없다)
2. **`itx-prod.env` 같은 이름이 금지 패턴을 빠져나갔다.** 기존 패턴은 파일명이 `.env`로
   **시작**할 때만 걸렸는데, 배포 때 실제로 만든 파일 이름이 `~/itx-prod.env`였다
   (DEPLOY.md 4절). `.env`로 **끝나는** 형태를 추가했다.

**하지 않은 것**: 프론트 전용 잡. `npm ci` + `vite build`는 Dockerfile 1단계에 있어
`build` 잡이 이미 검증한다 — 따로 두면 **두 곳에서 빌드하며 노드/의존성 버전이 갈린다.**
`main`/`dev` 보호 규칙에 CI 통과를 필수로 걸지는 **미정**(저장소 설정이라 소유자가 켠다).

**부수 효과 하나**: `test` 잡은 `uv sync --locked`를 쓴다. Dockerfile은 `--frozen`(락 그대로,
검사 없음)이라 **락을 갱신하지 않고 `pyproject.toml`의 의존성을 고치면 이미지가 조용히 옛
의존성으로 빌드된다.** 그 함정은 `--locked`를 쓰는 CI에서만 드러난다.

### D-45. 매진 판정은 `clear_until`이 아니라 남은 구간 전체를 본다 *(v15, Phase 4 실사용)*

**어떻게 드러났나**: 배포 첫날 **퇴근길**(영등포→천안)에 구독을 만들어 봤더니, 탑승 구간
(영등포-수원)만 매진이고 그 이후는 비어 있는 상황에서 **"앉을 좌석 없음 · 지하철 환승이
나을 수 있음"**이 떴다. 정작 몇 정거장 뒤부터는 천안까지 앉아서 갈 수 있는 좌석이 있었다.

출근길(천안→영등포)은 **탑승 직후가 가장 한가하고 뒤로 갈수록 팔린다.** 퇴근길은 정확히
반대다 — **탑승 구간이 가장 붐빈다.** 방향이 뒤집히면 데이터의 모양도 뒤집히는데, 목업
노선과 테스트가 전부 출근길 방향이라 **이 모양을 덮는 테스트가 하나도 없었다.**

**원인**: `all_sold_after_current`를 `clear_until`로 판정했다.

```python
all_sold = all(s.clear_until_idx <= start_idx for s in enriched)   # 틀렸다
```

`clear_until`은 **실효 시작 구간부터 연속으로** 빈 구간만 센다. 시작 구간이 팔려 있으면
뒤가 아무리 비어 있어도 `start_idx`를 그대로 돌려준다. 그 값으로 매진을 판정하니
"시작 구간 전 좌석 매진"이 **"남은 전 구간 전 좌석 매진"으로 뒤집혔다.**

**5절의 정의는 원래부터 "남은 전 구간 × 전 좌석 매진"이었다** — 코드가 문서보다 좁게
구현된 것이므로 설계 변경이 아니라 **버그**다. 다만 정의가 한 줄이라 이 함정을 막지
못했으므로 5절에 "`clear_until`로 판정하면 안 된다"를 명시했다.

**고친 것**: 남은 구간 `[start, alight)` 안에 빈 셀이 하나도 없을 때만 `True`.
회귀 테스트는 **퇴근길 노선을 픽스처로** 쓴다 (`Test시작_구간만_매진일_때`) — 같은 종류의
누락을 막으려면 방향이 다른 데이터가 테스트에 있어야 한다.

**영향 범위가 화면에서 끝나지 않았다**: 이 플래그는 `ALL_SOLD` 발송 조건이기도 하다
(8절, `alerts.py`). 즉 **틀린 판정이 푸시로 나갔다.** 조용히 틀리는 지점이 알림까지
번지는 경로를 실사용으로 확인한 첫 사례다.

**아직 미정 — 임의로 정하지 않는다.** 이 수정으로 잘못된 환승 권유는 사라졌지만
**추천은 여전히 0건**이다. 추천 대상이 `clear_until > start`로 제한돼 "지금 당장 앉을 수
있는 좌석"만 나오기 때문이다. "지금은 못 앉지만 수원부터 앉을 수 있는 좌석"을 추천하려면
결정이 필요하다:

- **랭킹 기준** — 지금부터 앉을 수 있는 짧은 구간과 나중부터 앉을 수 있는 긴 구간 중
  무엇이 위인가. 지연 착석은 **그때까지 그 좌석이 남아 있을 보장이 없다** — 5절의
  "빈 좌석 ≠ 착석 가능" 한계가 시간이 갈수록 커진다
- **응답 스키마** — `SeatRecommendation`에 "언제부터"가 없다(7절). 필드를 추가하지 않고
  추천만 내보내면 **사용자가 지금 앉을 수 있다고 오해한다** — 그쪽이 더 위험하다
- **알림** — 지연 착석만 있을 때 `SEATS_AVAILABLE`을 보낼지. 종류는 5개로 고정이므로
  새 종류가 아니라 다이제스트 상세도 문제다 (D-17의 손잡이)

### D-46. 추천은 두 목록이다 — "지금 앉을 수 있는 자리"와 "몇 정거장 뒤부터" *(v16, Phase 4 실사용)*

**맥락**: D-45로 잘못된 환승 권유는 사라졌지만 **추천은 여전히 0건**이었다. 퇴근길처럼
탑승 구간이 매진이면 "지금 당장 앉을 수 있는 좌석"이 없어서, 몇 정거장 뒤부터 하차역까지
계속 비어 있는 좌석이 있어도 화면이 아무것도 제안하지 못했다.

**결정 ①: 두 목록을 유지하고 합치지 않는다.** `move_to`(지금) / `move_to_later`(나중).
합치면 정렬 결과에 따라 **1순위가 "지금 못 앉는 자리"가 될 수 있고**, 그러면 화면에서
그 구분을 다시 만들어내야 한다. 소유자 선택 (2026-08-06).

**탈락한 안 2개**:
- *즉시 착석 우선* — 지금 앉을 수 있는 좌석이 있으면 그것만 보여준다. 안전하지만
  "수원부터는 끝까지 앉아 갈 자리가 있다"는 정보를 버린다
- *최장 구간 우선(단일 목록)* — 직관적이지만 1순위가 지금 못 앉는 자리가 되는 문제

**결정 ②: 지연 착석 정렬은 가장 긴 연속 구간 우선, 동률이면 일찍 앉을 수 있는 쪽.**
`longest_free_run(cells, start, alight)`이 순수 함수로 계산한다. 동률 규칙의 근거는
5절의 **"빈 좌석 ≠ 착석 가능"** 한계다 — 판매 데이터상 비어 있어도 다른 입석 승객이
앉아 있을 수 있고, **그 불확실성은 시간이 갈수록 커진다.** 같은 길이면 가까운 쪽이 낫다.

**결정 ③: 응답에 `clear_from_idx`("언제부터")를 반드시 싣는다.** 선택 사항이 아니다 —
필드 없이 추천만 내보내면 **사용자가 지금 앉을 수 있다고 오해한다.** 그건 추천을 안 하는
것보다 나쁘다. 화면·알림 문구 양쪽에서 이 값을 쓴다.

**결정 ④: 지연 착석만 있어도 `SEATS_AVAILABLE`을 보낸다.** 소유자 선택.
폴링은 정차역 도착 10분/4분 전이므로 "수원부터 4호차 1A"를 미리 알면 **그 호차로 걸어가
대기할 수 있다** — 행동 가능한 정보다. **알림 종류는 5개로 고정**이므로(8절) 새 종류가
아니라 다이제스트 상세도 문제다 (D-17의 손잡이).

**★ 구현 중 테스트가 잡아낸 것 — 해시에 무조건 넣으면 스퍼리어스 발송이 난다.**

지연 착석 1순위를 `last_verdict_hash`에 넣지 않으면 "수원부터 앉을 수 있는 자리가 생겼다"가
상태 변화로 잡히지 않아 **퇴근길에는 알림이 영원히 안 온다.** 그래서 넣었더니
`test_하위_추천만_바뀌면_침묵한다`와 `test_열차_진행만으로는_연장_알림이_나가지_않는다`가
동시에 깨졌다 — **지금 앉을 자리가 있는데도** 지연 목록의 변동만으로 알림이 나갔다.
D-16이 막으려던 바로 그 스퍼리어스 발송이다.

결론: **지연 착석 1순위는 `move_to`가 비었을 때만 해시에 넣는다.** 앉을 수 있으면 그냥
가서 앉으면 되므로 그 변동은 의사결정과 무관하다. 즉 **지연 착석은 지금 앉을 자리가 없을
때만 의사결정에 관여한다.** 이 원칙이 화면(요약 문구 대체 조건)에도 그대로 적용된다.

**배포 시 주의 — 첫 폴링에 알림 1건이 더 나간다.** 해시 튜플이 바뀌었으므로 DB에 남아
있는 `last_verdict_hash`(옛 튜플로 계산된 값)와 반드시 달라진다. 활성 구독마다 한 번
`changed=True`로 잡혀 알림이 나가고, 그 뒤로는 정상이다. 베이스라인 발송과 같은 성질이라
해롭지 않지만 **모르고 받으면 오작동으로 읽힌다.**

**함께 한 것**: `web/public/sw.js`의 `CACHE`를 `itx-shell-v2`로 올렸다. 올리지 않으면
홈화면 PWA가 앱을 완전히 종료할 때까지 옛 화면을 보여준다.

**Phase 5(iOS 재디자인)와의 관계**: 프론트 변경을 요약 문구와 지연 착석 목록 한 줄로만
제한했다. 재디자인이 어차피 이 영역을 다시 그리므로 지금 화면을 크게 손대는 것은 낭비다.
`move_to_later`가 응답에 있다는 사실만 D-43의 화면 매핑에서 반영하면 된다.

> **추가 (이슈 #42)**: 그 반영을 실제로 했다. 피그마 `ios` 페이지의 06·07·08이 두 그룹으로
> 갈렸고, "언제부터"를 붙이는 **`iOS/Chip-Later`** 심볼이 늘었다. 규칙과 문구 분기는
> `31:200`의 **"판정 표시"** 섹션에 있다. 11절 Phase 5도 함께 고쳤다.
>
> **동기화하면서 드러난 것**: `move_to_later`가 **1건일 때 화면이 같은 좌석을 두 번 말한다**
> (요약 줄과 지연 목록이 같은 좌석을 가리킨다). 목록이 2건 이상이면 자연스럽고, 코드가 두 줄을
> 모두 렌더하므로 **피그마도 그대로 그려 뒀다** — 조용히 고치면 이 중복이 보이지 않는다.
> 1건일 때 목록을 접을지는 Phase 5에서 정한다.

### D-47. 운행 중인 구간은 조회하지 않는다 — 위치와 "팔 수 있는 첫 구간"은 다른 값이다 *(v17, Phase 4 실사용)*

**어떻게 드러났나**: 출근길(2026-08-07, ITX-마음 4202, 천안→영등포)에 **천안을 출발한
직후부터** 천안-평택 구간이 매진으로 표시됐다. 실제로 팔린 게 아니라 **이미 출발해서
코레일이 팔 수 없는 구간**이었다. EC2 로그가 출발 시각마다 한 구간씩 그대로 찍었다:

```
07:13:07  천안→평택 구간에 열차 4202 없음 → 전 좌석 판매로 간주   ← 07:12 천안 출발
07:27:17  평택→수원 구간에 열차 4202 없음 → 전 좌석 판매로 간주   ← 07:26 평택 출발
07:54:12  수원→영등포 구간에 열차 4202 없음 → 전 좌석 판매로 간주 ← 07:52 수원 출발
```

**한 번의 사고가 아니라 구조적이다.** 폴 포인트는 항상 *다음 역 도착 10·4분 전* =
**주행 중**이므로 출발 이후 **모든 폴링**이 이 조건에 걸린다. 07:14 폴링에서 `ALL_SOLD`가
실제로 발사됐고(07:08까지는 아니었다), 구간이 넘어갈 때마다 해시가 흔들려 07:36에 재발화했다.

**원인은 D-36이 아니라 그 앞이다.** 빈 응답을 '전 좌석 판매됨'으로 흡수하는 것(D-36)은
매진 구간에서는 옳다. 틀린 것은 **애초에 팔릴 수 없는 구간을 조회 범위에 넣은 것**이다.
`estimate_seg`가 **도착시각만** 보므로 출발 후에도 그 구간이 '현재 구간'으로 남고,
D-18의 실효 시작이 그 값을 그대로 썼다.

시발역은 완충조차 없다. `train_stop`에서 시발역은 `arrival`이 NULL이라 `get_stops()`가
출발시각을 도착시각으로 대신 쓴다 — "현재 구간이 되는 순간"과 "코레일이 못 파는 순간"이
**정확히 같은 시각**이다. 중간역은 정차 시간(평택 2분)만큼만 유효 창이 있다.

**결정: 위치와 판매 가능 시작을 분리한다.**

- `estimate_seg`(도착시각 기준) = **열차 위치**. 진행바·GPS가 쓴다. 그대로 둔다
- `sellable_seg_idx`(출발시각 기준) = **팔 수 있는 첫 구간**. 조회 범위·판정이 쓴다
- 규칙 한 줄: **출발했으면 다음 구간, 정차 중이면 그 구간**

부수 효과가 전부 옳은 방향이다 — 주행 중 구간 1개만큼 호출이 줄고(10절 호출 예절),
화면에서 그 구간이 `seg.idx < startIdx`에 들어가 **기존 흐림 처리에 자동으로 걸리며**,
`my_seat_sold_from`이 이미 지나온 역을 가리키지 않는다.

**함께 정한 것 ①: 빈 조회 범위는 '판정 불필요'다.** 이용 구간의 마지막 구간을 달리는
중이면 팔 수 있는 구간이 하나도 없다. 예전 클램프(`alight_idx - 1`)로 되돌리면 바로 그
'팔 수 없는 구간'을 조회하게 되어 이 버그가 마지막 구간에서 되살아난다. 그래서 조회 0회 +
`Verdict.decision_needed = False`로 답한다.

> **`all([])`은 참이다.** 빈 매트릭스에 매진 판정식(D-45)을 그대로 돌리면
> `all_sold_after_current`가 **공허하게 참**이 되어 하차 직전에 "지하철 환승 고려"가 나간다.
> 반드시 분기해야 하는 이유가 이것이다. 알림은 베이스라인(D-20)까지 포함해 전부 침묵한다 —
> 취할 행동이 없는 시점의 알림은 종류를 불문하고 오발송이다.

**함께 정한 것 ②: 문구의 기준역은 `stops[start]`다** (소유자 선택, 2026-08-07).
구간 `i`는 `stops[i] → stops[i+1]`이므로 "구간 i가 비었다"는 곧 "`stops[i]`부터 앉을 수
있다"이다. 알림 제목과 화면 문구만 한 역 뒤를 가리키고 있었다 — D-46의 지연 착석 문구는
이미 `station(clear_from_idx)`를 쓰고 있었으므로 **같은 상황에 두 가지 답이 나오던 자리**다.
한 역 늦게 안내하면 그 역에서 앉을 기회를 그대로 놓친다.
**피그마 iOS 재디자인본도 같은 오류를 갖고 있었고 함께 고쳤다** (이슈 #42) —
06·08의 헤드라인이 `영등포부터`였는데 매트릭스상 시작은 `수원`이었다.

**이름도 함께 고쳤다.** 응답 최상위 `current_seg_idx`(열차 위치)와 `verdict.current_seg_idx`
(판정 시작)가 **이름이 같으면서 뜻이 다른 것**이 이 버그의 씨앗이었다. 후자를
`start_seg_idx`로, `build_verdict`/`query_range`의 인자도 `sellable_seg_idx`로 바꿨다.

**목업이 또 가리고 있었다** (D-31/D-32와 같은 종류). `korail_mock`과 테스트 픽스처가
정차 시간 없이 도착시각만 갖고 있어 "정차 중"과 "주행 중"을 애초에 구분할 수 없었다.
정차 3분을 넣는 것이 이 수정의 전제였다.

**남은 것 — 이번 범위 밖**: 같은 출근길 로그에 `ERR911081 좌석선택 예약불가`로 매트릭스
전체가 **500**이 된 기록이 4건 있다(출발 직후 15~60초 창). 코레일은 출발한 구간을 두
단계로 닫는다 — 먼저 `ERR911081`, 그 뒤 목록에서 제거. 이 결정으로 그 구간을 아예 부르지
않으므로 증상은 사라지지만, **한 구간의 실패가 매트릭스 전체를 죽이는 구조**는 그대로다
(`ERI411321` → `ERR911081`로 실패 코드가 두 번 바뀌었다). 구간 단위 실패 격리는 별도 이슈다.

### D-48. 한 구간의 조회 실패가 매트릭스 전체를 죽이지 않는다 *(v18, Phase 4 실사용 → 이슈 #40)*

**어떻게 드러났나**: D-47을 파던 중 같은 아침 로그에서 발견했다. `/matrix`가 **500**을
낸 기록이 4건 있었다 — 전부 열차가 역을 **출발한 직후 15~60초** 창이다.

```
07:12:55  GET …/matrix … 500   ← KorailApiError: ERR911081: 좌석선택 예약불가
07:13:07  GET …/matrix … 200   ← 12초 뒤. 이번엔 "열차 없음"(D-47 경로)
07:26:21  GET … 500 / 07:26:28  GET … 500 / 07:26:38  GET … 500   ← 사용자가 3번 재시도
```

**코레일은 출발한 구간을 두 단계로 닫는다.** 먼저 `ERR911081 좌석선택 예약불가`,
그 뒤 `ScheduleView` 목록에서 열차 자체를 제거. D-47이 앞 단계를, 이 결정이 뒷단을 맡는다.

**원인**: `fetch_segment_maps`의 `asyncio.gather`에 `return_exceptions`가 없어 첫 예외가
그대로 올라갔고, **이미 성공적으로 받아온 다른 구간의 좌석표까지 버려졌다.**
`ERR911081`은 `SOLD_OUT_CODES`(`ERI411321`)에도 문구 힌트에도 걸리지 않는다.

**이슈 #9/D-36이 고쳤던 실패 모드가 다른 코드로 재발했다.** 같은 자리에서 실패 코드가
두 번 바뀐 셈이다. **코드/문구 화이트리스트로 쫓아가는 방식의 한계**가 드러났다 —
D-36은 "코드값을 확보하면 문구 의존을 줄인다"고 했지만 실제로는 새 코드가 계속 나온다.

**결정: 사유를 판별하지 말고 구조로 격리한다.** D-36이 매진 한 가지 사유에만 적용했던
판단("한 구간의 사고가 전체를 삼키면 안 된다")을 **실패 사유 전반**으로 넓힌다.

- `fetch_segment_maps` → `SegmentMaps(maps, failed)`. 실패한 구간만 담고 나머지는 살린다
- **전 구간이 실패하면 첫 예외를 그대로 올린다** — 보여줄 것이 없을 때는 실패가 맞고,
  `CredentialsRequired`(→409) 같은 타입이 호출부의 상태코드 매핑에 필요하다
- `ERR911081`을 `SOLD_OUT_CODES`에 넣지 **않는다.** "예약불가"의 사유가 매진이라는 보장이
  없고, 매진으로 읽으면 그 구간이 조용히 '전 좌석 판매됨'이 된다 (#35가 밟은 함정)

**판정에서의 취급 — "확인 한계"다** (소유자 선택, 2026-08-07).

| 값 | 실패 구간에 대해 | 이유 |
|---|---|---|
| `clear_until` | 실패 구간에서 **멈춘다** | 그 뒤를 확인하지 못했다. "여기까지 확인됨"이 정확한 답이다 |
| `all_sold_after_current` | 실패 구간이 있으면 **False** | 모르는 것을 매진이라 부르지 않는다. D-47의 `all([])` 분기와 같은 논리 |
| `move_to_later` | 그대로 동작 | 실패 구간 뒤의 빈 구간은 **실제로 관측한 값**이므로 추천해도 정직하다 |

> 탈락한 안: *빈 것으로 취급* — 추천은 살아남지만 **없는 자리를 권한다.** 앉으러 갔는데
> 사람이 있는 실패는 이 도구가 가장 피해야 할 방향이다 (5절 "빈 좌석 ≠ 착석 가능").

**스케줄러는 부분 실패 시 알림을 보류하고 해시를 갱신하지 않는다.** 실패한 관측으로
해시를 덮으면 **실패 → 복구가 그 자체로 "상태 변화"** 가 되어 좌석이 하나도 안 팔렸는데
알림이 두 번 나간다. 해시를 그대로 두면 다음 완전한 조회가 **마지막 완전한 관측**과
비교되므로 그 요동이 애초에 생기지 않는다. `fail_count`도 건드리지 않는다 —
`FETCH_FAILED`(D-34)는 전 구간 실패의 신호다. 화면은 반대로 부분 결과를 그대로 보여준다:
사람이 직접 보고 판단하는 경로이므로 "수원까지만 확인됨"이 유용하다.

**프론트까지 함께 고쳐야 끝난다.** 백엔드만 고치면 실패 구간이 채움값(판매됨)으로 내려와
화면이 빨간 셀로 그린다 — **원인을 옮기기만 하는 셈**이다. 흐림 처리는 `seg.idx < startIdx`라
범위 중간의 실패에는 걸리지 않는다. D-31이 같은 지적을 한 번 했고 D-47이 `decision_needed`로
또 다뤘으므로 이번이 세 번째다. 색만 쓰지 않고 **물음표를 함께 찍는다** — 색각 이상·흑백
스크린샷에서 매진과 뭉개진다. 변경 범위는 셀 상태 + 요약 한 줄로 제한했다 (D-46 선례,
Phase 5가 이 화면을 다시 그린다).

> **추가 (이슈 #42)**: 피그마에 **`iOS/Cell-Failed`** 심볼을 만들어 뒀다
> (`#fdf3e7` / `#e8c9a0` + `?` — 웹 구현과 같은 값). **아직 어느 화면에도 배치하지 않았다** —
> 06·07은 D-46의 두 그룹을 보여주는 데 쓰고 있어서, 한 화면에 서로 다른 이야기를 두 개 넣으면
> 둘 다 흐려진다. 부분 실패 화면은 06의 변형으로 Phase 5에서 그린다.

### D-49. 내 자리는 매트릭스 최상단에 고정하고, 필터로 감추지 않는다 *(v19, 이슈 #33)*

**맥락**: 착석 후 매트릭스를 열면 **내 자리가 매번 다른 줄에 있었다.** 행 순서가
`clear_until` 내림차순이라, 내 자리가 팔릴수록(= 확인이 가장 급한 순간) 아래로 밀린다.
정작 그때 화면에서 제일 먼저 찾아야 하는 줄이 그 줄이다. 흔들리는 열차 안에서 눈으로
스캔하게 만드는 것은 10절이 세그먼트를 44pt로 키운 이유와 정확히 반대다.

**결정 ①: 착석 중이면 내 자리를 최상단에 고정한다.** 나머지 순서는 그대로다
(`clear_until` 내림차순 → 내 호차 근접순 → 좌석번호). 입석에는 적용되지 않는다 —
고정할 "내 자리"가 없다.

**결정 ②: 내 자리는 `하차역까지 빈 좌석만` 필터의 대상이 아니다.** 소유자 선택.
필터를 켜는 상황이 곧 **"내 자리가 팔려서 대안을 찾는" 상황**인데, 팔린 내 자리는
`clear_all`이 아니므로 **바로 그때 화면에서 사라진다.** 비교 기준이 없어지면 후보가
내 자리보다 나은지 판단할 수가 없다 — 필터의 목적 자체가 무너진다.

**★ 최상단 행의 뜻이 바뀐다는 것이 이 변경의 진짜 비용이다.**

지금까지 1행은 **"가장 오래 앉을 수 있는 좌석"** 이었다. 사실상 추천 1순위로 읽힌다.
내 자리를 올리면 1행이 추천으로 오독될 수 있다 — **D-46이 막으려던 것과 같은 종류의
오독**이다(구분이 사라져서 "지금 앉을 수 있는 자리"인지 알 수 없게 되는 것).
그래서 내 자리 행 아래에 **2px 구분선**을 넣어 두 번째 행부터가 후보임을 보인다.
`내자리` 태그만으로는 부족하다 — 태그는 그 줄이 무엇인지 말할 뿐, **그 아래가 다른
종류라는 것**은 말하지 않는다.

**범위**: 표시 순서만 바꾼다. `/matrix` 스키마도 도메인도 건드리지 않았다 —
추천(`move_to` / `move_to_later`)은 서버가 계산하며 내 좌석을 애초에 후보에서 제외한다
(`candidates = [s for s in enriched if s.key != my_key]`). 즉 **이 변경은 판정에 영향이 없다.**

**함께 한 것**: `web/public/sw.js`의 `CACHE`를 `itx-shell-v3`으로 올렸다. 올리지 않으면
홈화면 PWA가 앱을 완전히 종료할 때까지 옛 화면을 보여준다 (D-46과 같은 이유).

### D-50. web과 iOS를 스킨으로 나눈다 — 문구는 core가 한 번만 만든다 *(v20, 이슈 #44)*

**맥락**: 피그마에 `web`(480px)과 `ios`(393pt) 두 페이지가 다 있는데 코드는 web 한 벌뿐이라,
Phase 5에서 iOS를 적용하면 **web이 사라진다.** 소유자는 둘 다 유지하고 접속 기기에 따라
알아서 하나가 제공되기를 원했다 — web은 기능 패리티만, iOS는 UI/UX 개선을 계속.

**결정 ①: 한 번들 + 런타임 스킨 분기.** 배포 1개, `sw.js` 캐시 1개, 백엔드 무변경.

**탈락한 안 2개**:
- *Vite 멀티 엔트리 + 서버 UA 분기* — 백엔드를 건드려야 하고(D-43 결정 ② 위반) PWA
  매니페스트·서비스워커 스코프가 둘로 갈린다
- *CSS 미디어쿼리만으로 반응형* — **불가능하다.** iOS 재디자인은 "좁은 web"이 아니라
  StatusBar/NavBar/HomeIndicator·바텀시트·Segment가 있는 **다른 컴포넌트 구조**이고,
  탑승 등록을 네 단계로 쪼갠다. CSS로 우겨넣으면 iOS 디자인을 희석하게 된다

**결정 ②: 스킨은 서버 응답을 해석하지 않는다.** 판정 문구와 매트릭스 행 순서는
`core/format.js`가 **문장 조각 배열**(`[{t, em}]`)로 돌려주고, 스킨은 강조를 어떻게 그릴지만
정한다. 글리프(`⚠`)도 core가 넣지 않는다 — 그건 스킨의 어휘다.

> **이게 이 결정의 전부다.** 스킨이 각자 `move_to` / `move_to_later` / `clear_from_idx` /
> `decision_needed`를 해석해 문장을 만들면 두 벌이 반드시 갈리고, 그러면 뒤처진 쪽이
> **"못생긴" 상태가 아니라 "틀린 정보를 보여주는" 상태**가 된다. 그건 D-43 결정 ③이
> 경고한 실패다 — 판정 규칙이 달라진 것을 디자인 차이로 흘려보내는 것.
> 행 순서(D-49)도 같은 이유로 core에 있다. 두 스킨이 다른 순서를 보여주면 같은 종류의 사고다.

**결정 ③: 라우팅은 공유하고, 하위 단계는 스킨 안의 상태다.** iOS가 탑승 등록을
`02 → 03 → 04 → 05` 네 단계로 쪼개도 `App.jsx`의 `phase`는 5개 그대로다
(`loading`/`login`/`setup`/`matrix`/`settings`). 화면 개수가 11 vs 11로 안 맞는 것이
문제가 아니라 **당연한 것**이 된다.

**결정 ④: 기준은 "iOS 기기냐 아니냐"다.** 아이폰·아이패드만 `ios`를 받고 **그 외 전부**가
`web`이다 — 맥·윈도우·리눅스 데스크탑은 물론 **안드로이드 폰도 `web`**이다. iPadOS는 맥 UA로
위장하므로 `maxTouchPoints`로 가른다(`Macintosh` 조건이 함께 있어야 터치 윈도우 노트북이
잘못 걸리지 않는다). `?ui=`로 강제하고 `localStorage`에 고정한다.
**이것이 D-43 미정 ③의 답이다** — "393pt 고정으로 가면 데스크탑 브라우저에서 확인하기
나빠진다"는 걱정은 web 스킨을 데스크탑 기본값으로 남기는 것으로 닫힌다.

> *v20 보강*: 처음 이 결정을 적을 때 "맥"이라고 좁게 썼는데 **틀린 표현이었다.** 코드는
> 처음부터 iOS 여부만 봤다. **폼팩터로 가르지 않는 이유**도 함께 남긴다 — `ios`는 "모바일"이
> 아니라 iOS 관용구이고, `web`은 `max-width: 480`이라 이미 폰 폭이며(Phase 1~4의 아이폰
> 화면이 그것이다), `pointer: coarse` + 폭 판별은 데스크탑 창을 좁힐 때 스킨이 튄다.
> **안드로이드가 실사용에 들어오면 `ios`에 얹지 말고 `skins/android/`를 만든다.**

**결정 ⑤: web은 "동결"이 아니라 "기능 패리티 유지"다.** 동결이라고 부르는 순간 조용히 썩고,
정작 맥에서 디버깅할 때 못 쓰게 된다. 배포 전 `?ui=web`으로 한 번 눈으로 보는 것을 Phase 5
체크리스트에 넣었다.

**이번 범위는 구조뿐 — 동작은 그대로다.** `skins/ios/`는 web 스킨을 전개(spread)로 재수출하므로
아이폰에서도 지금과 똑같이 보인다. Phase 5에서 화면을 하나씩 추가하면 그 화면만 iOS로 바뀐다.
폴백을 두지 않으면 **"iOS 스킨을 만드는 동안 아이폰에서 앱이 반쪽이 되는" 기간**이 생긴다.

**비용을 숨기지 않는다**: 화면을 두 벌 유지하고, 기능이 늘면 web에도 최소한의 배선이 필요하다.
두 스킨 다 번들에 들어가지만 1인용 tailnet이라 무의미한 크기다(`React.lazy`는 PWA 콜드
스타트에 깜빡임이 생겨 쓰지 않는다).

**함께 한 것**: `core/format.js`에 스모크를 붙였다 (`web/test/format.smoke.mjs`,
`npm run smoke`, 의존성 없음). 프론트 자동 테스트가 0개라는 원칙(13절)의 **의도적 예외**다 —
이 파일만은 틀리면 **두 스킨이 같이 틀린다.** CI에 붙이는 것은 별도 판단으로 남겼다
(`test` 잡이 파이썬 전용이다). `sw.js`의 `CACHE`는 `itx-shell-v4`.

### D-51. CD — 러너를 tailnet에 들여보낸다(push), 재배포 가드는 시각이 아니라 폴 포인트 *(v21, 이슈 #22)*

CI(D-44)까지 왔지만 **배포는 여전히 M4가 있어야만 됐다.** 손이 여섯 번 가고, 여행 중에는
고쳐도 올릴 수가 없다. 남은 한 칸 — "CI가 이미 만드는 그 이미지를 EC2까지" — 을 자동화했다.

**결정 ①: push 방식(Tailscale Action). D-40은 개정하지 않는다.**

EC2 인바운드는 0개고(D-10, D-38) 러너는 공개 인터넷에 있다. 갈림길은 둘이었다:

| | **push** (Tailscale Action) | **pull** (GHCR) |
|---|---|---|
| D-40 "레지스트리 안 쓴다" | **유지** | 개정 필요 |
| 러너가 tailnet에 | 들어온다 (`tag:ci`) | 들어오지 않는다 |
| 이미지 전송 | 러너 → EC2 ~70MB (DERP면 느릴 수 있다) | EC2가 pull (레이어 캐시) |
| 배포 시점 | 명시적 (워크플로가 끝나면 끝) | 폴링 지연, 또는 결국 트리거용 SSH |
| EC2에 추가되는 것 | 없음 | 폴링용 timer/cron |

**push를 택했다.** 결정적인 것은 "**지금 손으로 하는 것과 같은 명령**"이라는 점이다 —
DEPLOY.md 6·9절이 폴백으로 그대로 유효하고, 실패했을 때 어디를 봐야 하는지가 이미 몸에 있다.
pull은 저장소가 public이라 GHCR이 무료이고 이미지에 시크릿이 없으므로 **D-40의 기각 근거가
실제로 약해진 것은 맞지만**, 그 대가로 EC2에 상주 프로세스가 생기거나(폴링) 결국 트리거용
SSH가 필요해져 tailnet을 안 쓰는 것도 아니게 된다. 부품이 하나 느는 쪽을 피했다.

**대가는 tailnet에 CI 노드를 들이는 것**이고, ACL로 좁혀 갚는다 — `tag:ci`에 허용된 것은
`korail-matrix:22` 하나뿐이고, Tailscale SSH 규칙도 `users: ["ubuntu"]`로 못 박는다.

> **이 과정에서 EC2 노드에 `tag:server`를 붙이게 된다.** Tailscale SSH는 `dst`에 사용자를
> 쓰면 `src`가 같은 사용자여야 해서(`users in dst are only allowed from the same user`),
> 태그에서 출발하는 규칙은 목적지도 태그여야 하기 때문이다. **부작용이 하나 있다** —
> 태그가 붙은 노드는 `autogroup:self`에 더 이상 잡히지 않으므로 **내 기기 → 서버 SSH 규칙을
> 따로 남기지 않으면 스스로 잠긴다** (인바운드 0개라 되돌릴 길이 없다). 절차는 DEPLOY.md 9절.
> 덤으로 태그 노드는 key expiry가 적용되지 않아, 3절이 걱정하던 만료 침묵이 사라진다.
OAuth 시크릿이 새도 피해가 거기서 끝난다. 러너는 매번 새 기계라 SSH host key TOFU가 주는
것이 없다 — **이 연결의 신원 보증은 ACL이지 host key가 아니다**(워크플로에 그렇게 적었다).

**결정 ②: 재배포 가드는 시각이 아니라 `next_poll_at`을 본다.**

자동 배포 = 컨테이너 재시작이다. 먼저 떠오른 것은 "07:00~09:30에는 배포하지 않는다"였지만,
그건 **통근 시간이 바뀌면 조용히 낡는 매직 넘버**다(원칙 1의 정신). 위험한 것은 아침이 아니라
**임박한 폴 포인트**다 — DEPLOY.md 9절이 이미 "폴 포인트 직전 재배포는 그 한 번을 놓칠 수
있다"고 적고 있었고, 막아야 할 것은 정확히 그 구간이다.

`scripts/deploy_guard.py`가 배포 직전 서버 DB에서 **10분 안에 폴이 잡힌 활성 구독**을 세고,
있으면 멈춘다. D-19가 재시작 내구성을 위해 이미 만들어 둔 포인터를 그대로 재사용한다.
구독이 없는 날은 새벽이든 아침이든 그냥 배포된다.

- **확신할 때만 막는다.** DB가 없거나·스키마가 없거나·잠겨서 못 읽으면 통과시킨다.
  모르는 것을 이유로 막으면 CD가 "영영 안 도는" 쪽으로 고장 나고, 그 상태는 가드가 없던
  어제보다 나쁘다. 막는 것은 **읽어서 확인했을 때뿐**이다
- **가드가 서버를 건드리기 전에 돈다.** 워크플로가 스크립트를 stdin으로 밀어 넣으므로
  (`ssh … 'python3 -' < scripts/deploy_guard.py`) 보류되면 EC2의 작업 트리조차 손대지 않은
  상태로 끝난다. 같은 명령을 손으로 돌려 "지금 배포해도 되나"를 미리 볼 수도 있다
- 호스트에는 uv도 앱 의존성도 없어 **표준 라이브러리만** 쓴다. `next_poll_at`이 KST aware
  ISO8601 문자열이라(`to_db`) `datetime.fromisoformat`으로 그대로 읽힌다
- GitHub Environments의 수동 승인도 검토했지만 **매 배포마다 손이 가면 결국 "버튼 하나"**이고,
  그건 지금의 수동 배포와 다르지 않다. 승인자를 두지 않은 이유다

**결정 ③: 롤백은 이미지와 작업 트리를 함께 되돌린다.**

`deploy_check.sh`가 **✗ 하나라도 있으면 종료 코드 1**로 끝나도록 고쳤다(지금까지는 항상 0이라
워크플로가 판정할 수 없었다). 실패하면 CD가 `:previous` 이미지 + 직전 커밋으로 되돌리고
재점검한다. 조용히 틀리는 자리 셋을 각각 막았다:

- **경고(`!`)는 종료 코드에 넣지 않는다.** 넣으면 "이미지 아키텍처 ?" 같은 사소한 것에
  자동 롤백이 걸린다
- **`compose up` 직후에 점검하지 않는다.** HEALTHCHECK의 `start-period`가 20초라
  멀쩡한 배포가 롤백된다. healthy를 기다린 뒤 점검한다
- **롤백은 "transfer 성공 후 실패"로 좁힌다.** 단순한 `if: failure()`면 폴 포인트 가드에서
  멈춘 경우에도 켜지는데, 그때 서버의 `:local`은 **잘 돌고 있는 최신 이미지**다 — 되돌리면
  멀쩡한 서버를 강등시킨다
- **이미지만 되돌리면 짝이 안 맞는다.** 옛 이미지가 새 compose·새 스크립트로 뜬다.
  같은 이유로 정상 배포에서도 `git pull`이 아니라 `git reset --hard <sha>`를 쓴다 —
  그 사이 main이 더 진행했으면 `pull`은 이미지와 다른 커밋을 가져온다

**함께 한 것**: `ci.yml`을 `workflow_call`로 열고 push 트리거에서 `main`을 뺐다. main 푸시는
CD가 CI를 게이트로 부르므로, 남겨두면 같은 커밋에서 CI가 두 번 돈다. 서버에 커밋별 이미지
태그를 남기지 않고 **OCI 라벨(`org.opencontainers.image.revision`)로 대신한다** — 10GB EBS에
이미지가 쌓이면 먼저 죽는 것은 SQLite 쓰기다(D-40의 로그 로테이션과 같은 이유).

**범위 밖으로 남긴 것**: 스키마가 바뀐 배포의 롤백은 여전히 백업 복구다(`PRAGMA user_version`은
되돌아가지 않는다). 배포 결과를 웹푸시로 보내는 것도 하지 않았다 — Actions 실패 알림으로 충분하고,
알림 종류를 5개로 고정한 원칙(8절)과 섞을 이유가 없다.

### D-52. 매트릭스는 좁히지 말고 밀어라 — 그리고 짧은 목업이 숨긴 것들 *(v22, 이슈 #48)*

**맥락**: Phase 5를 배포하고 실기기로 확인하다 **여섯 건**이 나왔다. 전부 매트릭스 화면이고
나머지 아홉 화면은 이상이 없었다. 공통점이 하나다 — **여섯 건 다 정차역이 많은 노선에서만
드러났다.** 목업(정차역 5개)에서는 하나도 보이지 않았고, 12개로 늘린 뒤에도 ⑤·⑥은 안 보였다.
**짧은 픽스처는 짧은 픽스처만 검증한다**는 것이 이 항목의 진짜 교훈이다.

> 아래 ①~⑤는 레이아웃이고 **⑥은 문구다** — 화면이 판정 카드와 다른 말을 하고 있었다.
> 한 항목에 함께 두는 이유는 원인이 같기 때문이다: 긴 노선을 한 번도 그려보지 않았다.

**① 구간 열이 정렬되지 않는다.** 표가 기본 `table-layout: auto`라 열 너비가 **역 이름 길이를
따라간다.** `영등포`(3자) 열이 `안양`(2자) 열보다 넓어져, 좌석 × 구간이 격자로 읽히지 않는다.
정차역이 늘수록 심해진다. 393pt에서 열이 8개를 넘으면 눈으로 셀을 세는 것이 불가능해진다.

**결정: 구간 열은 너비가 같다. 다 안 들어가면 글자를 줄이는 대신 가로로 스크롤한다.**
`table-layout: fixed` + 구간 열 최소 38pt(세 글자 역 이름이 11pt로 들어가는 폭)로 고정하고,
합이 화면을 넘으면 가로 스크롤한다. 좌석 열은 `sticky`로 왼쪽에 남긴다 — 밀고 나면
어느 좌석 줄인지 알 수 없으면 표가 무의미하다.

> **왜 글자를 줄이지 않나**: 11pt는 이미 iOS 최소치에 가깝다(설계 규칙, 웹 10.5 → 11).
> 여기서 더 줄이면 역 이름이 뭉개지고, **역을 잘못 읽으면 판정을 잘못 읽는다.**
> 줄이는 쪽은 조용히 틀리고 스크롤은 시끄럽게 맞다.

**함께**: 오른쪽이 잘린 것만으로는 "밀 수 있다"가 읽히지 않아, 넘칠 때만 한 줄로 말한다.
**못 본 구간을 안 판 자리로 착각하면 판단 자체가 틀어진다** — 이건 표시 문제가 아니라
판정 문제다. 좌석 열은 `내 자리`·`END` 태그가 있을 때만 넓히고(112) 없으면 좁혀(72)
그만큼을 구간에 넘긴다. 태그 유무로 폭이 한 번 바뀌지만 그 순간은 판정 자체가 바뀌는
순간이라 조용히 어긋나 보이지 않는다.

**② 좌석을 고르면 액션 바가 매트릭스 맨 끝에 생긴다.** 자리를 고른 뒤 표 끝까지 스크롤해야
"이 자리에 앉음"을 누를 수 있었다. 원인은 `screen`이 `min-height: 100dvh`인 것 —
콘텐츠가 길어지면 화면이 같이 늘어나 `body`의 `overflow-y: auto`가 발동하지 않고
**문서가 통째로 스크롤된다.** 흐름에 놓인 바는 뷰포트가 아니라 문서 끝에 앉는다.

**결정: 좌석 액션 바는 `position: fixed`로 화면 하단에 고정하고 시트처럼 올린다.**
`지금 상태` 시트와 같은 어휘다. 다만 **배경 막(backdrop)은 두지 않는다** — 바를 띄운 채로
다른 좌석을 눌러 비교하는 것이 이 화면의 핵심 동작이고, 막을 깔면 그게 막힌다.
대신 ✕를 뒀다: 좌석 행을 다시 눌러도 닫히지만 **그 행이 화면 밖일 수 있다.**

> `screen`을 `height: 100dvh` + 내부 스크롤로 바꾸는 쪽이 근본적이지만, 사파리 주소창이
> 늘었다 줄었다 하는 동안 내부 스크롤 컨테이너가 튀는 문제를 새로 산다. **이번 증상은
> 액션 바 하나이므로 그 하나만 고정한다.** 다른 화면은 실기기에서 이상이 없었다.

**③ 실기기 스크린샷을 받아보니 조건이 더 나빴다.** 창원→수원, **구간 11개**에 **네 글자 역**
(`창원중앙`)이 섞여 있었다. 재현본(짧은 노선, 세 글자 이하)만 보고 있었으면 둘 다 놓쳤다.

- **세 글자를 넘는 역 이름은 가운데서 접어 두 줄로 만든다.** CSS 줄바꿈에 맡기면 폭이 닿는
  데서 끊겨 `창원중`/`앙`이 된다 — 접는 위치를 코드가 정해야 `창원`/`중앙`이 나온다.
  열 폭을 이름에 맞춰 넓히는 쪽은 구간 11개에서 가로 스크롤이 배가 되어 더 나쁘다.
- **노선 진행바는 정차역이 여덟을 넘으면 이름을 고른다** — 처음에는 출발 · 하차 · 지금 향하는
  역 셋을 남겼는데 **그것도 부족했다 (⑤).** 일곱까지는 역당 51pt라 손대지 않는다.

**④ 스크롤하면 판정 문구가 시계·배터리 밑을 지나간다.** 내비바(`종료 / 열차명 / 설정`)가
콘텐츠와 같이 스크롤돼서 상단이 비고, 그 자리로 본문이 올라온다. **네이티브 iOS가 내비바를
상태바 아래로 밀어 넣고 블러를 씌우는 것이 바로 이것 때문이다** — 목업에는 스크롤이 없어서
피그마에서도, 헤드리스 스크린샷에서도 드러나지 않았다.

**결정: 내비바는 `sticky`로 상단에 고정하고 상태바 영역까지 덮는다.** `screen`이 이미
`padding-top: env(safe-area-inset-top)`을 갖고 있으므로 내비바만 그만큼 음수 마진으로
끌어올린 뒤 같은 값을 자기 패딩으로 되돌린다 — **다른 화면(로그인·부팅)의 세이프 에어리어는
건드리지 않고** 내비바만 위로 올라간다. 흐름상 차지하는 높이는 그대로라 아래가 밀리지 않는다.

**⑤ 셋만 남겨도 겹친다 — 그 셋 중 둘이 인접한 노선이 있다.** 무궁화 용산→광주송정은
정차역이 20개다(역당 18pt, 역 이름은 22~33pt). 출발이 `용산`이고 지금 향하는 역이
`영등포`, 즉 **바로 옆 노드**라 라벨 둘이 그대로 겹쳤다. 간격으로는 풀리지 않는다.

**결정: 정차역이 많으면 지금 향하는 역 하나만 라벨한다.** 읽는 사람이 잃는 것은 없다 —
**시작·하차는 바로 위 줄이 이미 말하고 있었다**(`용산 → 광주송정 · 자유석`). 진행바에 또 쓴
것이 중복이었고, **그 중복이 겹침의 원인이었다.** 진행 정도는 채워진 점이, 지나온 구간은
아래 매트릭스의 흐린 열이 말한다. 셋을 둘로, 둘을 하나로 깎는 식의 임시 대응이 아니라
"진행바가 유일하게 말할 수 있는 것만 말한다"로 정리한 것이다.

> 후보였던 대안: ⓐ 점을 버리고 진행 막대 + `지금 영등포로 향하는 중 · 2/20`,
> ⓑ 정차역이 많으면 진행바 자체를 감춘다. ⓐ는 장거리에서 정보량이 가장 많지만 피그마
> `ios` 설계본(점 + 펄스)과 달라지고, ⓑ는 "지금 어디쯤"을 훑어볼 수단이 사라진다.
> 20개 점이 18pt 간격이면 점선처럼 보이는 것은 사실이라, 그게 거슬리면 ⓐ가 다음 후보다.

**⑥ 액션 바가 판정 카드와 다른 말을 하고 있었다.** 지금 구간이 팔린 좌석을 고르면
`{탑승역}까지 빈 좌석`이 찍혔다 — `clearUntil`이 그 경우 `startIdx`를 그대로 돌려주는데
화면이 그걸 `stops[startIdx]`로 옮겨 **길이 0인 구간을 문장으로 만든** 것이다.
같은 화면의 판정 카드는 그 좌석을 `1-1(조치원부터 서대전까지)`로 맞게 말하고 있었다.
**한 화면이 서로 다른 말을 하는 순간 사용자는 어느 쪽도 못 믿는다.** 게다가 그 문장 옆에는
`이 자리에 앉음` 버튼이 있었다.

**결정: `core/format.js`에 `seatWindow()`를 두고 두 스킨이 그 문장을 쓴다.**
지금 비어 있으면 `{역}까지 빈 좌석`, 지금 팔렸으면 **남은 구간에서 처음 비는 구간**을 찾아
`지금은 빈 자리가 아님 · {역}부터 {역}까지`, 끝까지 팔렸으면 `남은 구간 전부 판매됨`.

- **`seatRange`로는 안 된다.** 그쪽은 서버가 준 추천(`clear_from_idx`)을 쓰지만, 좌석을 눌러
  고르는 쪽은 **추천 목록에 없는 좌석도 고를 수 있다** — 행의 `cells`에서 직접 세야 한다.
- **`이 자리에 앉음`은 그대로 둔다.** 지금 팔린 좌석에서 버튼을 막는 쪽이 더 안전해 보이지만,
  **자리를 옮겼는데 갱신을 못 하는 경우**가 생긴다 (조회가 실패했거나 한 박자 늦은 데이터일 때
  실제로 앉아 있을 수 있다). 막는 대신 **틀린 문장을 고친다.**
- 문구가 길어져 CTA가 두 줄로 깨졌다 — 두 스킨의 `sitBtn`에 `nowrap`을 걸었다.
  **줄어드는 쪽은 설명이고 버튼은 아니다.**
- **web 스킨에도 똑같이 있던 버그다.** core에 두는 것의 값이 여기서 회수된다 (→ D-50 결정 ②).
  스모크에 8건을 고정했다(전 구간 빈 좌석 / 도중까지 / 지금 팔림 / 중간만 빔 / 한 구간만 빔 /
  전부 팔림 / 실효 시작이 밀린 두 경우) — **문구가 갈리는 순간 두 스킨이 같이 틀린다.**

**함께 한 것**: 프리뷰에 `?scroll=<px>`을 더했다. **고정 요소는 스크롤해야 비로소 드러난다** —
맨 위에서 찍으면 흐름에 둔 것과 구분되지 않아 ②와 ④를 헤드리스로 볼 수 없었다.
프리뷰 하네스에 `?state=long`·`?state=longest`를 더했다. 기본 픽스처가 5개역이라 **다섯 증상
전부 헤드리스에서 재현되지 않았고**, 12개역으로 늘린 뒤에도 ⑤는 안 잡혔다 — 그 노선에는
"셋 중 둘이 인접"이 없었기 때문이다. **목업이 짧으면 목업만 통과한다.** 그래서 픽스처를
**실기기에서 깨진 두 노선 그대로**(창원→수원 12개역 · 용산→광주송정 계열) 맞춰 놨다.
`sw.js`의 `CACHE`는 `itx-shell-v7`.

### D-53. 사용자 관리는 앱에 넣는다 — CLI 권장안을 뒤집고, 대신 방어를 네 겹으로 *(v23, 이슈 #54)*

**맥락**: tailnet에 지인을 초대해 두 번째 사용자가 생기면서 "원치 않는 계정이 생겼을 때
어떻게 지우나"가 실제 질문이 됐다. 그때까지 답은 **EC2에 SSH로 들어가 SQLite를 여는 것**
하나뿐이었다 — 폰에서는 사실상 불가능하다.

**소유자의 최초 우려는 반대 방향이었다**: "스크립트가 깃허브에 공개돼 있으니 가입한 사람이
실행할 수 있지 않나". **성립하지 않는다.** 스크립트를 실행하려면 EC2 셸이 필요하고,
가입자가 얻는 것은 443 포트의 HTTP 세션뿐이다. SSH는 ACL에서 `autogroup:member`와
`tag:ci`(22만)에게만 열려 있고 공유 사용자는 `autogroup:shared` → `tcp:443`이다 (→ D-51).
앱은 `tailscale serve`(tailnet only)라 인터넷에 노출돼 있지도 않다. **공개된 것은 스크립트의
내용이지 실행 권한이 아니다.**

**그런데 결론은 앱 기능이다.** 11절 미해결 항목("관리자 복구 수단", D-24 후속)은 CLI를
권장했고 그 이유는 "상시 열린 구멍이 안 남는다"였다. **그 권장을 뒤집는다** — 폰에서 즉시
대응할 수 있어야 한다는 실사용 요구가 더 크다고 소유자가 판단했다.
*(권장안 문구는 지우지 않는다. 뒤집힌 결정도 개정 이력으로 남긴다.)*

**대가는 정직하게 치른다.** 삭제 권한이 HTTP로 노출되는 만큼 방어가 네 겹이다:

| 겹 | 거절 | 무엇을 막나 |
|---|---|---|
| `Depends(current_admin)` | 403 | 관리자 아닌 사용자 |
| 비밀번호 재확인 | 403 | 세션 탈취, 폰 오조작 |
| **자기 자신** | 400 | 관리자 소멸 |
| **관리자 계정** | 400 | 관리자 소멸 |

뒤의 두 겹이 이 결정의 핵심이다. 승격 API가 없으므로(D-24) **관리자가 사라지면 앱에서
되돌릴 방법이 전혀 없다** — 로그인도 가입(403)도 막히고 DB 직접 수정만 남는다. 11절이
"Phase 1 개발 중 실제로 겪었다"고 적어둔 바로 그 상태다. 그러니 이건 UI에서 버튼을 감추는
것으로 끝낼 문제가 아니라 **서버가 거절해야 하는 것**이다. 화면은 방어선이 아니다.

**목록은 자격증명을 한 조각도 내보내지 않는다** (절대규칙 9). 연동 여부는 `korail_pw_enc` /
`discord_webhook_enc`의 **NULL 여부로만** 판단한다 — 복호화하지 않으므로 평문이 메모리에도
뜨지 않는다. 테스트는 키 이름뿐 아니라 **값**에도 자격증명이 없는지 확인한다(키만 보는 검사는
직렬화 방식이 바뀌면 통과시켜버린다).

**삭제는 `DELETE FROM user` 한 줄이다.** `session`/`preset`/`subscription`/`push_device`가
전부 `ON DELETE CASCADE`이고 `db_session`이 `PRAGMA foreign_keys = ON`을 켠다.
세션이 함께 지워지므로 상대는 다음 요청부터 401이고 **컨테이너 재시작이 필요 없다** —
재시작은 폴 포인트를 먹는다(D-51이 가드를 붙인 이유와 같다).

> **손으로 지울 때 조용히 틀리는 지점**: `sqlite3` CLI나 맨 `sqlite3.connect()`는
> `foreign_keys`가 **기본 꺼짐**이다. 그 상태로 `DELETE FROM user`를 하면 **에러 없이**
> 세션·구독이 고아로 남는다. 앱 경로에는 이 함정이 없지만 DEPLOY.md 절차에는 있다.

**이 기능은 "관리자 복구 수단"이 아니다.** 관리자만 호출할 수 있으므로 관리자 계정 자체를
잃는 경우는 여전히 풀리지 않는다. 11절 미해결 항목은 **그대로 남는다.**

**범위 밖**: 관리자 승격 API(D-24 유지), 사용자 정지/비활성화(삭제로 충분하다),
삭제 감사 로그(1~2인용에 과하다), 가입 토글 자동 재잠금 — 마지막 것은 "열어둔 채 잊는다"는
**원인** 쪽 대책이라 값이 크지만, 이 이슈의 범위가 아니라 별도로 다룬다.

---

### D-54. 미사용 시간대 자동 정지 — 시각이 아니라 **다음 기동 전의 폴**을 본다 *(v24, 이슈 #58)*

**문제**: EC2가 24시간 켜져 있는데 실제로 쓰는 것은 평일 통근 시간대뿐이다. 월 ~$4.7 중
컴퓨트가 $3.8이라 미사용 시간대를 끄면 절반 가까이 줄어든다.

**단순한 안(고정 시간표)은 조용히 틀린다.** "23:50에 끄고 06:00에 켠다"로 하면, 꺼져 있는
동안 도래한 폴 포인트가 `resolve_poll`의 grace 2분을 넘겨 **스킵되고 포인터만 전진한다**
(D-19). 운행이 통째로 지나갔으면 `is_ride_over`가 구독을 만료시켜 그 열차에 대해서는
아무 일도 없었던 것이 된다. 남는 것은 로그 한 줄이고 **알림은 오지 않는다.**

**결정**: 기동은 고정 시간표(EventBridge Scheduler, 평일 06:00 `Asia/Seoul`), **정지는
조건부**로 한다. `scripts/shutdown_guard.py`가 **다음 기동 시각 + 부팅 마진 10분** 전에
폴 포인트가 잡힌 활성 구독이 있는지 DB에 물어보고, 있으면 끄지 않는다.

D-51의 재배포 가드와 같은 태도다 — **시각을 하드코딩하지 않는다. 위험한 것은 시각이 아니라
임박한 폴이다.** 통근 시간이 바뀌어도 가드는 낡지 않는다.

**주말은 따로 다루지 않는다.** "다음 기동 시각" 계산에 이미 들어 있다 — 금요일 밤의 다음
기동은 월요일 06:00이므로, 토요일 열차 구독이 하나라도 있으면 금요일 밤부터 정지를 거부한다.

#### ★ 판단 불능일 때의 방향이 `deploy_guard.py`와 반대다

| | 모를 때 | 이유 |
|---|---|---|
| `deploy_guard.py` | **통과**시킨다 | 막는 쪽으로 고장 나면 CD가 영영 안 돈다 — "가드가 없던 어제"보다 나쁘다 |
| `shutdown_guard.py` | **켜둔다** | 하룻밤 $0.09 대 출근길 알림 전체. 어느 쪽이 싼지가 분명하다 |

대신 이 방향의 고장은 **요금서에만 나타난다** — DB를 계속 못 읽으면 인스턴스가 영영 안 자고
절감이 조용히 0이 된다. `journalctl -u itx-shutdown`에 사유가 남는다.

#### 조용히 틀리는 자리 셋을 각각 막았다

| 자리 | 무엇이 일어나나 | 대책 |
|---|---|---|
| `Persistent=true` | systemd가 **꺼져 있는 동안 놓친 실행을 부팅 직후 몰아서 친다.** 매일 밤 꺼지므로 놓친 실행이 늘 있고, 월요일 06:00에 켜지자마자 다시 꺼진다 | `Persistent=false` |
| 종료 동작이 `terminate` | OS가 건 poweroff에 인스턴스가 **삭제된다.** 종료 방지(`disableApiTermination`)는 API만 막을 뿐 이걸 막지 않는다 | 설치 전 콘솔에서 `stop` 확인 (DEPLOY.md 9절) |
| 호스트 타임존 변경 | 크론이 9시간 어긋난다 | 타이머의 `OnCalendar`에 `Asia/Seoul`을 직접 적는다 |

#### 설정이 세 곳에 나뉜다 — 함께 바꿔야 한다

EventBridge cron 식 / `shutdown_guard.START_TIME` / `itx-shutdown.timer`의 `OnCalendar`.
기동을 07:00으로 늦췄는데 가드가 06:00을 믿으면, 06:10 폴을 "기동 후"로 오판해 **전날 밤에
인스턴스를 꺼버린다.** 박스에서 EventBridge를 조회하게 만들 수도 있었지만(IAM 인스턴스
프로파일 + boto3) 월 $2를 아끼자고 늘릴 부품이 아니라고 봤다 — 대신 세 파일 모두에 경고를 적었다.

**대안으로 검토하고 채택하지 않은 것**: 1년 Compute Savings Plan. 다운타임도 알림 누락
위험도 없이 월 $1.3 정도를 줄여 절감 규모가 비슷하다. **1년 약정이 싫다**는 이유로 스케줄링을
골랐다 — 약정이 부담스럽지 않게 되면 이 결정을 뒤집어도 된다 (그때는 둘을 겸하지 마라.
Savings Plan은 시간당 약정액을 인스턴스가 꺼져 있어도 청구한다).

#### 부수 효과 — **배포와 백업이 가동 시간대에 묶인다** *(설치 후 발견)*

박스가 꺼져 있으면 tailnet에서 피어가 사라지므로 **CD가 `대상 주소 확인` 단계에서 실패한다.**
서버를 건드리기 전이라 손상은 없고 다음 기동 뒤 Re-run으로 끝나지만, "배포는 언제든 된다"는
전제가 깨졌다. 실패 메시지에 사유를 적고 DEPLOY.md 9절에 명시했다 — **조용한 실패가 아니라
시끄러운 실패라서** 구조를 바꾸지 않고 안내만 두는 것으로 충분하다고 봤다.

같은 이유로 **"새벽 3시 백업"은 한 번도 실행되지 않는다.** #60(정기 백업)이 이 제약을
전제로 설계돼야 한다 — `Persistent=true`로 때우려 하면 위 표의 첫 줄을 다시 만난다.

**범위 밖**: 인스턴스가 스스로 다음 기동 시각을 EventBridge에 예약하는 것(부품이 는다),
DB 정기 백업(별도로 다룬다 — #60), 가동 시간대의 자동 학습.

---

### D-55. DB 백업은 S3로, **떴다고 끝이 아니라 검증하고 기록한다** *(v25, 이슈 #60)*

**문제**: 리전 이관(D-6 재확인) 뒤 `data/itx.db`의 사본이 **어디에도 없었다.** 서울 EBS
볼륨 하나에만 있고, 그 안에 코레일 자격증명(Fernet)·푸시 기기 등록·그리고 저장소에 없는
station·train_stop 캐시(D-29 — 소스 CSV는 `data/`가 gitignore)가 들어 있다.

**결정**: 매일 23:40에 `.backup` 스냅샷을 떠 **S3에 하루 1개, 30일 보관.**

#### 보관 위치 — 셋을 재고 S3

| 안 | 기각 사유 |
|---|---|
| tailnet의 맥으로 push | **맥북이 23:40에 깨어 있어야 한다.** macOS는 Tailscale SSH 서버가 못 되니 박스가 맥으로 밀어야 하고, 그러려면 맥의 원격 로그인을 켜야 한다. 백업이 노트북 뚜껑 상태에 달리면 백업이 아니다 |
| EBS 스냅샷 | 코드가 없어 매력적이지만 **볼륨을 통째로 떠서 WAL 중간 상태를 잡는다** — D-41이 금지한 바로 그것이다. 3MB 파일 복원에 볼륨을 붙여야 한다 |
| **S3** | **채택.** 볼륨·인스턴스·리전이 사라져도 살아남는다. 월 몇 센트 |

**대가는 박스에 AWS 자격이 처음 생긴다는 것.** 그래서 인스턴스 프로파일을 버킷 한 접두사의
`s3:PutObject` **하나로** 좁혔다. `GetObject`도 `ListBucket`도 주지 않는다 — 복원은 사람이
로컬에서 하고, 박스가 남의 백업을 읽을 이유가 없다. 유출 시 피해는 "여기에 파일을 쓸 수
있다"로 끝난다.

#### 떴다고 끝이 아니다 — 이 이슈의 실제 내용

**빈 DB도 `.backup`은 성공한다.** 검증 없이 올리면 "백업이 있다"는 **잘못된 안심**을 얻고,
정작 필요할 때 아무것도 없다. 그래서:

- `user`·`station`이 비어 있으면 **올리지 않고 실패**한다. 그 둘이 0인 정상 상태는 없다
  (가입이 잠겨 있어 계정은 항상 있고, station 캐시는 화면이 뜨는 전제다).
  `subscription`·`push_device`는 0일 수 있으므로 세기만 한다
- **성공 기록은 업로드가 끝난 뒤에만** 쓴다. `--no-upload`(예행 연습)는 기록하지 않는다 —
  손으로 확인한 것이 진짜 백업으로 위장되면 낡음 감지가 무력해진다

#### 실패를 알리는 방법 — `deploy_check.sh`에 얹는다

**알림 종류는 5개로 고정이라 늘리지 않는다** (8절). 로그만 남기면 아무도 안 본다.
성공 시각을 `/var/lib/itx-backup/last_success`에 적고 `deploy_check.sh`가 그 나이를
**배포마다** 찍는다 — 이미 "조용히 틀리는 것들을 한 화면에 모으는" 도구이므로 자리가 맞다.

**`!`(경고)이지 `✗`(치명)가 아니다.** 낡은 백업 때문에 배포가 롤백되면 안 된다.
기준은 **4일** — 인스턴스가 주말에 자므로 금요일 백업 뒤 월요일까지 정상적으로 3일이
벌어진다(D-54). 3일로 잡으면 월요일마다 거짓 경고가 뜨고, 그러면 진짜 신호를 무시하게 된다.

#### 시각이 23:40인 이유

정지 가드(23:50)보다 **10분 앞**이다. D-54가 이미 적었듯 **"새벽 3시 백업"은 한 번도
실행되지 않는다** — 그 시각에 인스턴스가 없다. `Persistent=true`로 때우면 부팅 직후
몰아치기가 아침 기동과 겹친다. 타이머는 평일이 아니라 **매일**이다: 주말 구독 때문에
가드가 켜둔 날에도 백업이 돌고, 자고 있으면 아무 일도 없다.

**범위 밖**: 백업 암호화(이미 SSE-S3 + Fernet 이중), 오프사이트 2차 복제,
자동 복원 리허설, `SECRET_KEY` 교체 시의 재암호화 마이그레이션.

### D-56. 즐겨찾기 노선 — 잠자던 프리셋을 칩으로 깨우고, 상한 5개는 서버가 지킨다 *(v26, 이슈 #68)*

**문제**: D-37이 직전 구간 자동 프리필을 앞당기면서 "구간이 둘 이상 필요해지면 그때
프리셋 프론트를 붙인다"고 미뤄뒀다. 그 시점이 왔다 — 출근/퇴근처럼 방향이 다른 구간을
오가면 프리필은 항상 반대 방향을 채워 놓는다. 백엔드 `/api/presets`는 Phase 1부터
있었지만 프론트가 쓰지 않아 잠들어 있었다.

**결정**: 프리셋을 **"즐겨찾기 노선"**이라는 이름으로 탑승 등록 화면에 노출한다.
계정당 **최대 5개.**

- **UI는 칩 행이다** (web 05 · ios 02 화면, 피그마 `Chip/Route`·`iOS/Chip-Route`).
  칩 탭 = 출발/도착 채움, × = 삭제, 점선 칩 = 현재 구간 저장. 새 화면을 만들지 않는다 —
  프리필(D-37)과 같은 자리에서 한 탭 차이로 해결될 일이다
- **상한 5의 근거**: 통근 왕복 2개 + 예외 구간 몇 개면 끝나는 도구다. 무한정 쌓이면
  칩 행이 스크롤이 되고, 그 순간 "한 탭"이라는 존재 이유가 사라진다. 조정 예정 값이므로
  `MAX_PRESETS_PER_USER` 상수 + 순수 함수 `can_add_preset`으로 격리했다 (D-17)
- **방어선은 서버다**: 프론트는 5개가 차면 저장 칩을 감출 뿐이고, 초과 POST는 서버가
  409로 거절한다. 화면이 감춘 것을 방어로 착각하지 않는다 (D-53과 같은 원칙)
- **저장 가능 판정과 라벨 문구는 `core/favorites.js`가 한 번만 만든다** — 스킨마다
  갈리면 뒤처진 쪽이 틀린 정보가 된다 (D-50과 같은 원칙)
- 즐겨찾기 조회 실패는 삼킨다 — 직전 구간 프리필과 같은 급의 **실패해도 되는 부가
  기능**이다. 여기서 막혀 탑승 등록을 못 하게 되면 안 된다

**name 필드는 그대로 둔다**: 화면은 `from → to`를 직접 그리므로 name이 없어도 되지만,
스키마에서 빼는 마이그레이션은 이 이슈의 일이 아니다. 저장 시 `"수원 → 용산"` 형태로
채워 둔다.

**범위 밖**: usual_train_nos·poll_offsets_min의 프론트 노출(여전히 API로만),
칩 순서 변경(정렬은 id 순 고정), 즐겨찾기 기반 알림.

### D-57. 갭 구간은 마지막 스냅샷으로 보여주고, 출발 -1분에 한 번 더 본다 *(v27, 이슈 #72)*

**문제 (실사용 보고)**: 천안 07:12 ITX-마음, 천안-평택-수원-영등포 이용. 천안을 출발하는
순간 천안-평택 열이 매트릭스에서 회색 비활성으로 사라졌다. D-47의 의도된 부수효과다 —
`sellable_seg_idx`가 출발한 구간을 조회·판정에서 빼면서 `start_seg_idx`가 전진하고,
화면의 `seg.idx < startIdx` 흐림 처리에 걸린다. **시발역은 완충이 0분**이라(도착=출발
폴백) 출발 즉시 사라지고, 중간역도 정차 시간(2~3분)이 전부다. 폴 포인트가 전부 다음 역
도착 -10/-4분이라 출발 직후에는 갱신 이벤트조차 없다. 그런데 사용자는 그 구간을 **지금
타고 있고**, 아직 서 있다면 "빈 좌석이었던 자리 = 지금 앉아도 되는 자리"라는 정보가
가장 필요한 순간이다.

**결정 4개 묶음** (판정을 고치는 것이 아니라 **표시를 되살리는 것**이다):

1. **`seat_snapshot` 테이블** — `(train_no, date, frm, to)`별 **마지막 성공 조회**를
   보존한다. 60초 화면 캐시(`matrix_cache`)와 별개다: TTL 없음, 운행일 단위로 청소.
   **스케줄러 폴과 화면 조회 양쪽이 기록한다** — 이 테이블은 알림 상태
   (`last_verdict_hash`/`last_cells_snapshot`)가 아니므로 절대규칙 5와 무관하다.
   - **오염 방지**: 기록 조건은 "조회 시점에 sellable했던 구간의 성공한 조회"다.
     구조가 보장한다 — 조회 범위가 이미 `[max(sellable, board), alight)`이고,
     ERR911081 등 실패는 예외로 빠져 SeatMap 자체가 안 생긴다. 빈 응답(D-36 = 전
     좌석 판매)은 sellable 범위 안에서는 진짜 정보이므로 기록한다.
   - 남는 리스크 하나: 실제 출발이 실효 출발보다 이른 경우 출발 후 빈 응답이 스냅샷을
     덮을 수 있다. 열차는 조기 출발하지 않고 지연은 실효 출발을 뒤로만 미므로 수용한다.
2. **표시 범위 = 갭 구간만**: `[max(current_seg_idx, board_idx), 실효 시작)` — 지금
   타고 있는 구간이다. 그 앞의 완전히 지나온 구간은 기존 회색(past) 유지. `/matrix`
   응답에 `snapshots: [{seg_idx, as_of, seats}]`로 내려주고, 화면은 점선 셀 +
   "HH:MM 조회" 배지 + 범례 "이전 조회"로 실시간과 구분한다 (피그마 web 07-1·07-2,
   ios 06-1·06-2). **verdict 계산이 끝난 뒤에 채운다** — 판정·알림·좌석 추천 랭킹에는
   절대 유입되지 않는다 (#35 재발 방지).
3. **폴 포인트에 실효 출발 -1분 추가** (`TimelineConfig.depart_poll_offsets_min=(1,)`) —
   -4분 조회와 출발 사이(막판 발권 창)에 팔린 좌석까지 스냅샷에 담는다. 정차역당 최대
   3회가 되므로 조회 예절을 "정차역당 2~3회"로 개정 (D-12 개정, CLAUDE.md 규칙 10 동반
   수정). dedup은 기존 set이 처리(실데이터에서 A역 출발-1분 = B역 도착-10분 겹침 존재).
   실행 시점에 `sellable_seg_idx`를 재계산하므로 grace 지각으로 출발을 넘겨도 그 구간
   조회는 자연히 스킵된다 — ERR911081 창(출발 직후 15~60초)을 밟지 않는다.
4. **`decision_needed=False`여도 스냅샷이 있으면 매트릭스를 그린다** — 마지막 구간
   주행 중이 스냅샷이 가장 절실한 순간이다("곧 도착" 헤드라인은 유지, 스냅샷 열만).
   스냅샷마저 없으면 기존대로 숨긴다 — D-47의 "빈 표는 매진으로 오독" 근거는 그대로다.

**한계 (기록해 둔다)**: 스냅샷 유니버스와 현재 조회 유니버스가 다르면 스냅샷에만 있는
좌석은 표시되지 않는다 — 행이 `seats` 기준이라서다. Phase 0-6 실측상 전 구간 좌석
집합이 동일해 실질 영향 없음. 호출량은 정차역당 +1회(5정차 기준 폴 10→13회, dedup 반영).

**범위 밖**: 스냅샷 기반 알림(알림 5종 유지, 8절), 갭 구간 좌석의 추천 랭킹 반영,
지나온 전 구간의 스냅샷 표시.

### D-58. 정차역 캐시 자동 재적재 + 에러 매핑 통일 *(v28, 이슈 #75/#76)*

**문제 (실사용 장애, 2026-09-01 07시대)**: 코레일 정기 시각표 개편으로 사용자의 평일
07:12 천안발 ITX-마음이 06:36 대전발로 바뀌었다. 라이브 검색(`/api/trains/search`)은
새 열차를 200으로 잘 돌려줬는데 그 열차를 고르면 **매트릭스를 불러올 수 없음**. 서버
로그·프로드 DB 읽기 전용 조회로 확인한 실제 실패 지점은 두 겹:

1. `train_stop` 캐시가 **2026-08-05에 8/1~8/4 실적으로 적재된 이후 4주간 미갱신**. D-29
   본문에서 "재적재는 스케줄러/cron으로 자동화할 수 있다. 지금은 수동 스크립트로
   충분"이라고 유예했던 것이 낡아 있었다. 사용자가 고른 새 열차번호가 스테일 캐시에는
   *개편 전 다른 노선*으로 남아 있어 `route_indexes`가 `LookupError("노선에 없는
   역입니다")` → `POST /api/subscriptions` **404** (아침 6회+ 관측).
2. `_compute_next_poll_at`([app/api/subscriptions.py])이 `TrainStopsNotCached`
   (RuntimeError)를 잡지 않아 캐시에 없는 신규 번호를 고르면 **500**. 매트릭스 쪽 404
   detail도 개발자용 문구(`scripts/load_train_stops.py 로 …`)라 사용자에게 부적절.

**결정 (묶어서 하나로 처리)**:

1. **에러 매핑 통일 — `app/api/stops.py` 신설 (이슈 #75)**. `resolve_route`가 매트릭스와
   구독 등록 양쪽에서 `get_stops` + `route_indexes`를 대신 부르고 `TrainStopsNotCached`
   /`LookupError`/`ValueError`를 사용자용 한국어 404/422로 매핑한다. `stops_error_detail`
   은 순수 함수(`now` 주입, D-21)로 두 문구를 만든다:
   - 캐시 미스: "정차역 정보가 아직 준비되지 않았습니다 … 다음 날 새벽 자동 갱신 후 …"
   - 노선 불일치: "'{역}' 역이 열차 {no}의 정차역 목록에 없습니다 (정보 기준: YYYY-MM-DD)
     시각표 개편으로 정보가 낡았을 수 있습니다 …"
   나이만으로 개편/오입력을 구분할 수 없다는 점이 핵심이다 — 개편 당일엔 캐시가 1일치
   여도 틀리므로 기준일을 그대로 노출해 사용자가 판단하게 한다.
2. **일일 자동 재적재 (이슈 #76, D-29 유예분 해소)**. `scripts/load_train_stops.py`의
   공공데이터 클라이언트를 `app/adapters/train_run_info.py`로 옮기고(외부 연동 =
   adapters/), 30초 폴 틱과 같은 in-process `AsyncIOScheduler`에 두 번째 잡을 붙였다
   (9절 참고). 세 호출 멱등, 실패는 로그만.
3. **스테일 번호 퍼지 (핵심)**. `apply_day`가 저장 후 `DELETE FROM train_stop WHERE
   source_run_ymd < 컷오프`를 돌린다. 컷오프는 `run_ymd - train_stop_max_age_days`
   (기본 7일, 주말 공백 커버). `save_stops`가 이미 열차 단위 delete+insert라 새 실적에
   나오는 번호는 자연 갱신되지만, 실적에서 사라진 옛 번호는 그대로 눌러앉아 있었다 —
   이번 장애의 정확한 원인이 그것이었다. **7일이면 다음 개편 창구 전에 자연 소멸한다.**
   `station.usable`은 D-29 원칙대로 켜기만 한다.
4. **명시적 트랜잭션 (침묵 위험 봉쇄)**. `app.storage.db.connect`가 `isolation_level=None`
   (autocommit)이라 `save_stops`의 per-train delete+insert 사이를 폴 틱이 읽으면 매트릭스가
   순간 '정차역 없음'으로 뜬다. `_transaction` 컨텍스트로 명시적 BEGIN…COMMIT/ROLLBACK,
   WAL 스냅샷이 폴 틱을 트랜잭션 이전 상태에 붙여둔다. 이번 장애에는 없었지만 자동화로
   빈도가 높아지면서 나타날 가능성이 커져 함께 잡았다.

**설정** (매직 넘버 인라인 금지, D-17):
`data_go_kr_service_key`(시크릿, .env), `stops_reload_hours="6,12"`, `stops_reload_minute=5`,
`train_stop_max_age_days=7`.

**복구 타이밍의 정직한 한계**. 공공데이터는 D-1 실적이라 개편 첫날은 이 자동화가
있어도 새 노선을 등록할 수 없다 — 다음 날 새벽에 회복된다. 사용자 문구가 그 사실을
그대로 설명한다. 사용자가 조기에 등록하려면 라이브 검색으로 열차가 존재함을 확인한
뒤 다음 날 아침에 재시도해야 한다.

**잔여 리스크 (기록해 둔다)**. 재사용 번호가 개편 후에도 board/alight 두 역을 모두
포함하되 시각만 낡은 침묵 케이스는 개편 당일 하루로 축소됨(다음 06:05 재적재가 새
실적으로 덮는다). 등록 시 라이브 검색결과의 dep_time과 캐시 dep_time을 대조하는
검증은 **범위 밖** — API 스키마 변경 또는 추가 라이브 호출이 필요한데(호출 예절
비용, CLAUDE.md 10) 기대 효익(하루 짧은 창의 침묵 케이스)이 낮다. 실제 발생 사례가
쌓이면 재검토한다.

**범위 밖**: 프론트 문구(서버 detail이 그대로 `err.message`로 렌더되므로 프론트 무변경),
새 알림 종류(5종 불변, 규칙 6), 실 API 재적재 검증(fixture/스텁만 — 규칙 10).
