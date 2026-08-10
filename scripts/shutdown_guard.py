#!/usr/bin/env python3
"""자동 정지 가드 — **지금 인스턴스를 꺼도 되는가**를 DB에 물어본다 (#58).

미사용 시간대에 EC2를 끄면 비용이 줄지만, **꺼져 있는 동안 도래한 폴 포인트는 조용히
사라진다.** `resolve_poll`은 포인터가 grace 2분을 넘기면 스킵하고 다음 포인트로 전진시키고
(D-19), 운행이 통째로 지나갔으면 `is_ride_over`가 구독을 만료시킨다. 남는 것은 로그 한
줄뿐이고 알림은 오지 않는다.

그래서 `deploy_guard.py`와 같은 태도를 취한다 (D-51): **시각을 하드코딩해 "23:50이면
끈다"고 정하지 않는다.** 위험한 것은 시각이 아니라 임박한 폴이므로 그것을 직접 본다.

## 판단 기준

    다음 기동 시각(+부팅 마진) 전에 폴 포인트가 잡힌 활성 구독이 있는가?
        있다 → 끄지 않는다 (그 폴을 놓친다)
        없다 → 꺼도 된다

주말은 이 계산에 자연히 들어간다. 금요일 밤의 "다음 기동"은 월요일 06:00이므로, 토요일
열차 구독이 하나라도 있으면 금요일 밤부터 정지를 거부한다.

## ★ `deploy_guard.py`와 **판단 불능일 때의 방향이 반대다**

배포 가드는 모르면 **통과시킨다** — 막는 쪽으로 고장 나면 CD가 영영 안 돌고, 그 상태는
"가드가 없던 어제"보다 나쁘기 때문이다.

정지 가드는 모르면 **켜둔다.** 하룻밤 더 켜두는 비용은 $0.09고 알림 누락은 그날 출근길
전체다. 어느 쪽이 싼지가 분명하다.

대신 이 방향의 고장은 **요금서에만 나타난다** — DB를 계속 못 읽으면 인스턴스가 영영 안 자고,
절감 효과가 조용히 0이 된다. `journalctl -u itx-shutdown`으로 사유가 남으니 첫 주에 한 번
확인해라 (DEPLOY.md 9절).

## ★ `START_*` 상수는 EventBridge 스케줄과 **손으로 맞춰야 한다**

기동은 AWS(EventBridge Scheduler)가, 정지 판단은 이 파일이 한다. 한쪽만 바꾸면 조용히
틀린다 — 기동을 07:00으로 늦췄는데 여기가 06:00이면, 06:10 폴을 "기동 후"로 오판해서
전날 밤에 인스턴스를 꺼버린다. 바꿀 때는 반드시 양쪽을 함께 바꿔라.

## EC2 호스트에서 돈다 — 표준 라이브러리만

호스트에는 uv도 앱 의존성도 없다. systemd 유닛이 이 파일을 직접 실행한다:

    /usr/bin/python3 scripts/shutdown_guard.py ~/itx-seat-matrix/data/itx.db

**이 스크립트 자체는 아무것도 끄지 않는다** — 읽기만 하고 종료 코드로 답한다. 그래서
아무 때나 손으로 돌려도 안전하다. 실제 `shutdown`은 유닛이 종료 코드를 보고 친다.

종료 코드: 0 = 꺼도 된다 / 1 = 켜둬라
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 조정 예정 값은 로직에 인라인하지 않는다 (D-17).
# ★ EventBridge Scheduler의 `cron(0 6 ? * MON-FRI *)` / `Asia/Seoul` 과 같은 값이어야 한다.
START_TIME = time(6, 0)
START_WEEKDAYS = (0, 1, 2, 3, 4)  # datetime.weekday(): 월=0 … 금=4

# 기동 직후는 아직 폴을 못 한다 — EC2 시작 + 우분투 부팅 + docker compose up + 스케줄러
# 기동까지 1~2분이 걸린다. 넉넉히 잡는다: 마진을 늘리면 그만큼 "안 끄는" 쪽으로 기운다.
BOOT_MARGIN = timedelta(minutes=10)


def next_start_at(now: datetime) -> datetime:
    """`now` 이후 첫 기동 시각 (KST).

    금요일 밤이면 월요일 06:00이 나온다 — 주말 정지가 이 한 줄에서 나온다.
    `now`가 정확히 기동 시각이면 **다음 날**을 돌려준다 (이미 켜져 있다는 뜻이므로).
    """
    now = now.astimezone(KST)
    candidate = datetime.combine(now.date(), START_TIME, tzinfo=KST)
    for _ in range(8):  # 최대 8일 — 주말을 건너뛰어도 넉넉하다
        if candidate > now and candidate.weekday() in START_WEEKDAYS:
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError("다음 기동 시각을 찾지 못했다 — START_WEEKDAYS 가 비었나")


def polls_before(
    conn: sqlite3.Connection, *, now: datetime, deadline: datetime
) -> list[dict[str, Any]]:
    """`now`~`deadline` 사이에 폴 포인트가 잡힌 활성 구독을 돌려준다.

    시각 비교를 SQL이 아니라 파이썬에서 하는 이유는 `deploy_guard.imminent_polls`와 같다 —
    `next_poll_at`은 KST 오프셋이 붙은 ISO8601 문자열이라 문자열 비교가 오프셋을 이해하지
    못한다.

    `next_poll_at IS NULL`은 제외한다. 마지막 폴 포인트가 지나 **만료 판정만 남은** 상태이고,
    그 판정은 다음 기동 뒤 첫 틱에 그대로 난다 — 알림과 무관하다.
    """
    rows = conn.execute(
        "SELECT id, train_no, date, next_poll_at FROM subscription"
        " WHERE active = 1 AND next_poll_at IS NOT NULL"
    ).fetchall()

    hits: list[dict[str, Any]] = []
    for row in rows:
        try:
            at = datetime.fromisoformat(row["next_poll_at"])
        except (TypeError, ValueError):
            # 읽을 수 없는 값 하나 때문에 정지를 막지는 않는다. 진짜로 읽을 수 없는
            # 상황(DB 자체가 안 열림)은 main()에서 통째로 "켜둔다"로 처리한다
            continue
        if at.tzinfo is None:
            continue
        at = at.astimezone(KST)
        if now <= at <= deadline:
            hits.append(
                {
                    "id": row["id"],
                    "train_no": row["train_no"],
                    "date": row["date"],
                    "next_poll_at": at,
                }
            )
    hits.sort(key=lambda h: h["next_poll_at"])
    return hits


def _connect(db_path: Path) -> sqlite3.Connection:
    """`deploy_guard._connect`와 같은 이유로 read-only URI를 쓰지 않는다.

    DB가 WAL이라 `mode=ro` 연결은 `-shm`이 없을 때(컨테이너가 내려가 있는 경우) 열리지
    않는다. 평범하게 열고 SELECT만 한다.
    """
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="다음 기동 전에 폴 포인트가 있으면 자동 정지를 보류시킨다 (#58)",
    )
    parser.add_argument("db", type=Path, help="itx.db 경로")
    parser.add_argument(
        "--now",
        default=None,
        help="기준 시각(ISO8601, KST). 예행 연습용 — 생략하면 현재 시각",
    )
    args = parser.parse_args(argv)

    now = datetime.now(KST) if args.now is None else datetime.fromisoformat(args.now)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    now = now.astimezone(KST)

    start = next_start_at(now)
    deadline = start + BOOT_MARGIN
    stamp = now.strftime("%Y-%m-%d %H:%M %Z")
    horizon = (
        f"다음 기동 {start.strftime('%m-%d(%a) %H:%M')}"
        f" + 부팅 마진 {int(BOOT_MARGIN.total_seconds() // 60)}분"
    )

    db_path = args.db.expanduser()
    if not db_path.exists():
        # deploy_guard 와 반대 방향이다 — 모르면 켜둔다 (모듈 docstring 참조)
        print(f"정지 보류: {db_path} 가 없다 — 판단 근거가 없으므로 켜둔다")
        return 1

    try:
        conn = _connect(db_path)
        try:
            hits = polls_before(conn, now=now, deadline=deadline)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"정지 보류: DB를 읽지 못했다 ({exc}) — 판단 근거가 없으므로 켜둔다")
        return 1

    if not hits:
        print(f"정지 가능: {stamp} 기준 {horizon} 전까지 폴 포인트가 없다")
        return 0

    print(f"정지 보류: {stamp} 기준 {horizon} 전에 폴 포인트가 있다")
    for hit in hits:
        print(
            f"  구독 #{hit['id']}  {hit['date']} {hit['train_no']}호"
            f"  → {hit['next_poll_at'].strftime('%m-%d %H:%M:%S')}"
        )
    print("지금 끄면 이 폴을 놓친다 — 켜둔다")
    return 1


if __name__ == "__main__":
    sys.exit(main())
