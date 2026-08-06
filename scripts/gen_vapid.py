#!/usr/bin/env python3
"""VAPID 키페어 생성 (PLAN.md 8절, D-34). 일회성 — app/ 코드와 무관하다.

웹푸시는 "누가 보냈는지"를 VAPID 키페어로 증명한다. 비밀키가 발송 권한이므로
**`.env`에만** 둔다 (절대규칙: 시크릿은 .env로만). 공개키는 브라우저가
`pushManager.subscribe({applicationServerKey})`에 넣어야 하므로 공개돼도 무해하고,
프론트는 `GET /api/push/config`로 받아 간다.

    uv run python scripts/gen_vapid.py

출력 3줄을 `.env`에 붙여넣어라. **키를 바꾸면 기존 push_device 등록이 전부 무효가 된다**
(브라우저 구독이 옛 공개키에 묶여 있다) — 그때는 각 기기에서 알림을 다시 켜야 한다.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01


def _b64(raw: bytes) -> str:
    """base64url, 패딩 없음 — 웹푸시 규격(RFC 8292)이 요구하는 형태."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> None:
    vapid = Vapid01()
    vapid.generate_keys()

    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    print("# .env 에 붙여넣기 (커밋 금지)")
    print(f"VAPID_PRIVATE_KEY={_b64(private_raw)}")
    print(f"VAPID_PUBLIC_KEY={_b64(public_raw)}")
    print("VAPID_SUBJECT=mailto:본인메일@example.com")


if __name__ == "__main__":
    main()
