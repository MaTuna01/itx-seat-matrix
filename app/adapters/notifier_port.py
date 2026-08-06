"""NotifierPort — 알림 전송 경계 (PLAN.md 8절 채널, 원칙 2, D-11/D-20).

채널이 둘이고 **활성 조건이 다르다**:

| 채널 | 역할 | 활성 조건 |
|---|---|---|
| WebPushNotifier | 기본. 항상 발송 | push_device 등록만 하면 됨 |
| DiscordNotifier | 보조 | ① 웹훅 연동 + ② 토글 on 둘 다 |

폴백(웹푸시 실패 시에만 디스코드)이 아니라 **양쪽 병행**이다 — iOS는 수신 실패를
서버에 알려주지 않아서 "웹푸시가 실패했는지"를 서버가 확실히 알 수 없고, 폴백으로
짜면 오히려 알림 구멍이 생긴다 (8절).

발송 실패는 예외로 던지지 않고 `NotifyResult`에 담는다. 한 채널이 죽어도 다른 채널은
가야 하고, 스케줄러 틱이 알림 실패로 멈추면 **그 뒤 구독이 전부 조회되지 않는다.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.domain.models import Alert


@dataclass(frozen=True)
class PushTarget:
    """웹푸시 구독 1건 = 기기 1대. `p256dh`/`auth`는 브라우저가 준 공개 재료다."""

    device_id: int
    endpoint: str
    p256dh: str
    auth: str
    label: str | None = None


@dataclass(frozen=True)
class NotifyTargets:
    """한 사용자에게 보낼 채널 정보.

    `discord_webhook`은 **복호화된 평문**이다 (storage/creds.py). 응답 모델에 담지 마라
    (절대규칙 9). `discord_webhook`이 None이면 디스코드 채널은 스스로 침묵한다 —
    "연동 + 토글" 판단은 이 값을 채우는 쪽(adapters/notify.py)이 이미 끝냈다.
    """

    devices: tuple[PushTarget, ...] = ()
    discord_webhook: str | None = None


@dataclass(frozen=True)
class NotifyResult:
    """발송 결과. 예외 대신 이 값으로 보고한다.

    `dead_device_ids`는 410/404를 받은 기기다 — 호출부가 **즉시 삭제한다** (D-20).
    """

    sent: int = 0
    dead_device_ids: tuple[int, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def delivered(self) -> bool:
        return self.sent > 0

    def merge(self, other: "NotifyResult") -> "NotifyResult":
        return NotifyResult(
            sent=self.sent + other.sent,
            dead_device_ids=self.dead_device_ids + other.dead_device_ids,
            errors=self.errors + other.errors,
        )


@runtime_checkable
class NotifierPort(Protocol):
    async def send(self, alert: Alert, targets: NotifyTargets, *, payload: dict) -> NotifyResult:
        """`alert`를 이 채널로 보낸다. **예외를 던지지 않는다** (`NotifyResult.errors`에 담는다).

        `payload`는 웹푸시 본문에 그대로 실리는 JSON이다 (딥링크 정보 포함, D-20).
        디스코드처럼 payload가 필요 없는 채널은 무시한다.
        """
        ...


class CompositeNotifier:
    """여러 채널에 병행 발송하고 결과를 합친다 (8절 "양쪽 모두 발송").

    순차 실행이다 — 채널이 2개고 폴링 시점당 푸시 1건이라 병렬화할 이유가 없다.
    """

    def __init__(self, notifiers: tuple[NotifierPort, ...]) -> None:
        self._notifiers = notifiers

    async def send(self, alert: Alert, targets: NotifyTargets, *, payload: dict) -> NotifyResult:
        result = NotifyResult()
        for notifier in self._notifiers:
            result = result.merge(await notifier.send(alert, targets, payload=payload))
        return result
