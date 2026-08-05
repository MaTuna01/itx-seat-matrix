"""코레일 계정 연결 API (PLAN 7절, Phase 2 항목 C).

핵심은 **자격증명이 절대 응답에 나오지 않는 것**이다 (CLAUDE.md 절대규칙 9).
평문이 DB에 남지 않는 것도 함께 본다.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.storage.creds import load_korail_cred

KORAIL_ID = "test-korail-id"
KORAIL_PW = "test-korail-pw-9931"


def _db(monkeypatch_env_db: str | None = None) -> sqlite3.Connection:
    from app.storage.db import connect

    conn = connect()
    conn.row_factory = sqlite3.Row
    return conn


def test_korail_starts_unlinked(client) -> None:
    res = client.get("/api/me")
    assert res.status_code == 200
    assert res.json()["korail_linked"] is False


def test_put_korail_links_account(client) -> None:
    res = client.put(
        "/api/me/korail", json={"korail_id": KORAIL_ID, "korail_pw": KORAIL_PW}
    )
    assert res.status_code == 200, res.text
    assert res.json()["korail_linked"] is True
    assert client.get("/api/me").json()["korail_linked"] is True


def test_response_never_contains_credentials(client) -> None:
    """PUT 응답·GET /api/me 어디에도 id/pw가 등장하면 안 된다."""
    put = client.put("/api/me/korail", json={"korail_id": KORAIL_ID, "korail_pw": KORAIL_PW})
    me = client.get("/api/me")
    for res in (put, me):
        body = res.text
        assert KORAIL_PW not in body
        assert KORAIL_ID not in body
        assert "korail_pw" not in res.json()
        assert "korail_pw_enc" not in res.json()


def test_password_is_encrypted_at_rest(client) -> None:
    """DB에 평문 비밀번호가 남으면 안 된다 — Fernet 암호문이어야 한다."""
    client.put("/api/me/korail", json={"korail_id": KORAIL_ID, "korail_pw": KORAIL_PW})
    conn = _db()
    try:
        row = conn.execute("SELECT korail_id, korail_pw_enc FROM user").fetchone()
        assert row["korail_id"] == KORAIL_ID  # id는 평문 저장 (검색·표시용, 비밀 아님)
        assert row["korail_pw_enc"] != KORAIL_PW
        assert KORAIL_PW not in row["korail_pw_enc"]
        assert row["korail_pw_enc"].startswith("gAAAA")  # Fernet 토큰 접두
    finally:
        conn.close()


def test_roundtrip_decrypts_to_original(client) -> None:
    client.put("/api/me/korail", json={"korail_id": KORAIL_ID, "korail_pw": KORAIL_PW})
    conn = _db()
    try:
        user_id = conn.execute("SELECT id FROM user").fetchone()["id"]
        cred = load_korail_cred(conn, user_id)
        assert cred is not None
        assert cred.korail_id == KORAIL_ID
        assert cred.korail_pw == KORAIL_PW
    finally:
        conn.close()


def test_delete_korail_unlinks(client) -> None:
    client.put("/api/me/korail", json={"korail_id": KORAIL_ID, "korail_pw": KORAIL_PW})
    res = client.delete("/api/me/korail")
    assert res.status_code == 200
    assert res.json()["korail_linked"] is False

    conn = _db()
    try:
        user_id = conn.execute("SELECT id FROM user").fetchone()["id"]
        assert load_korail_cred(conn, user_id) is None
    finally:
        conn.close()


def test_put_korail_requires_auth(anon_client) -> None:
    """모든 /api/*는 Depends(current_user) 필수 (절대규칙 9)."""
    res = anon_client.put(
        "/api/me/korail", json={"korail_id": KORAIL_ID, "korail_pw": KORAIL_PW}
    )
    assert res.status_code == 401


def test_delete_korail_requires_auth(anon_client) -> None:
    assert anon_client.delete("/api/me/korail").status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"korail_id": "", "korail_pw": KORAIL_PW},
        {"korail_id": KORAIL_ID, "korail_pw": ""},
        {"korail_id": KORAIL_ID},
        {},
    ],
)
def test_put_korail_rejects_incomplete_payload(client, payload: dict) -> None:
    assert client.put("/api/me/korail", json=payload).status_code == 422


def test_put_korail_does_not_call_korail(client, monkeypatch) -> None:
    """저장 시점에 실 API를 때리면 안 된다 (호출 예절, CLAUDE.md 10).

    자격증명이 틀렸다는 사실은 첫 매트릭스 조회에서 드러나면 충분하다.
    """
    import requests

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("자격증명 저장이 네트워크 호출을 유발했다")

    monkeypatch.setattr(requests.Session, "request", explode)
    res = client.put("/api/me/korail", json={"korail_id": KORAIL_ID, "korail_pw": KORAIL_PW})
    assert res.status_code == 200
