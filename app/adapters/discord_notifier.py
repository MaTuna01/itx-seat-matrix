"""DiscordNotifier — 보조 채널 (PLAN.md 8절, D-11).

봇이 아니라 **웹훅**이다. 사용자가 자기 서버 채널에서 웹훅 URL을 만들어 설정 화면에
붙여넣으면 끝 — 봇 토큰 발급, 서버 초대, 권한 설정이 전부 불필요하고 코드도
`httpx.post(webhook_url, json=...)` 수준이다.

활성 조건은 **① 웹훅 연동 + ② 토글 on 둘 다**다. 이 어댑터는 그 판단을 하지 않는다 —
`targets.discord_webhook`이 채워졌다는 것 자체가 "보내도 된다"는 뜻이고, 판단은
`adapters/notify.py`가 한다. 여기서 또 검사하면 조건이 두 곳에 흩어진다.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.adapters.notifier_port import NotifyResult, NotifyTargets
from app.domain.models import Alert

# 디스코드는 성공 시 204(또는 wait=true일 때 200)를 준다.
# 401/403/404 = 웹훅이 지워졌거나 URL이 틀렸다 — 재시도해도 같다.
DEAD_STATUS = frozenset({401, 403, 404})


@dataclass(frozen=True)
class DiscordConfig:
    timeout_seconds: float = 10.0


DEFAULT_DISCORD = DiscordConfig()


class DiscordNotifier:
    """`NotifierPort` 구현. httpx는 async이므로 to_thread가 필요 없다."""

    def __init__(self, config: DiscordConfig = DEFAULT_DISCORD) -> None:
        self._config = config

    async def send(self, alert: Alert, targets: NotifyTargets, *, payload: dict) -> NotifyResult:
        webhook = targets.discord_webhook
        if not webhook:
            return NotifyResult()  # 미연동/토글 off — 침묵이 정상이다. 에러가 아니다
        return await self.post(webhook, f"**{alert.title}**\n{alert.body}")

    async def post(self, webhook_url: str, content: str) -> NotifyResult:
        """웹훅에 한 건 보낸다. `PUT /api/me/discord`의 URL 검증도 이 경로를 쓴다 (8절).

        **예외를 던지지 않는다** — 스케줄러 틱이 디스코드 장애로 멈추면 그 뒤 구독이
        전부 조회되지 않는다 (NotifierPort 계약).
        """
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                res = await client.post(webhook_url, json={"content": content})
        except Exception as exc:  # noqa: BLE001 — 네트워크/DNS 등
            return NotifyResult(errors=(f"디스코드 발송 오류: {exc}",))

        if res.status_code in DEAD_STATUS:
            return NotifyResult(
                errors=(f"디스코드 웹훅이 유효하지 않다({res.status_code}) · URL을 다시 등록하세요",)
            )
        if res.status_code >= 400:
            return NotifyResult(errors=(f"디스코드 발송 실패({res.status_code})",))
        return NotifyResult(sent=1)
