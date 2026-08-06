"""push_device 저장소 (PLAN.md 5절, 8절 채널, D-20).

`endpoint`는 브라우저가 발급한 기기 식별자다. 같은 기기가 알림을 다시 켜면 **같은
endpoint가 돌아오므로** UPSERT로 행을 재사용한다 — 안 하면 UNIQUE 위반이거나 중복 행이
쌓여 한 기기에 알림이 두 번 간다.

`delete_dead()`가 이 모듈의 존재 이유의 절반이다: iOS는 endpoint를 조용히 회전시키고
옛 endpoint는 410/404를 돌려준다. 지우지 않으면 죽은 기기가 쌓여 매 발송이 에러를 뿜고
**진짜 실패와 구분이 안 된다** (D-20).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.adapters.notifier_port import PushTarget
from app.storage.db import to_db


def list_devices(conn: sqlite3.Connection, user_id: int) -> list[PushTarget]:
    rows = conn.execute(
        "SELECT id, endpoint, p256dh, auth, label FROM push_device"
        " WHERE user_id = ? ORDER BY id",
        (user_id,),
    ).fetchall()
    return [
        PushTarget(
            device_id=row["id"],
            endpoint=row["endpoint"],
            p256dh=row["p256dh"],
            auth=row["auth"],
            label=row["label"],
        )
        for row in rows
    ]


def upsert_device(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    label: str | None,
    now: datetime,
) -> int:
    """등록/재등록. 같은 endpoint면 키와 소유자를 갱신하고 행을 재사용한다.

    소유자까지 갱신하는 이유: 같은 기기로 다른 계정에 로그인해 알림을 켤 수 있다.
    그때 옛 소유자에게 계속 발송되면 **남의 통근 정보가 내 폰에 뜬다.**
    """
    conn.execute(
        "INSERT INTO push_device (user_id, endpoint, p256dh, auth, label, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(endpoint) DO UPDATE SET"
        "   user_id = excluded.user_id, p256dh = excluded.p256dh,"
        "   auth = excluded.auth, label = excluded.label",
        (user_id, endpoint, p256dh, auth, label, to_db(now)),
    )
    row = conn.execute("SELECT id FROM push_device WHERE endpoint = ?", (endpoint,)).fetchone()
    return int(row["id"])


def delete_device(conn: sqlite3.Connection, user_id: int, device_id: int) -> bool:
    """남의 기기를 지울 수 없게 user_id를 함께 조건에 넣는다 (IDOR 방지)."""
    cur = conn.execute(
        "DELETE FROM push_device WHERE id = ? AND user_id = ?", (device_id, user_id)
    )
    return cur.rowcount > 0


def delete_dead(conn: sqlite3.Connection, device_ids: tuple[int, ...]) -> int:
    """410/404를 받은 기기를 즉시 삭제한다 (D-20).

    발송 결과에 따른 정리이므로 user_id 조건이 없다 — id는 발송 대상 목록에서 온 값이다.
    """
    if not device_ids:
        return 0
    placeholders = ",".join("?" * len(device_ids))
    cur = conn.execute(f"DELETE FROM push_device WHERE id IN ({placeholders})", device_ids)
    return cur.rowcount
