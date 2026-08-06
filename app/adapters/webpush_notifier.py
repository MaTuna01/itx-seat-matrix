"""WebPushNotifier — 기본 채널 (PLAN.md 8절, D-9/D-20/D-21).

`pywebpush`는 **동기 라이브러리**다 (내부에서 requests를 쓴다). 절대규칙 3의 korail2와
같은 취급을 한다 — 어댑터 내부에서 `asyncio.to_thread`로 감싸고 Port는 async를 유지한다.
감싸지 않으면 발송 한 건이 이벤트 루프를 막아 그 틱의 다른 구독 조회까지 멈춘다.

**410/404 = 죽은 기기**다. iOS는 푸시 endpoint를 조용히 회전/만료시키므로 지우지 않으면
죽은 행이 쌓여 매 발송이 에러를 뿜고 진짜 실패와 구분이 안 된다 (D-20). 이 어댑터는
`dead_device_ids`로 보고만 하고 삭제는 저장소 책임이다 (`storage/push.delete_dead`).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from pywebpush import WebPushException, webpush

from app.adapters.notifier_port import NotifyResult, NotifyTargets, PushTarget
from app.domain.models import Alert

# 브라우저 푸시 서비스가 "이 기기 구독은 이제 없다"고 답하는 코드.
# 그 외 4xx/5xx는 일시적 장애로 보고 기기를 남긴다 — 살아 있는 기기를 지우면
# 사용자가 알림을 다시 켜야 하고, 그 사실을 알 방법도 없다.
DEAD_STATUS = frozenset({404, 410})


@dataclass(frozen=True)
class WebPushConfig:
    """조정 예정 손잡이 (D-17). 매직 넘버를 로직에 인라인하지 않는다."""

    # 폴 포인트 간격(-10분/-4분)보다 길게 잡을 이유가 없다. 폰이 이보다 오래 오프라인이면
    # 그 알림은 이미 낡았고, 다음 폴링이 최신 상태로 다시 알려준다.
    ttl_seconds: int = 600
    # 즉시 배달 요청. iOS 웹푸시 신뢰성 문제(D-9)에 대한 최소한의 방어다
    urgency: str = "high"
    timeout_seconds: float = 10.0


DEFAULT_WEBPUSH = WebPushConfig()


class WebPushNotifier:
    """`NotifierPort` 구현. VAPID 비밀키는 env에서만 온다 (D-34)."""

    def __init__(
        self,
        *,
        private_key: str,
        subject: str,
        config: WebPushConfig = DEFAULT_WEBPUSH,
    ) -> None:
        self._private_key = private_key
        self._subject = subject
        self._config = config

    async def send(self, alert: Alert, targets: NotifyTargets, *, payload: dict) -> NotifyResult:
        if not self._private_key:
            # 설정 누락은 조용히 넘기면 안 된다 — 알림이 안 오는 이유가 여기 있다.
            return NotifyResult(errors=("웹푸시 VAPID 키가 설정되지 않았다 (.env)",))
        if not targets.devices:
            return NotifyResult(errors=("등록된 알림 기기가 없다",))

        body = json.dumps(payload, ensure_ascii=False)
        results = await asyncio.gather(
            *(self._send_one(device, body) for device in targets.devices)
        )
        merged = NotifyResult()
        for result in results:
            merged = merged.merge(result)
        return merged

    async def _send_one(self, device: PushTarget, body: str) -> NotifyResult:
        try:
            await asyncio.to_thread(self._push_sync, device, body)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            label = device.label or device.endpoint[-12:]
            if status in DEAD_STATUS:
                return NotifyResult(
                    dead_device_ids=(device.device_id,),
                    errors=(f"기기 '{label}' 구독 만료({status}) → 삭제",),
                )
            return NotifyResult(errors=(f"기기 '{label}' 발송 실패({status}): {exc}",))
        except Exception as exc:  # noqa: BLE001 — 네트워크/DNS 등. 틱을 멈추게 하지 않는다
            label = device.label or device.endpoint[-12:]
            return NotifyResult(errors=(f"기기 '{label}' 발송 오류: {exc}",))
        return NotifyResult(sent=1)

    def _push_sync(self, device: PushTarget, body: str) -> None:
        """동기 구간. 스레드에서 돈다."""
        webpush(
            subscription_info={
                "endpoint": device.endpoint,
                "keys": {"p256dh": device.p256dh, "auth": device.auth},
            },
            data=body,
            vapid_private_key=self._private_key,
            # pywebpush가 이 dict에 exp/aud를 채워 넣으므로 **호출마다 새로 만든다**.
            # 재사용하면 두 번째 발송에 첫 번째의 aud가 남아 401이 된다.
            vapid_claims={"sub": self._subject},
            ttl=self._config.ttl_seconds,
            headers={"Urgency": self._config.urgency},
            timeout=self._config.timeout_seconds,
        )
