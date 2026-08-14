"""API 스모크 — 인증 경계 + PATCH 상태 전이 422 (PLAN 13절).

`api/`는 원칙적으로 생략 가능한 영역이지만, 13절이 명시한 두 가지는 확인한다:
① 인증(401) ② PATCH 상태 전이 검증(422).
여기에 절대규칙 5(화면 조회가 알림 상태를 건드리지 않는다)를 함께 잠근다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.adapters.korail2_adapter import CredentialsRequired, TrainStopsNotCached
from app.api.deps import get_korail_port
from app.domain.models import KST
from app.storage.db import connect, db_path, dt_from_db
from app.storage.stations import Station, upsert
from tests.conftest import enable_signup, stop_infos

# 목업 열차는 운행일 08:00~08:56에 달린다. 내일 날짜를 쓰면 "운행 전"이 확정돼
# 현재 구간이 시계와 무관하게 0이 된다 (테스트 결정성)
#
# ★ **반드시 KST 기준 "내일"이어야 한다** (절대규칙 1). `date.today()`는 naive·로컬 TZ라
# UTC 러너에서 KST보다 하루 뒤처지고, 그러면 "내일"이 **이미 출발한 오늘**이 된다 —
# `current_seg_idx`가 0이 아니게 되고 첫 폴 포인트도 지나 있어 세 테스트가 깨졌다.
# KST 00:00~09:00(= UTC 15:00~24:00)에만 나타나서 로컬에서는 거의 안 보인다 (→ D-44 CI가 잡았다).
RIDE_DATE = (datetime.now(KST).date() + timedelta(days=1)).isoformat()


def make_subscription(client, **overrides) -> dict:
    payload = {
        "train_no": "1004",
        "date": RIDE_DATE,
        "board_at": "천안",
        "alight_at": "서울",
        "status": "STANDING",
    }
    payload.update(overrides)
    res = client.post("/api/subscriptions", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


class TestAuth:
    def test_인증_없이는_401(self, anon_client):
        assert anon_client.get("/api/me").status_code == 401
        assert anon_client.get("/api/subscriptions").status_code == 401

    def test_로그인하면_내_정보를_돌려준다(self, client):
        res = client.get("/api/me")
        assert res.status_code == 200
        body = res.json()
        assert body["email"] == "me@example.com"
        assert body["korail_linked"] is False
        # 자격증명·웹훅은 응답에 절대 나오지 않는다 (절대규칙 9)
        assert "korail_pw_enc" not in body and "discord_webhook_enc" not in body

    def test_잘못된_비밀번호는_401(self, client):
        res = client.post(
            "/api/auth/login", json={"email": "me@example.com", "password": "wrong-password"}
        )
        assert res.status_code == 401

    def test_로그아웃하면_세션이_죽는다(self, client):
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/me").status_code == 401


class TestRememberMe:
    """세션 수명 이원화 (D-23). 쿠키와 서버 세션을 함께 가른다."""

    def _cookie_header(self, res):
        return res.headers["set-cookie"]

    def test_미체크면_브라우저_세션_쿠키다(self, anon_client):
        res = anon_client.post(
            "/api/auth/signup",
            json={"email": "a@example.com", "password": "commute-1234", "display_name": "나"},
        )
        assert res.status_code == 201
        # Max-Age/Expires가 없어야 브라우저 종료 시 사라진다
        header = self._cookie_header(res).lower()
        assert "max-age" not in header and "expires" not in header

    def test_체크하면_지속_쿠키_30일(self, anon_client):
        anon_client.post(
            "/api/auth/signup",
            json={"email": "a@example.com", "password": "commute-1234", "display_name": "나"},
        )
        anon_client.post("/api/auth/logout")
        res = anon_client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "commute-1234", "remember": True},
        )
        assert res.status_code == 200
        assert f"Max-Age={30 * 24 * 3600}" in self._cookie_header(res)

    def test_서버_세션_만료도_함께_갈린다(self, anon_client):
        """쿠키만 바꾸면 서버 세션이 30일 살아 있어 반쪽짜리다."""
        anon_client.post(
            "/api/auth/signup",
            json={"email": "a@example.com", "password": "commute-1234", "display_name": "나"},
        )
        with connect(db_path()) as conn:
            transient = conn.execute(
                "SELECT persistent, created_at, expires_at FROM session"
            ).fetchone()
        assert transient["persistent"] == 0
        assert dt_from_db(transient["expires_at"]) - dt_from_db(transient["created_at"]) == timedelta(
            hours=12
        )

        anon_client.post("/api/auth/logout")
        anon_client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "commute-1234", "remember": True},
        )
        with connect(db_path()) as conn:
            row = conn.execute("SELECT persistent, created_at, expires_at FROM session").fetchone()
        assert row["persistent"] == 1
        assert dt_from_db(row["expires_at"]) - dt_from_db(row["created_at"]) == timedelta(days=30)

    def test_슬라이딩_연장은_원래_수명으로만_한다(self, anon_client):
        """임시 세션이 접속할 때마다 30일로 승격되면 규칙이 무의미해진다."""
        anon_client.post(
            "/api/auth/signup",
            json={"email": "a@example.com", "password": "commute-1234", "display_name": "나"},
        )
        anon_client.get("/api/me")  # 슬라이딩 연장 발생
        with connect(db_path()) as conn:
            row = conn.execute("SELECT created_at, expires_at FROM session").fetchone()
        gap = dt_from_db(row["expires_at"]) - dt_from_db(row["created_at"])
        assert gap < timedelta(days=1)


class TestSignupLock:
    """가입 잠금은 DB에 있고 관리자가 토글한다 (D-24)."""

    def test_첫_계정은_부트스트랩으로_열리고_관리자가_된다(self, client):
        assert client.get("/api/me").json()["is_admin"] is True
        assert client.get("/api/admin/settings").json() == {"signup_enabled": False}

    def test_두_번째_가입은_기본_잠김이다(self, client, anon_client):
        res = anon_client.post(
            "/api/auth/signup",
            json={"email": "x@example.com", "password": "commute-1234", "display_name": "x"},
        )
        assert res.status_code == 403

    def test_관리자가_켜면_가입되고_다시_끌_수_있다(self, client, anon_client):
        enable_signup(client)
        res = anon_client.post(
            "/api/auth/signup",
            json={"email": "x@example.com", "password": "commute-1234", "display_name": "x"},
        )
        assert res.status_code == 201
        assert res.json()["is_admin"] is False  # 관리자는 첫 계정뿐

        client.patch("/api/admin/settings", json={"signup_enabled": False})
        with TestClient(app) as third:
            assert third.post(
                "/api/auth/signup",
                json={"email": "y@example.com", "password": "commute-1234", "display_name": "y"},
            ).status_code == 403

    def test_비관리자는_토글할_수_없다(self, client, anon_client):
        enable_signup(client)
        anon_client.post(
            "/api/auth/signup",
            json={"email": "x@example.com", "password": "commute-1234", "display_name": "x"},
        )
        assert anon_client.get("/api/admin/settings").status_code == 403
        assert anon_client.patch(
            "/api/admin/settings", json={"signup_enabled": True}
        ).status_code == 403

    def test_인증_없이는_401(self, anon_client):
        assert anon_client.get("/api/admin/settings").status_code == 401


class TestSubscriptionTransition:
    def test_SEATED_인데_좌석이_없으면_422(self, client):
        res = client.post(
            "/api/subscriptions",
            json={
                "train_no": "1004", "date": RIDE_DATE, "board_at": "천안",
                "alight_at": "서울", "status": "SEATED",
            },
        )
        assert res.status_code == 422

    def test_뒤집힌_구간으로는_구독을_만들_수_없다(self, client):
        """구간 스왑(#67)의 서버측 안전장치 — 방향이 틀리면 422로 거부한다."""
        res = client.post(
            "/api/subscriptions",
            json={
                "train_no": "1004", "date": RIDE_DATE, "board_at": "서울",
                "alight_at": "천안", "status": "STANDING",
            },
        )
        assert res.status_code == 422

    def test_구독_생성시_첫_폴_포인트를_기록한다(self, client):
        sub = make_subscription(client)
        # 천안 08:00 - 10분 (D-19 재시작 내구성 포인터)
        assert sub["next_poll_at"].startswith(f"{RIDE_DATE}T07:50:00")

    def test_앉음_전이(self, client):
        sub = make_subscription(client)
        res = client.patch(
            f"/api/subscriptions/{sub['id']}",
            json={"status": "SEATED", "my_car": 4, "my_seat_no": "1B"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "SEATED"
        assert (res.json()["my_car"], res.json()["my_seat_no"]) == (4, "1B")

    def test_자리_이동_전이는_스냅샷을_무효화한다(self, client):
        sub = make_subscription(client, status="SEATED", my_car=3, my_seat_no="7A")
        with connect(db_path()) as conn:
            conn.execute(
                "UPDATE subscription SET last_cells_snapshot = ?, last_verdict_hash = ?"
                " WHERE id = ?",
                ("[true, false]", "old-hash", sub["id"]),
            )
        client.patch(f"/api/subscriptions/{sub['id']}", json={"my_car": 4, "my_seat_no": "1B"})
        with connect(db_path()) as conn:
            row = conn.execute(
                "SELECT last_cells_snapshot, last_verdict_hash FROM subscription WHERE id = ?",
                (sub["id"],),
            ).fetchone()
        assert row["last_cells_snapshot"] is None  # D-16
        assert row["last_verdict_hash"] == "old-hash"  # 베이스라인 재발송 방지 (D-20)

    def test_일어남_전이는_좌석을_비운다(self, client):
        sub = make_subscription(client, status="SEATED", my_car=3, my_seat_no="7A")
        res = client.patch(f"/api/subscriptions/{sub['id']}", json={"status": "STANDING"})
        assert res.status_code == 200
        assert res.json()["my_car"] is None and res.json()["my_seat_no"] is None

    def test_SEATED로_바꾸면서_좌석을_안_주면_422(self, client):
        sub = make_subscription(client)
        res = client.patch(f"/api/subscriptions/{sub['id']}", json={"status": "SEATED"})
        assert res.status_code == 422

    def test_남의_구독은_보이지_않는다(self, client, anon_client):
        sub = make_subscription(client)
        enable_signup(client)
        anon_client.post(
            "/api/auth/signup",
            json={"email": "other@example.com", "password": "commute-1234", "display_name": "남"},
        )
        assert anon_client.patch(
            f"/api/subscriptions/{sub['id']}", json={"status": "STANDING"}
        ).status_code == 404

    def test_삭제하면_비활성화된다(self, client):
        sub = make_subscription(client)
        assert client.delete(f"/api/subscriptions/{sub['id']}").status_code == 204
        assert client.get("/api/subscriptions").json() == []

    def test_active_only_false는_종료한_구독을_최근순으로_준다(self, client):
        """탑승 등록 화면의 직전 구간 프리필이 이 파라미터에 걸려 있다 (이슈 #12).

        기본값(활성만)이 바뀌면 라우팅이 끝난 열차의 매트릭스를 띄우고,
        정렬이 바뀌면 프리필이 엉뚱한 구간을 채운다. 둘 다 조용히 틀린다.
        """
        older = make_subscription(client, board_at="천안", alight_at="수원")
        newer = make_subscription(client, board_at="평택", alight_at="서울")
        for sub in (older, newer):
            client.delete(f"/api/subscriptions/{sub['id']}")

        assert client.get("/api/subscriptions").json() == [], "기본값은 활성만"

        rows = client.get("/api/subscriptions", params={"active_only": "false"}).json()
        assert [r["id"] for r in rows] == [newer["id"], older["id"]], "created_at DESC"
        assert rows[0]["board_at"] == "평택" and rows[0]["alight_at"] == "서울"
        assert all(r["active"] is False for r in rows)

    def test_남의_종료된_구독은_보이지_않는다(self, client, anon_client):
        """프리필 소스가 user_id로 갈리는지 (절대규칙 9)."""
        mine = make_subscription(client)
        client.delete(f"/api/subscriptions/{mine['id']}")
        enable_signup(client)
        anon_client.post(
            "/api/auth/signup",
            json={"email": "other2@example.com", "password": "commute-1234", "display_name": "남"},
        )
        assert anon_client.get(
            "/api/subscriptions", params={"active_only": "false"}
        ).json() == []


class TestMatrix:
    def test_응답_스키마는_PLAN_7절과_같다(self, client):
        res = client.get(
            f"/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울", "my_seat": "3-7A"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["stops"] == ["천안", "평택", "수원", "안양", "영등포", "서울"]
        assert body["current_seg_idx"] == 0
        assert body["position_source"] == "schedule"  # GPS 파라미터를 안 보냈다
        assert len(body["seats"]) == 18
        assert body["sub_status"] == "SEATED"
        verdict = body["verdict"]
        assert verdict["my_seat_status"] == "SOLD_FROM"  # 목업 3-7A는 [T,T,T,F,F]
        assert verdict["my_seat_sold_from"] == "천안"
        # SEATED는 동률이면 내 호차(3호차) 근접순 → 4-1B보다 3-8B가 먼저다
        assert verdict["move_to"][0] == {
            # clear_from_idx: 지금(실효 시작 0)부터 앉을 수 있다는 뜻 (→ D-46)
            "car": 3, "seat_no": "8B", "clear_from_idx": 0, "clear_until_idx": 5,
            "clear_all": True,
        }
        # 하차역까지 비는 좌석은 이 둘뿐이다 (clear_all 좌석이 있으면 그것만 추천)
        assert [f"{r['car']}-{r['seat_no']}" for r in verdict["move_to"]] == ["3-8B", "4-1B"]
        # 지금 앉을 수 있는 좌석이 있으므로 지연 착석 목록은 별도로 유지된다 (합치지 않는다)
        assert "move_to_later" in verdict
        assert body["failed_seg_idxs"] == []  # 정상 조회 (→ D-48)
        assert body["snapshots"] == []  # 운행 전 — 갭 구간이 없다 (→ D-57)
        assert body["next_poll"] == {"station": "천안", "offset_min": 10, "basis": "arrival"}

    def test_한_구간이_실패해도_200과_부분_매트릭스를_준다(self, client, monkeypatch):
        """★ 회귀 방어 (이슈 #40). 예전에는 한 구간의 실패가 **매트릭스 전체를 500**으로
        만들었다 — 이미 받아온 다른 구간의 좌석표까지 함께 버려진다.

        실측: 출발 직후 `ERR911081 좌석선택 예약불가`로 화면이 4번 500이 났다.
        `failed_seg_idxs`가 없으면 화면은 실패를 **매진**으로 그린다 — 전혀 다른 정보다.
        """
        from app.adapters.korail_client import KorailApiError
        from app.adapters.korail_mock import MockKorailAdapter

        real = MockKorailAdapter.get_seat_map

        async def flaky(self, cred, train_no, d, frm, to):  # noqa: ANN001, ANN202
            if frm == "수원":
                raise KorailApiError("ERR911081", "좌석선택 예약불가")
            return await real(self, cred, train_no, d, frm, to)

        monkeypatch.setattr(MockKorailAdapter, "get_seat_map", flaky)

        res = client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["failed_seg_idxs"] == [2]  # 수원→안양
        assert body["seats"], "성공한 구간의 좌석표까지 함께 버려졌다"
        # 실패를 매진으로 읽으면 여기서 환승을 권한다
        assert body["verdict"]["all_sold_after_current"] is False

    def test_좌석_미지정이면_입석_관점_판정(self, client):
        res = client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
        )
        body = res.json()
        assert body["sub_status"] == "STANDING"
        assert body["verdict"]["my_seat_status"] is None

    def test_노선에_없는_역은_404(self, client):
        res = client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "부산", "alight_at": "서울"},
        )
        assert res.status_code == 404

    def test_뒤집힌_구간은_422(self, client):
        """구간 스왑(#67)의 서버측 안전장치 — 같은 열차에서 방향이 반대면 조회를 거부한다."""
        res = client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "서울", "alight_at": "천안"},
        )
        assert res.status_code == 422

    def test_잘못된_좌석_형식은_422(self, client):
        res = client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울", "my_seat": "7A"},
        )
        assert res.status_code == 422

    def test_화면_조회는_알림_상태를_건드리지_않는다(self, client):
        """절대규칙 5 / D-13·D-17 — 기록은 스케줄러만 한다."""
        sub = make_subscription(client, status="SEATED", my_car=3, my_seat_no="7A")
        client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울", "my_seat": "3-7A"},
        )
        with connect(db_path()) as conn:
            row = conn.execute(
                "SELECT last_verdict_hash, last_cells_snapshot, last_notified_at"
                " FROM subscription WHERE id = ?",
                (sub["id"],),
            ).fetchone()
        assert row["last_verdict_hash"] is None
        assert row["last_cells_snapshot"] is None
        assert row["last_notified_at"] is None

    # ── 갭 구간 스냅샷 (→ D-57) ─────────────────────────────────────
    def _mid_ride(self, hour: int, minute: int, monkeypatch) -> None:
        """운행 중 시각으로 화면 시계를 고정한다 (트레인 시각표는 08:00~08:56)."""
        from datetime import date as _date2, time as _time2

        import app.api.trains as trains_mod

        frozen = datetime.combine(
            _date2.fromisoformat(RIDE_DATE), _time2(hour, minute), tzinfo=KST
        )
        monkeypatch.setattr(trains_mod, "now_kst", lambda: frozen)

    def test_주행_중이면_갭_구간_스냅샷을_내려준다(self, client, monkeypatch):
        """★ D-57의 핵심 배선. 08:16 = 평택 출발(08:15) 후 수원 도착(08:26) 전 —
        타고 있는 평택→수원 구간은 조회 범위 밖이지만, 마지막 성공 조회가 있으면
        표시 전용으로 내려간다. 판정(start_seg_idx)은 D-47대로 다음 구간이다."""
        from datetime import date as _date2, time as _time2

        from app.domain.models import SeatMap, SeatState
        from app.storage import seat_snapshot

        as_of = datetime.combine(_date2.fromisoformat(RIDE_DATE), _time2(8, 14), tzinfo=KST)
        with connect(db_path()) as conn:
            seat_snapshot.record(
                conn,
                SeatMap(
                    train_no="1004", date=_date2.fromisoformat(RIDE_DATE),
                    frm="평택", to="수원",
                    seats=[
                        SeatState(car=3, seat_no="7A", sold=True),
                        SeatState(car=4, seat_no="1B", sold=False),
                    ],
                    fetched_at=as_of,
                ),
            )
        self._mid_ride(8, 16, monkeypatch)

        res = client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["current_seg_idx"] == 1  # 위치: 평택→수원 주행 중
        assert body["verdict"]["start_seg_idx"] == 2  # 판정은 수원부터 (D-47 불변)
        assert len(body["snapshots"]) == 1
        snap = body["snapshots"][0]
        assert snap["seg_idx"] == 1
        assert snap["as_of"].startswith(f"{RIDE_DATE}T08:14:00")
        assert {(s["car"], s["seat_no"], s["sold"]) for s in snap["seats"]} == {
            (3, "7A", True), (4, "1B", False),
        }

    def test_스냅샷이_없으면_빈_리스트로_폴백한다(self, client, monkeypatch):
        self._mid_ride(8, 16, monkeypatch)
        res = client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["snapshots"] == []  # 프론트는 기존 회색(past) 표시로 폴백

    def test_스냅샷이_있어도_알림_상태는_그대로다(self, client, monkeypatch):
        """절대규칙 5 재확인 — 스냅샷 배선이 화면 조회에 쓰기 경로를 더했지만
        (seat_snapshot), 알림 상태는 여전히 스케줄러만 기록한다."""
        sub = make_subscription(client, status="SEATED", my_car=3, my_seat_no="7A")
        self._mid_ride(8, 16, monkeypatch)
        client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울", "my_seat": "3-7A"},
        )
        with connect(db_path()) as conn:
            row = conn.execute(
                "SELECT last_verdict_hash, last_cells_snapshot FROM subscription WHERE id = ?",
                (sub["id"],),
            ).fetchone()
        assert row["last_verdict_hash"] is None
        assert row["last_cells_snapshot"] is None

    # ── GPS 포그라운드 보정 (D-13) ──────────────────────────────────
    def _seed_mock_route_coords(self) -> None:
        """목업 노선(천안~서울)에 일직선 합성 좌표를 넣는다.

        실좌표가 아니라 단위 간격 직선을 쓴다 — 구간 판별이 모호하지 않고
        실좌표 값 변경에 흔들리지 않는 결정적 테스트를 위해서다.
        """
        with connect(db_path()) as conn:
            now = datetime.now(KST)
            for i, name in enumerate(["천안", "평택", "수원", "안양", "영등포", "서울"]):
                upsert(conn, Station(name=name, lat=36.0 + i * 0.1, lng=127.0), source="t", now=now)

    def test_GPS_좌표가_있으면_현재_구간을_보정한다(self, client):
        self._seed_mock_route_coords()
        now_ms = datetime.now(KST).timestamp() * 1000
        res = client.get(
            "/api/trains/1004/matrix",
            params={
                "date": RIDE_DATE, "board_at": "천안", "alight_at": "서울",
                "lat": 36.25, "lng": 127.0,  # 수원(36.2)~안양(36.3) 사이 → 구간 idx 2
                "gps_accuracy_m": 20, "gps_fixed_at_ms": now_ms,
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["position_source"] == "gps"
        assert body["current_seg_idx"] == 2

    def test_GPS_정확도가_나쁘면_무시하고_시각표_추정을_쓴다(self, client):
        self._seed_mock_route_coords()
        now_ms = datetime.now(KST).timestamp() * 1000
        res = client.get(
            "/api/trains/1004/matrix",
            params={
                "date": RIDE_DATE, "board_at": "천안", "alight_at": "서울",
                "lat": 36.25, "lng": 127.0,
                "gps_accuracy_m": 500,  # 기본 임계값(100m) 초과
                "gps_fixed_at_ms": now_ms,
            },
        )
        body = res.json()
        assert body["position_source"] == "schedule"
        assert body["current_seg_idx"] == 0

    def test_GPS_시각이_낡으면_무시하고_시각표_추정을_쓴다(self, client):
        self._seed_mock_route_coords()
        stale_ms = (datetime.now(KST).timestamp() - 60) * 1000  # 60초 전
        res = client.get(
            "/api/trains/1004/matrix",
            params={
                "date": RIDE_DATE, "board_at": "천안", "alight_at": "서울",
                "lat": 36.25, "lng": 127.0,
                "gps_accuracy_m": 20, "gps_fixed_at_ms": stale_ms,
            },
        )
        body = res.json()
        assert body["position_source"] == "schedule"

    def test_GPS_파라미터_일부만_오면_무시한다(self, client):
        """★ 넷 다 있어야 시도한다 — 신선도를 판단할 수 없는 상태로 좌표만 믿으면 안 된다."""
        self._seed_mock_route_coords()
        res = client.get(
            "/api/trains/1004/matrix",
            params={
                "date": RIDE_DATE, "board_at": "천안", "alight_at": "서울",
                "lat": 36.25, "lng": 127.0,  # accuracy/fixed_at 누락
            },
        )
        body = res.json()
        assert body["position_source"] == "schedule"

    def test_GPS_좌표가_노선에서_멀면_시각표_추정으로_폴백(self, client):
        self._seed_mock_route_coords()
        now_ms = datetime.now(KST).timestamp() * 1000
        res = client.get(
            "/api/trains/1004/matrix",
            params={
                "date": RIDE_DATE, "board_at": "천안", "alight_at": "서울",
                "lat": 35.115, "lng": 129.042,  # 부산 — 완전히 다른 노선
                "gps_accuracy_m": 20, "gps_fixed_at_ms": now_ms,
            },
        )
        body = res.json()
        assert body["position_source"] == "schedule"

    def test_station_테이블에_좌표가_없으면_시각표_추정을_쓴다(self, client):
        """station 테이블 미적재 개발 환경에서도 화면이 죽지 않아야 한다."""
        now_ms = datetime.now(KST).timestamp() * 1000
        res = client.get(
            "/api/trains/1004/matrix",
            params={
                "date": RIDE_DATE, "board_at": "천안", "alight_at": "서울",
                "lat": 36.25, "lng": 127.0,
                "gps_accuracy_m": 20, "gps_fixed_at_ms": now_ms,
            },
        )
        assert res.status_code == 200
        assert res.json()["position_source"] == "schedule"


class _CredentialsRequiredPort:
    """`Korail2Adapter`가 계정 미연결일 때의 동작을 흉내낸다."""

    async def list_stations(self):
        return []

    async def search_trains(self, cred, d, frm, to, at=None):
        raise CredentialsRequired("코레일 계정이 연결되지 않았습니다.")

    async def get_train_name(self, train_no, d):
        return None

    async def get_stops(self, cred, train_no, d):
        return stop_infos()

    async def get_seat_map(self, cred, train_no, d, frm, to):
        raise CredentialsRequired("코레일 계정이 연결되지 않았습니다.")


class _TrainStopsNotCachedPort:
    """`Korail2Adapter`가 정차역 캐시 미스일 때의 동작을 흉내낸다 (D-29)."""

    async def list_stations(self):
        return []

    async def search_trains(self, cred, d, frm, to, at=None):
        return []

    async def get_train_name(self, train_no, d):
        return None

    async def get_stops(self, cred, train_no, d):
        raise TrainStopsNotCached("열차 9999의 정차역이 캐시에 없다.")

    async def get_seat_map(self, cred, train_no, d, frm, to):
        raise AssertionError("get_stops에서 이미 끝났어야 한다")


class TestKorailErrorMapping:
    """계정 미연결/정차역 캐시 미스가 500이 아니라 의미 있는 상태코드로 나가는지.

    실사용(ADAPTER=korail2) 중 `CredentialsRequired`/`TrainStopsNotCached`가
    그대로 노출돼 500이 나던 버그의 회귀 테스트다.
    """

    def _override(self, port):
        app.dependency_overrides[get_korail_port] = lambda: port

    def teardown_method(self):
        app.dependency_overrides.pop(get_korail_port, None)

    def test_계정_미연결_matrix조회는_409(self, client):
        self._override(_CredentialsRequiredPort())
        res = client.get(
            "/api/trains/1004/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
        )
        assert res.status_code == 409

    def test_계정_미연결_열차검색은_409(self, client):
        self._override(_CredentialsRequiredPort())
        res = client.get(
            "/api/trains/search",
            params={"date": RIDE_DATE, "from": "천안", "to": "서울"},
        )
        assert res.status_code == 409

    def test_정차역_캐시_미스는_404(self, client):
        self._override(_TrainStopsNotCachedPort())
        res = client.get(
            "/api/trains/9999/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
        )
        assert res.status_code == 404


def test_프리셋은_사용자별로_보인다(client, anon_client):
    res = client.post(
        "/api/presets",
        json={
            "name": "출근", "from_station": "천안", "to_station": "서울",
            "usual_train_nos": ["1004"],
        },
    )
    assert res.status_code == 201
    assert res.json()["poll_offsets_min"] == [10, 4]
    assert len(client.get("/api/presets").json()) == 1

    enable_signup(client)
    anon_client.post(
        "/api/auth/signup",
        json={"email": "other@example.com", "password": "commute-1234", "display_name": "남"},
    )
    assert anon_client.get("/api/presets").json() == []


def test_프리셋은_계정당_5개까지다(client):
    """즐겨찾기 노선 상한 (D-56). 6번째는 409, 하나 지우면 다시 저장된다."""
    for i in range(5):
        res = client.post(
            "/api/presets",
            json={"name": f"노선{i}", "from_station": "천안", "to_station": "서울"},
        )
        assert res.status_code == 201

    res = client.post(
        "/api/presets",
        json={"name": "여섯째", "from_station": "서울", "to_station": "천안"},
    )
    assert res.status_code == 409
    assert "5개" in res.json()["detail"]
    assert len(client.get("/api/presets").json()) == 5

    first_id = client.get("/api/presets").json()[0]["id"]
    assert client.delete(f"/api/presets/{first_id}").status_code == 204
    res = client.post(
        "/api/presets",
        json={"name": "여섯째", "from_station": "서울", "to_station": "천안"},
    )
    assert res.status_code == 201


def test_프리셋_상한은_사용자별이다(client, anon_client):
    """다른 계정이 5개를 채워도 내 상한과 무관하다 (user_id 귀속, PLAN 6절)."""
    for i in range(5):
        assert (
            client.post(
                "/api/presets",
                json={"name": f"노선{i}", "from_station": "천안", "to_station": "서울"},
            ).status_code
            == 201
        )

    enable_signup(client)
    anon_client.post(
        "/api/auth/signup",
        json={"email": "other@example.com", "password": "commute-1234", "display_name": "남"},
    )
    res = anon_client.post(
        "/api/presets",
        json={"name": "퇴근", "from_station": "서울", "to_station": "천안"},
    )
    assert res.status_code == 201


class TestTrainPicker:
    """역 드롭다운 + 시각 하한 검색 (D-25). Phase 1은 Mock, Phase 2에서 소스만 교체."""

    def test_역_목록(self, client):
        res = client.get("/api/stations")
        assert res.status_code == 200
        assert [s["name"] for s in res.json()] == ["천안", "평택", "수원", "안양", "영등포", "서울"]

    def test_역_목록도_인증이_필요하다(self, anon_client):
        assert anon_client.get("/api/stations").status_code == 401

    def test_시각을_안_주면_그날_전체_편성(self, client):
        res = client.get(
            "/api/trains/search", params={"date": RIDE_DATE, "from": "천안", "to": "서울"}
        )
        assert res.status_code == 200
        trains = res.json()
        assert [t["train_no"] for t in trains] == ["1004", "1008", "1012", "1016"]
        assert trains[0]["dep_time"].startswith(f"{RIDE_DATE}T08:00:00")

    def test_시각은_정확한_시각이_아니라_하한이다(self, client):
        """'오후 5시 이후 열차'를 전부 준다 — 통근은 그렇게 고른다."""
        res = client.get(
            "/api/trains/search",
            params={"date": RIDE_DATE, "from": "천안", "to": "서울", "time": "17:00"},
        )
        assert [t["train_no"] for t in res.json()] == ["1012", "1016"]

    def test_출발_시각_오름차순(self, client):
        trains = client.get(
            "/api/trains/search", params={"date": RIDE_DATE, "from": "천안", "to": "서울"}
        ).json()
        assert [t["dep_time"] for t in trains] == sorted(t["dep_time"] for t in trains)

    def test_구간이_뒤집히면_결과가_없다(self, client):
        res = client.get(
            "/api/trains/search", params={"date": RIDE_DATE, "from": "서울", "to": "천안"}
        )
        assert res.json() == []

    def test_잘못된_시각_형식은_422(self, client):
        res = client.get(
            "/api/trains/search",
            params={"date": RIDE_DATE, "from": "천안", "to": "서울", "time": "오후5시"},
        )
        assert res.status_code == 422

    def test_편성마다_열차명이_다르다(self, client):
        """기준 편성 이름을 상수로 쓰면 다른 편성에 엉뚱한 이름이 붙는다."""
        def name(train_no):
            return client.get(
                f"/api/trains/{train_no}/matrix",
                params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
            ).json()["train_name"]

        assert name("1004") == "ITX-마음"
        assert name("1012") == "무궁화호"

    def test_편성마다_좌석표가_다르다(self, client):
        def seats(train_no):
            return client.get(
                f"/api/trains/{train_no}/matrix",
                params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
            ).json()["seats"]

        assert seats("1004") != seats("1012")

    def test_목업에_없는_열차번호는_404(self, client):
        res = client.get(
            "/api/trains/9999/matrix",
            params={"date": RIDE_DATE, "board_at": "천안", "alight_at": "서울"},
        )
        assert res.status_code == 404
        assert client.post(
            "/api/subscriptions",
            json={
                "train_no": "9999", "date": RIDE_DATE, "board_at": "천안",
                "alight_at": "서울", "status": "STANDING",
            },
        ).status_code == 404
