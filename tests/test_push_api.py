"""알림 기기 등록 + 디스코드 연동 API (PLAN.md 7절, 8절, D-11/D-20/D-34).

실제 발송은 하지 않는다 — conftest가 VAPID 키를 비워두므로 웹푸시는 "미설정"으로
떨어지고, 디스코드는 `DiscordNotifier.post`를 가로챈다. 테스트가 밖으로 HTTP를
내보내면 그건 테스트가 아니라 사고다.
"""

from __future__ import annotations

import pytest

from app.adapters.discord_notifier import DiscordNotifier
from app.adapters.notifier_port import NotifyResult
from tests.conftest import enable_signup

DEVICE = {
    "endpoint": "https://web.push.apple.com/abc123",
    "keys": {"p256dh": "BPubKeyMaterial", "auth": "AuthSecret"},
    "label": "아이폰",
}


@pytest.fixture
def no_discord_http(monkeypatch):
    """디스코드 웹훅 POST를 가로채 성공으로 답한다. 호출 인자를 기록한다."""
    calls: list[tuple[str, str]] = []

    async def fake_post(self, webhook_url: str, content: str) -> NotifyResult:
        calls.append((webhook_url, content))
        return NotifyResult(sent=1)

    monkeypatch.setattr(DiscordNotifier, "post", fake_post)
    return calls


# ── 인증 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/push/config"),
        ("get", "/api/push/devices"),
        ("post", "/api/push/devices"),
        ("post", "/api/push/test"),
        ("put", "/api/me/discord"),
        ("patch", "/api/me/discord"),
        ("delete", "/api/me/discord"),
    ],
)
def test_로그인_없이는_접근할_수_없다(anon_client, method, path):
    """모든 /api/*는 Depends(current_user) 필수 (절대규칙 9)."""
    # httpx의 get/delete는 json= 을 받지 않는다 — 본문이 필요한 메서드만 실어 보낸다
    kwargs = {"json": {}} if method in {"post", "put", "patch"} else {}
    res = getattr(anon_client, method)(path, **kwargs)
    assert res.status_code == 401


# ── VAPID 공개키 ────────────────────────────────────────────────────
def test_config는_공개키만_돌려준다(client):
    res = client.get("/api/push/config")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"vapid_public_key", "configured"}
    assert body["configured"] is False  # 테스트 환경은 키가 비어 있다
    assert "private" not in res.text.lower()


# ── 기기 등록 ───────────────────────────────────────────────────────
def test_기기를_등록하고_목록에서_본다(client):
    res = client.post("/api/push/devices", json=DEVICE)
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["label"] == "아이폰"

    listed = client.get("/api/push/devices").json()
    assert [d["id"] for d in listed] == [created["id"]]
    # endpoint/키는 응답에 실리지 않는다 — 화면은 라벨만 알면 된다
    assert "endpoint" not in listed[0]
    assert DEVICE["endpoint"] not in client.get("/api/push/devices").text


def test_같은_endpoint_재등록은_행을_늘리지_않는다(client):
    first = client.post("/api/push/devices", json=DEVICE).json()
    again = client.post(
        "/api/push/devices", json={**DEVICE, "label": "아이폰(재등록)"}
    ).json()

    assert again["id"] == first["id"]
    devices = client.get("/api/push/devices").json()
    assert len(devices) == 1
    assert devices[0]["label"] == "아이폰(재등록)"


def test_기기를_삭제한다(client):
    device_id = client.post("/api/push/devices", json=DEVICE).json()["id"]
    assert client.delete(f"/api/push/devices/{device_id}").status_code == 204
    assert client.get("/api/push/devices").json() == []
    assert client.delete(f"/api/push/devices/{device_id}").status_code == 404


def test_남의_기기는_삭제할_수_없다(client, anon_client):
    """IDOR 방지 — user_id는 세션에서만 온다 (절대규칙 9)."""
    device_id = client.post("/api/push/devices", json=DEVICE).json()["id"]
    enable_signup(client)
    res = anon_client.post(
        "/api/auth/signup",
        json={"email": "other@example.com", "password": "commute-1234", "display_name": "남"},
    )
    assert res.status_code == 201, res.text

    assert anon_client.delete(f"/api/push/devices/{device_id}").status_code == 404
    assert len(client.get("/api/push/devices").json()) == 1


# ── 테스트 발송 ─────────────────────────────────────────────────────
def test_테스트_발송은_실패해도_500이_아니다(client):
    """실패 이유를 화면에 그대로 보여주는 것이 이 엔드포인트의 목적이다 (D-9)."""
    client.post("/api/push/devices", json=DEVICE)
    res = client.post("/api/push/test")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["devices"] == 1
    assert body["sent"] == 0  # VAPID 키가 없다
    assert any("VAPID" in err for err in body["errors"])


def test_기기가_없으면_그_사실을_알려준다(client):
    body = client.post("/api/push/test").json()
    assert body["devices"] == 0
    assert body["sent"] == 0
    assert body["errors"]


