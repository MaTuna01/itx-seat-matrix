"""스케줄러 패키지 (PLAN.md 9절).

Phase 1에서는 비어 있다 — 폴링 루프와 알림 발송은 **Phase 3**이다.
Phase 1이 미리 만들어 둔 것은 스케줄러가 쓸 순수 함수들뿐이다:

- `domain/timeline.py` — `compute_poll_points` / `first_poll_at` / `resolve_poll`(grace 2분)
- `domain/alerts.py` — 해시 + 셀 스냅샷 이중 감지, 우선순위 합성, 베이스라인
- `subscription.next_poll_at` — 재시작 내구성의 핵심 포인터 (D-19).
  구독 생성 시 `api/subscriptions.py`가 이미 기록한다

Phase 3의 `poller.py`는 30초 틱에서 `next_poll_at <= now`인 활성 구독을 찾아
위 함수들을 순서대로 호출하고, 결과(`last_verdict_hash`, `last_cells_snapshot`,
`last_notified_at`, `next_poll_at`)를 **스케줄러만** 기록한다.
"""
