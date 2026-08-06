"""알림 발송 배선 — 채널 조립 + 대상 적재 + 죽은 기기 정리 (PLAN.md 8·9절, D-11/D-20).

**"무엇을 보낼지"는 여기서 결정하지 않는다.** 그건 `domain/alerts.evaluate()`가 이미
끝냈다. 이 모듈은 결정된 `Alert` 한 건을 채널로 내보내고, 그 부수효과(죽은 기기 삭제)를
정리하는 마지막 1미터다.

api(`/api/push/test`)와 scheduler 양쪽이 이 모듈을 쓴다.
"""

from __future__ import annotations

import sqlite3

from app.adapters.discord_notifier import DiscordNotifier
from app.adapters.notifier_port import CompositeNotifier, NotifyResult, NotifyTargets
from app.adapters.webpush_notifier import WebPushNotifier
from app.config import Settings, get_settings
from app.domain.models import Alert
from app.storage import push as push_repo
from app.storage.creds import load_discord_webhook


def build_notifier(settings: Settings | None = None) -> CompositeNotifier:
    """웹푸시(기본) + 디스코드(보조)를 병행 채널로 묶는다.

    디스코드 어댑터는 **항상** 조립한다 — 사용자별 활성 여부는 `NotifyTargets`에
    웹훅이 실리는지로 결정된다 (어댑터 조립 시점에는 사용자를 모른다).
    """
    settings = settings or get_settings()
    return CompositeNotifier(
        (
            WebPushNotifier(
                private_key=settings.vapid_private_key,
                subject=settings.vapid_subject,
            ),
            DiscordNotifier(),
        )
    )


def load_targets(conn: sqlite3.Connection, user_id: int) -> NotifyTargets:
    """발송 대상 적재. **opt-in 2단계(연동 + 토글)를 판정하는 유일한 지점이다** (D-11).

    `discord_enabled`가 꺼져 있으면 웹훅을 아예 싣지 않는다 — 어댑터가 URL을 보고도
    참는 구조로 만들면 조건이 두 곳에 흩어져 언젠가 한쪽만 고쳐진다.
    """
    row = conn.execute("SELECT discord_enabled FROM user WHERE id = ?", (user_id,)).fetchone()
    enabled = bool(row["discord_enabled"]) if row is not None else False
    return NotifyTargets(
        devices=tuple(push_repo.list_devices(conn, user_id)),
        discord_webhook=load_discord_webhook(conn, user_id) if enabled else None,
    )


def alert_payload(alert: Alert) -> dict:
    """service worker가 받는 JSON. `url`이 알림 탭 → 매트릭스 딥링크다 (D-20).

    "알림은 앱을 열 시점을 알리는 장치"(D-2/D-9)의 마지막 연결 고리 —
    탭했을 때 매트릭스가 아니라 홈으로 떨어지면 알림의 절반이 무용해진다.
    """
    return {
        "kind": alert.kind.value,
        "title": alert.title,
        "body": alert.body,
        "subscription_id": alert.subscription_id,
        "url": f"/?sub={alert.subscription_id}",
    }


async def deliver(
    conn: sqlite3.Connection,
    user_id: int,
    alert: Alert,
    *,
    notifier: CompositeNotifier | None = None,
) -> NotifyResult:
    """한 건 발송 + 죽은 기기 즉시 삭제 (D-20).

    삭제를 발송과 같은 호출에 묶는 이유: 410/404는 발송 시점에만 알 수 있고,
    나중에 정리하는 별도 잡을 두면 그 사이 발송이 계속 에러를 뿜는다.
    """
    notifier = notifier or build_notifier()
    targets = load_targets(conn, user_id)
    result = await notifier.send(alert, targets, payload=alert_payload(alert))
    if result.dead_device_ids:
        push_repo.delete_dead(conn, result.dead_device_ids)
    return result