# ── 디스코드 연동 (opt-in 2단계, D-11) ──────────────────────────────
def test_웹훅_저장_시_즉시_테스트_발송으로_검증한다(client, no_discord_http):
    res = client.put(
        "/api/me/discord", json={"webhook_url": "https://discord.com/api/webhooks/1/xyz"}
    )
    assert res.status_code == 200, res.text
    assert no_discord_http, "저장만 하고 URL을 검증하지 않았다"

    me = res.json()
    assert me["discord_linked"] is True
    # 연동했다고 켜지지는 않는다 — 토글은 별도다
    assert me["discord_enabled"] is False
    # 웹훅 URL은 어떤 응답에도 실리지 않는다 (절대규칙 9)
    assert "webhook" not in res.text.lower() or "discord.com" not in res.text


def test_검증_실패하면_저장하지_않는다(client, monkeypatch):
    """「연동됨」으로 표시된 채 발송이 안 되는 상태가 가장 나쁘다."""

    async def failing_post(self, webhook_url: str, content: str) -> NotifyResult:
        return NotifyResult(errors=("디스코드 웹훅이 유효하지 않다(404)",))

    monkeypatch.setattr(DiscordNotifier, "post", failing_post)
    res = client.put("/api/me/discord", json={"webhook_url": "https://discord.com/bad"})

    assert res.status_code == 422
    assert client.get("/api/me").json()["discord_linked"] is False


def test_연동_없이_토글을_켤_수_없다(client):
    res = client.patch("/api/me/discord", json={"enabled": True})
    assert res.status_code == 422
    assert client.get("/api/me").json()["discord_enabled"] is False


def test_연동_후_토글을_켜고_끈다(client, no_discord_http):
    client.put("/api/me/discord", json={"webhook_url": "https://discord.com/api/webhooks/1/xyz"})

    assert client.patch("/api/me/discord", json={"enabled": True}).json()["discord_enabled"] is True
    assert (
        client.patch("/api/me/discord", json={"enabled": False}).json()["discord_enabled"] is False
    )
    # 토글을 껐다고 연동이 풀리지는 않는다 — 재연동 없이 다시 켤 수 있어야 한다
    assert client.get("/api/me").json()["discord_linked"] is True


def test_연동_해제하면_토글도_내려간다(client, no_discord_http):
    client.put("/api/me/discord", json={"webhook_url": "https://discord.com/api/webhooks/1/xyz"})
    client.patch("/api/me/discord", json={"enabled": True})

    me = client.delete("/api/me/discord").json()
    assert me["discord_linked"] is False
    assert me["discord_enabled"] is False, "URL이 없는데 켜져 있으면 상태가 거짓말을 한다"


def test_토글이_꺼져_있으면_디스코드로_보내지_않는다(client, no_discord_http):
    """`load_targets`가 opt-in 2단계를 판정하는 유일한 지점이다 (D-11)."""
    from app.adapters.notify import load_targets
    from app.storage.db import connect, db_path

    client.put("/api/me/discord", json={"webhook_url": "https://discord.com/api/webhooks/1/xyz"})
    conn = connect(db_path())
    try:
        assert load_targets(conn, 1).discord_webhook is None
        client.patch("/api/me/discord", json={"enabled": True})
        assert load_targets(conn, 1).discord_webhook == "https://discord.com/api/webhooks/1/xyz"
    finally:
        conn.close()


# ── VAPID subject 정규화 (D-34 후속) ─────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ma775100@example.com", "mailto:ma775100@example.com"),  # 스킴 없음 → 붙인다
        ("  me@example.com  ", "mailto:me@example.com"),  # 공백 제거
        ("mailto:me@example.com", "mailto:me@example.com"),  # 이미 있으면 그대로
        ("https://example.com", "https://example.com"),  # https 스킴도 허용된다
        ("", ""),  # 미설정은 미설정으로 둔다
    ],
)
def test_vapid_subject에_스킴이_없으면_mailto를_붙인다(monkeypatch, raw, expected):
    """`py_vapid`는 스킴을 필수로 요구하고, 없으면 **발송 시점에** 죽는다.

    그 시점이 하필 폰에서 알림 켜기를 누른 순간이라 원인이 서버 설정이라는 걸 알기 어렵다.
    실제로 이 실수로 한 번 막혔다 — `.env`에 이메일만 적는 건 흔하다.
    """
    from app.config import Settings

    monkeypatch.setenv("VAPID_SUBJECT", raw)
    assert Settings(_env_file=None).vapid_subject == expected


def test_정규화된_subject는_py_vapid_검사를_통과한다(monkeypatch):
    from py_vapid import _check_sub

    from app.config import Settings

    monkeypatch.setenv("VAPID_SUBJECT", "me@example.com")
    assert _check_sub(Settings(_env_file=None).vapid_subject) is True
