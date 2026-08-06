# CLAUDE.md

ITX 자유석 좌석 매트릭스 — 개인용 통근 도구 (FastAPI + React PWA, 조회 전용).
**PLAN.md(v11)가 단일 진실 원천이다.** 이 파일은 그 요약이 아니라 작업 규칙이다.
설계 판단이 필요하면 PLAN.md 해당 절 → 17절 결정 이력(D-1~D-37) 순으로 근거를 찾고,
그래도 미정의면 **임의로 정하지 말고 물어봐라.**

## 절대 규칙 (조용히 틀리는 지점들)

1. **모든 datetime은 KST aware** (`ZoneInfo("Asia/Seoul")`). naive datetime을 만들면 안 된다.
   `date`는 열차 운행일 기준.
2. **시간 의존 함수는 `now: datetime`을 인자로 받는다.** `datetime.now()`를 함수 내부에서
   직접 부르는 도메인/스케줄러 코드는 리뷰 반려 대상 (테스트 불가능해짐).
3. **korail2는 동기 라이브러리다.** async 코드에서 직접 호출 금지 — 어댑터 내부에서
   `asyncio.to_thread`로 감싼다. Port 인터페이스는 async를 유지한다.
4. **domain/ 은 순수 함수만.** I/O, DB, 네트워크, 전역 상태 접근 금지.
   외부 연동은 전부 adapters/의 Port 구현 뒤로.
5. **`last_verdict_hash` / `last_cells_snapshot`은 스케줄러만 기록한다.**
   사용자 화면 조회(`/matrix`)가 알림 상태를 건드리면 안 된다 (D-13, D-17).
6. **알림 종류는 5개로 고정** (SEATS_AVAILABLE / MY_SEAT_SOLD / SEAT_EXTENDED /
   ALL_SOLD / FETCH_FAILED). 새 종류를 추가하지 않는다 (8절 "이것만. 늘리지 말 것").
7. **역/노선 이름을 코드에 하드코딩하지 않는다** (원칙 1). "수원" 같은 문자열이
   도메인 로직에 등장하면 잘못된 것이다 (테스트 픽스처는 예외).
8. **인덱스는 전체 노선 `stops` 기준, 실효 시작 = `max(current_seg_idx, board_idx)`** (D-18).
9. **모든 `/api/*`는 `Depends(current_user)` 필수.** `user_id`를 쿼리/바디로 받지 않는다.
   자격증명·웹훅 URL은 API 응답에 절대 노출하지 않는다.
10. **코레일 호출 예절**: 조회는 정차역당 1~2회 + 실패 재시도(30초×3)가 상한.
    Semaphore(3) + 지터 유지, 세션은 재사용(만료 시에만 재로그인).
    개발/디버깅 중에도 실 API를 루프로 때리지 마라 — Mock 어댑터를 써라.

## 아키텍처 경계

```
api/ ──> domain/ (순수 함수) <── scheduler/
  │                                │
  └────────> adapters/ (Port 구현) <┘
                 │
             storage/ (SQLite)
```

- 의존 방향: api·scheduler → domain, adapters. domain은 아무것도 import하지 않는다
  (models 제외).
- 어댑터 전환은 env `ADAPTER=mock|korail2`. Phase 1은 Mock만으로 전체를 관통한다.
- uvicorn `--workers 1` 고정 — APScheduler 인프로세스 (2개면 알림 중복 발사).

## 테스트 규칙 (PLAN.md 13절)

작업 완료 선언 전에 `uv run pytest` 통과가 전제다. **필수** 영역을 건드렸으면
해당 테스트를 함께 수정/추가해야 완료다:

- `test_verdict.py` — STANDING/SEATED 양쪽, **내 좌석 부재 규칙**, 실효 시작
- `test_matrix.py` — 병합/조인, 부분 구간, 부재 추론 유니버스 합집합
- `test_alerts.py` — 13절의 7개 케이스 (침묵해야 할 때 침묵하는지가 핵심)
- `test_timeline.py` — estimate_seg 경계, 폴 포인터 전진, grace 2분
- 픽스처의 시간은 전부 `now` 주입으로 시나리오를 만든다. sleep/실제 시계 사용 금지.

어댑터·프론트·api는 스모크/생략 가능 (단 PATCH 상태 전이 422는 확인).

## 작업 방식

- **Phase 순서를 지킨다** (11절). 현재 Phase 범위 밖 기능을 미리 만들지 않는다.
  어디까지 왔는지는 **PLAN.md 11절이 유일한 기준이다** — 여기에 적어두면 반드시 낡는다.
- **자격증명은 필수다** — Phase 0에서 "로그인 필수 + 본계정"으로 확정됐다 (D-14/D-22).
  비로그인 조회는 불가능하니 그 전제의 코드를 만들지 마라.
  코레일 계정은 `.env`가 아니라 **사용자별로 DB에** 있고 비밀번호는 Fernet 암호화다 (D-35).
  `.env`의 `KORAIL_ID`/`KORAIL_PW`는 `scripts/phase0_feasibility.py` 전용 잔재다 —
  `config.Settings`에 필드조차 없으니 앱 코드에서 읽으려 하지 마라.
