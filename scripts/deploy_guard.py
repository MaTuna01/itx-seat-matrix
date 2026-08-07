#!/usr/bin/env python3
"""재배포 가드 — **지금 컨테이너를 재시작해도 되는가**를 DB에 물어본다 (#22, D-51).

자동 배포는 곧 컨테이너 재시작이다. `next_poll_at` 포인터가 DB에 있어 데이터는 안전하고
2분 grace 안이면 지각한 폴도 실행되지만(D-19), **폴 포인트 직전에 재시작하면 그 한 번은
놓칠 수 있다** (DEPLOY.md 9절이 이미 그렇게 적고 있다). 그 한 번이 하필 베이스라인
알림이면 그날 출근길 검증이 통째로 무의미해진다.

## 왜 시각을 하드코딩하지 않는가

"07:00~09:30에는 배포하지 않는다"가 먼저 떠오르지만, 그건 **통근 시간이 바뀌면 조용히
낡는** 매직 넘버다(원칙 1의 정신). 위험한 것은 시각이 아니라 **임박한 폴 포인트**이므로
그것을 직접 본다. 구독이 없는 날은 새벽이든 아침이든 그냥 배포된다.

## 확신할 때만 막는다

DB가 없거나·아직 스키마가 없거나·잠겨서 못 읽으면 **통과시킨다(0)**. 모르는 것을 이유로
막으면 CD가 영영 안 도는 쪽으로 고장 나고, 그 상태는 "가드가 없던 어제"보다 나쁘다.
막는 것은 "10분 안에 폴이 잡힌 활성 구독이 있다"를 **읽어서 확인했을 때뿐**이다.

## EC2 호스트에서 돈다 — 표준 라이브러리만

호스트에는 uv도 앱 의존성도 없다. CD 워크플로는 이 파일을 stdin으로 밀어 넣는다:

    ssh ubuntu@korail-matrix 'python3 - ~/itx-seat-matrix/data/itx.db' < scripts/deploy_guard.py

그래서 **배포를 중단해도 EC2의 작업 트리는 손대지 않은 상태로 남는다.** 손으로 확인할 때도
같은 명령을 쓰면 된다 (읽기만 하므로 아무 때나 돌려도 안전하다).

종료 코드: 0 = 배포해도 된다 / 1 = 보류해라
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 조정 예정 값은 로직에 인라인하지 않는다 (D-17). 컨테이너 재기동은 20~30초면 끝나지만
# 이미지 load + up까지 포함하면 몇 분이 걸릴 수 있어 넉넉히 잡는다.
DEFAULT_WINDOW_MINUTES = 10


def imminent_polls(
    conn: sqlite3.Connection, *, now: datetime, window: timedelta
) -> list[dict[str, Any]]:
    """`now` 부터 `window` 안에 폴 포인트가 잡힌 활성 구독을 돌려준다.

    시각 비교는 SQL이 아니라 파이썬에서 한다 — `next_poll_at`은 KST 오프셋이 붙은
    ISO8601 문자열이라(`app/storage/db.py`의 `to_db`) 문자열 비교가 오프셋을 이해하지
    못한다. 행 수가 많아야 수십 개라 전부 읽어도 싸다.

    `next_poll_at IS NULL`은 제외한다. 마지막 폴 포인트가 이미 지나 **만료 판정만 남은**
    상태이고(`app/scheduler/poller.py`), 그 판정은 재시작을 넘겨도 다음 틱에 그대로 난다.
    """
    deadline = now + window
    rows = conn.execute(
        "SELECT id, train_no, date, next_poll_at FROM subscription"
        " WHERE active = 1 AND next_poll_at IS NOT NULL"
    ).fetchall()

    hits: list[dict[str, Any]] = []
    for row in rows:
        try:
            at = datetime.fromisoformat(row["next_poll_at"])
        except (TypeError, ValueError):
            # 읽을 수 없는 값은 막을 근거가 못 된다 — 위 "확신할 때만 막는다"와 같은 태도
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
    """읽기 전용 URI(`mode=ro`)를 쓰지 않는다.

    DB가 WAL이라 read-only 연결은 `-shm`이 없을 때(컨테이너가 내려가 있는 경우) 열리지
    않는다. 평범하게 열고 SELECT만 하면 SQLite가 필요한 만큼만 알아서 처리한다.
    `data/`는 uid 1000(= 호스트의 `ubuntu`) 소유라 권한도 맞는다.
    """
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="임박한 폴 포인트가 있으면 배포를 보류시킨다 (#22)",
    )
    parser.add_argument("db", type=Path, help="itx.db 경로")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=DEFAULT_WINDOW_MINUTES,
        help=f"이 시간 안의 폴 포인트를 막는다 (기본 {DEFAULT_WINDOW_MINUTES}분)",
    )
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

    db_path = args.db.expanduser()
    if not db_path.exists():
        print(f"가드: {db_path} 가 없다 — 막을 근거가 없으니 통과시킨다")
        return 0

    try:
        # `with sqlite3.connect(...)`는 트랜잭션만 닫고 연결은 닫지 않는다 — 여기서는
        # 명시적으로 닫는다
        conn = _connect(db_path)
        try:
            hits = imminent_polls(
                conn, now=now, window=timedelta(minutes=args.window_minutes)
            )
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"가드: DB를 읽지 못했다 ({exc}) — 통과시킨다")
        return 0

    stamp = now.strftime("%Y-%m-%d %H:%M %Z")
    if not hits:
        print(f"가드 통과: {stamp} 기준 {args.window_minutes}분 안에 폴 포인트가 없다")
        return 0

    print(f"배포 보류: {stamp} 기준 {args.window_minutes}분 안에 폴 포인트가 있다")
    for hit in hits:
        print(
            f"  구독 #{hit['id']}  {hit['date']} {hit['train_no']}호"
            f"  → {hit['next_poll_at'].strftime('%H:%M:%S')}"
        )
    print("지금 재시작하면 이 폴을 놓칠 수 있다. 지나간 뒤 다시 돌려라")
    return 1


if __name__ == "__main__":
    sys.exit(main())
