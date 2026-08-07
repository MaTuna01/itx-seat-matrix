"""관리자 사용자 관리 (D-53, 이슈 #54).

삭제 권한이 HTTP로 노출되는 기능이라 **거절해야 할 때 거절하는지**가 이 파일의 코어다.
성공 경로는 한 개고 나머지는 전부 방어 경로다.

`client` = 첫 계정 = 관리자, `anon_client` = 두 번째 사람 (conftest).
"""

from __future__ import annotations

from app.storage.db import get_conn
from tests.conftest import enable_signup
from tests.test_api import make_subscription

SECOND = {"email": "x@example.com", "password": "commute-5678", "display_name": "엑스"}
ADMIN_PW = "commute-1234"  # conftest의 `client` 픽스처가 쓰는 값


def add_second_user(admin_client, anon_client) -> int:
    """가입을 열어 두 번째 계정을 만들고 그 id를 준다. anon_client는 로그인 상태가 된다."""
    enable_signup(admin_client)
    res = anon_client.post("/api/auth/signup", json=SECOND)
    assert res.status_code == 201, res.text
    admin_client.patch("/api/admin/settings", json={"signup_enabled": False})
    return res.json()["id"]


def delete_user(client, user_id: int, password: str = ADMIN_PW):
    # httpx의 `.delete()`는 본문을 받지 않는다 — DELETE + body는 `.request()`로 보낸다.
    # 브라우저 fetch는 그대로 지원하므로 프론트에는 제약이 없다
    return client.request("DELETE", f"/api/admin/users/{user_id}", json={"password": password})


class TestAccessBoundary:
    def test_인증_없이는_401(self, anon_client):
        assert anon_client.get("/api/admin/users").status_code == 401
        assert delete_user(anon_client, 1).status_code == 401

    def test_비관리자는_403(self, client, anon_client):
        add_second_user(client, anon_client)
        assert anon_client.get("/api/admin/users").status_code == 403
        # 두 번째 사람이 관리자를 지우려 해도 403 (자기 비밀번호를 정확히 넣어도)
        assert delete_user(anon_client, 1, SECOND["password"]).status_code == 403


class TestList:
    def test_자격증명은_한_조각도_나가지_않는다(self, client, anon_client):
        add_second_user(client, anon_client)
        anon_client.put(
            "/api/me/korail", json={"korail_id": "0101234", "korail_pw": "korail-pw"}
        )

        rows = client.get("/api/admin/users").json()
        assert len(rows) == 2
        for row in rows:
            assert set(row) == {
                "id", "email", "display_name", "is_admin", "created_at",
                "korail_linked", "discord_linked", "subscription_count",
            }
            # 값에도 새면 안 된다 (키 이름만 보는 검사는 통과시켜버린다)
            assert "korail-pw" not in str(row)
            assert "0101234" not in str(row)

    def test_연동_여부와_구독_수를_준다(self, client, anon_client):
        second_id = add_second_user(client, anon_client)
        anon_client.put(
            "/api/me/korail", json={"korail_id": "0101234", "korail_pw": "korail-pw"}
        )
        make_subscription(anon_client)

        rows = {r["id"]: r for r in client.get("/api/admin/users").json()}
        assert rows[1]["is_admin"] is True
        assert rows[1]["subscription_count"] == 0
        assert rows[second_id]["is_admin"] is False
        assert rows[second_id]["korail_linked"] is True
        assert rows[second_id]["discord_linked"] is False
        assert rows[second_id]["subscription_count"] == 1


class TestDeleteRefusals:
    def test_틀린_비밀번호는_403이고_지워지지_않는다(self, client, anon_client):
        second_id = add_second_user(client, anon_client)
        assert delete_user(client, second_id, "wrong-password").status_code == 403
        assert len(client.get("/api/admin/users").json()) == 2

    def test_자기_자신은_삭제할_수_없다(self, client):
        assert delete_user(client, 1).status_code == 400

    def test_관리자_계정은_삭제할_수_없다(self, client, anon_client):
        second_id = add_second_user(client, anon_client)
        # 승격 API가 없으므로 두 번째 관리자는 DB에서 직접 만든다 (테스트 전용)
        with get_conn() as conn:
            conn.execute("UPDATE user SET is_admin = 1 WHERE id = ?", (second_id,))

        res = delete_user(client, second_id)
        assert res.status_code == 400
        assert "관리자" in res.json()["detail"]

    def test_없는_사용자는_404(self, client):
        assert delete_user(client, 9999).status_code == 404

    def test_비밀번호를_아예_안_보내면_422(self, client, anon_client):
        second_id = add_second_user(client, anon_client)
        assert client.request(
            "DELETE", f"/api/admin/users/{second_id}"
        ).status_code == 422


class TestDelete:
    def test_삭제하면_딸린_데이터와_세션이_함께_사라진다(self, client, anon_client):
        second_id = add_second_user(client, anon_client)
        make_subscription(anon_client)
        assert anon_client.get("/api/me").status_code == 200

        assert delete_user(client, second_id).status_code == 204

        assert [r["id"] for r in client.get("/api/admin/users").json()] == [1]
        # 세션 CASCADE — 재시작 없이 상대는 즉시 로그아웃된다
        assert anon_client.get("/api/me").status_code == 401
        with get_conn() as conn:
            for table in ("session", "preset", "subscription", "push_device"):
                left = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (second_id,)
                ).fetchone()[0]
                assert left == 0, f"{table}에 고아 행이 남았다"

    def test_지운_이메일로_다시_가입할_수_있다(self, client, anon_client):
        """UNIQUE 제약이 살아 있으면 삭제가 반쪽짜리다."""
        second_id = add_second_user(client, anon_client)
        assert delete_user(client, second_id).status_code == 204

        enable_signup(client)
        assert anon_client.post("/api/auth/signup", json=SECOND).status_code == 201