- 스택: Python 3.12, FastAPI, Pydantic v2, SQLite(stdlib), **uv** (pip 직접 사용 금지),
  프론트는 web/에서 Vite + React + 바닐라 CSS.
- 폴더 구조는 PLAN.md 15절을 따른다. 새 최상위 모듈이 필요하면 먼저 물어봐라.
- 조정 예정 값(추천 랭킹 가중치, `min_extension_segments`, 다이제스트 상한 등)은
  **설정값을 가진 순수 함수로 격리** — 매직 넘버를 로직에 인라인하지 않는다 (D-17).
- 시크릿은 .env로만. `.env`, `*.db`, `scripts/phase0_results/`는 커밋 금지.

## 설계 변경이 필요할 때

구현 중 PLAN.md와 충돌하거나 문서가 침묵하는 지점을 발견하면:
1. 멈추고 문제를 보고한다 (임의 구현 금지)
2. 합의된 변경은 PLAN.md 본문 수정 + 17절 결정 이력에 D-항목 추가로 남긴다
   (뒤집힌 결정도 지우지 않는다 — 개정 이력으로 유지)

## 참조 파일

- `PLAN.md` — 설계 전체. 특히 5절(도메인 규칙), 8절(알림), 9절(스케줄러), 13절(테스트)
- `seat-matrix.jsx` — 매트릭스 화면 프로토타입이자 verdict 규칙의 참조 구현.
  `/matrix` 응답 스키마(7절)와 1:1
- `scripts/phase0_feasibility.py` — Phase 0 검증 (일회성, app/ 코드와 무관)

## Git 규칙 (이슈 기반 워크플로우)

모든 기능 개발·버그 수정은 **이슈 발급 → 브랜치 분기 → 작은 단위 커밋/푸시 → PR** 순서로 진행한다.
분기/머지 대상은 항상 **`dev` 브랜치** (main 아님).

1. **이슈 먼저 발급 (필수).** 작업 착수 전 `.github/ISSUE_TEMPLATE/`의 템플릿으로 GitHub 이슈를 만든다.
   - 기능 개발 → `Feature`(feature.md) / 외부 요청 작업 → `Feature request`(feature_request.md)
   - 버그 수정 → `Bug`(bug.md) / 질문 → `Question`(question.md)
   - 템플릿의 상세·체크리스트 항목을 채운다. 발급된 **이슈 번호**를 이후 브랜치·커밋·PR에 사용한다.
   - 예: `gh issue create --template feature.md` (gh 인증 필요) 또는 GitHub 웹의 이슈 템플릿.

2. **브랜치.** `dev`에서 이슈 단위로 `feat/<기능이름>` 브랜치를 분기해 작업한다.
   - `git switch backend && git pull --rebase origin backend` 후 `git switch -c feat/<기능이름>`.

3. **커밋.** 작은 작업 단위마다 `[#이슈번호] 커밋 메시지` 형태로 커밋만 진행한다. push는 사용자가 검토 후 직접 하도록할것.
   - 예: `[#12] A-01 활동 분석 서비스 추가`. 한 커밋 = 한 논리 단위, 큰 덩어리로 몰아 커밋하지 말 것.

4. **PR.** 이슈 단위 작업이 모두 끝나면 `.github/PullRequestTemplate.md` 템플릿으로 PR을 생성한다.
   - 제목 `[#이슈번호] 작업내용`, base 브랜치 **`dev`**.
   - 본문의 `Closes #<이슈번호>`를 채워 머지 시 이슈가 자동으로 닫히게 한다.
   - 예: `gh pr create --base dev --title "[#1] 이슈이름" --body-file .github/PullRequestTemplate.md`.

5. **품질 게이트.** PR 올리기 전 빌드 여부 테스트 필수. `dev` 브랜치는 항상 컴파일되는 상태를 유지한다.

6. `dev -> main` 머지는 phase가 넘어갈 때 사용자에게 제안 하고 사용자가 직접 merge.가

## 보안상 위험성이 높은 민감 정보들은 .env로 관리하고 반드시 gitignore 처리

`scripts/hooks/pre-commit`이 이를 기계적으로 강제한다 (D-33). 새 클론에서는 한 번
`git config core.hooksPath scripts/hooks`를 실행해야 켜진다.
막는 것: ① `.env.example`의 시크릿성 키에 값이 채워진 커밋 ② `.env`의 실제 값이
들어간 커밋(파일 종류 무관) ③ `.env`·`*.db` 등 커밋 금지 파일.
시크릿이 아닌 새 설정을 `.env.example`에 값과 함께 넣어야 하면 훅의 `PUBLIC_KEYS`에 추가한다.