"""코레일 모바일 API 저수준 클라이언트 (**동기**) — Phase 2 항목 B/E/F.

`korail2`는 로그인만 시킨다 (비밀번호 AES 암호화 + `code.do` 왕복을 대신해 준다).
데이터 조회는 **원시 POST**로 직접 한다 — 이유:

- 좌석맵 엔드포인트(`research.*`)가 korail2에 **아예 없다** (Phase 0 감사)
- `ScheduleView` 응답의 **운행 순번**(`h_dpt_stn_run_ordr`/`h_arv_stn_run_ordr`)이
  좌석맵 페이로드에 반드시 필요한데 korail2의 `Train` 객체는 이를 버린다

이 모듈은 동기다. **async에서 직접 부르지 마라** — `korail2_adapter`가
`asyncio.to_thread`로 감싼다 (CLAUDE.md 절대규칙 3).

세션은 프로세스 내 캐시이고 **만료를 감지했을 때만** 재로그인한다.
"""

from __future__ import annotations

import threading
from datetime import date as _date
from datetime import datetime
from typing import Any

from app.adapters.korail_dynapath import DynaPathSession, apply_bypass
from app.domain.models import KST, KorailCred, SeatState, TrainSummary

HOST = "https://smart.letskorail.com:443"
MOBILE = f"{HOST}/classes/com.korail.mobile"

URL_SCHEDULE = f"{MOBILE}.seatMovie.ScheduleView"  # 열차 조회
URL_CARS = f"{MOBILE}.research.TrainResearch"  # 호차별 잔여석
URL_SEATS = f"{MOBILE}.research.ResidualSeatsResearch.do"  # ★ 좌석별 판매가능 Y/N
URL_STATIONS = f"{MOBILE}.common.stationdata"  # 역 코드 테이블

DEVICE = "AD"
GENERAL_CLASS = "1"  # txtPsrmClCd — 일반실
SENTINEL_SEAT = "0A"  # 좌석 목록에 섞여 오는 자리표시자. 좌석이 아니다

# 로그인 필요 (korail2 NeedToLoginError.codes)
NEED_LOGIN_CODES = frozenset({"P058"})
# 결과 없음 — 실패가 아니라 '해당 없음'이다 (korail2 NoResultsError.codes)
NO_RESULT_CODES = frozenset({"P100", "WRG000000", "WRD000061", "WRT300005"})

# 매진 — **실패가 아니라 데이터다** (D-36). "이 구간엔 팔 좌석이 없다"는 뜻이고,
# 좌석맵 관점에서는 '전 좌석 판매됨'과 같다. 조회 에러로 취급하면 앞 구간에서 이미
# 받아온 좌석표까지 함께 버려진다.
#
# 코드값을 확정하지 못해 **문구도 함께 본다.** 코레일은 같은 상황에 여러 코드를 쓰고
# 우리가 관측한 표본이 좁다. 문구 매칭은 취약하지만, 놓쳤을 때의 대가(조회 전체 실패)가
# 오탐의 대가(매진으로 잘못 표시 → 추천에서 빠짐)보다 크다.
# 원칙 1(역/노선 하드코딩 금지)과는 무관하다 — 외부 API의 에러 문구지 도메인 값이 아니다.
# 실측값 (배포 첫날 EC2 로그, 2026-08-06 16:18 KST — 수원→영등포 호차 조회):
#   ERI411321 / "잔여석이 없습니다."
# 문구 힌트("잔여석")로도 잡히던 건이지만, 코드가 있으면 코레일이 문구를 바꿔도 견딘다.
SOLD_OUT_CODES: frozenset[str] = frozenset({"ERI411321"})
SOLD_OUT_HINTS = ("잔여석", "매진", "좌석이 없", "여석이 없")


class KorailApiError(RuntimeError):
    """코레일이 `strResult=FAIL`을 준 경우."""

    def __init__(self, msg_cd: str, msg_txt: str) -> None:
        super().__init__(f"{msg_cd}: {msg_txt}")
        self.msg_cd = msg_cd
        self.msg_txt = msg_txt


class KorailSessionExpired(KorailApiError):
    """세션 만료. 재로그인 후 1회 재시도한다."""


class KorailSoldOut(KorailApiError):
    """이 구간에 팔 좌석이 없다 (D-36).

    **조회 실패가 아니라 '전부 판매됨'이라는 데이터다.** 재시도 대상도 아니다 —
    30초 뒤에 물어도 매진은 매진이다. 좌석맵 경로에서 빈 결과로 흡수한다.
    """


def looks_sold_out(msg_cd: str, msg_txt: str) -> bool:
    """코레일 FAIL 응답이 '매진'을 뜻하는가. 코드 우선, 없으면 문구."""
    if msg_cd in SOLD_OUT_CODES:
        return True
    return any(hint in msg_txt for hint in SOLD_OUT_HINTS)


class KorailBlocked(KorailApiError):
    """`MACRO ERROR` — 안티봇에 막혔다.

    DynaPath 우회가 깨졌다는 신호다. 고칠 곳은 `korail_dynapath.py` 하나다 (D-22).
    재시도해도 소용없으므로 재시도 대상이 아니다.
    """


# ── 순수 파서 (네트워크 없음, 단위 테스트 대상) ───────────────────────────
def parse_delay_minutes(raw: str | None) -> int | None:
    """`h_expct_dlay_hr` → 지연 분. 정보 없음/파싱 실패는 None.

    **6자리 포맷이다** (Phase 0 실측 `'000000'`). korail2의 주석은 `hhmm`이라고
    적어두었지만 4자리가 아니다 — 그 주석을 믿으면 조용히 틀린다.
    6자리를 `HHMMSS`로 읽는다 (`'001500'` → 15분).

    지연 정보는 있으면 좋은 것이고 없어도 시스템은 지연 0으로 계속 동작한다 —
    그래서 예외를 던지지 않고 None으로 떨어뜨린다 (우아한 성능 저하, D-12).
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or not text.isdigit():
        return None
    if len(text) != 6:
        # 포맷이 바뀌었다는 뜻. 추측해서 틀린 지연을 쓰느니 모른다고 하는 편이 낫다.
        return None
    hours, minutes, seconds = int(text[0:2]), int(text[2:4]), int(text[4:6])
    return hours * 60 + minutes + (1 if seconds >= 30 else 0)


def parse_seat_states(car_no: int, seat_infos: list[dict[str, Any]]) -> list[SeatState]:
    """`ResidualSeatsResearch` 좌석 목록 → `SeatState`.

    Phase 0 항목 6 실측: 응답은 **전체 좌석 + 상태**다 (구매 가능분만이 아니라).
    따라서 `h_sale_psb_flg`가 곧 판매 여부이고 병합은 단순 조인이다.
    `'0A'`는 좌석이 아닌 자리표시자라 제외한다.
    """
    states: list[SeatState] = []
    for info in seat_infos:
        seat_no = str(info.get("h_con_seat_no") or "").strip()
        if not seat_no or seat_no == SENTINEL_SEAT:
            continue
        # 판매 가능(Y) == 비어 있음. sold는 그 반대다.
        states.append(
            SeatState(car=car_no, seat_no=seat_no, sold=info.get("h_sale_psb_flg") != "Y")
        )
    return states


def _dt(date_str: str | None, time_str: str | None) -> datetime | None:
    """`yyyyMMdd` + `hhmmss` → KST aware datetime."""
    if not date_str or not time_str:
        return None
    text = f"{date_str}{str(time_str).ljust(6, '0')[:6]}"
    try:
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except ValueError:
        return None


def parse_train_summary(raw: dict[str, Any], d: _date) -> TrainSummary | None:
    """`ScheduleView`의 `trn_info` 1건 → `TrainSummary`. 시각이 없으면 None."""
    dep = _dt(raw.get("h_dpt_dt"), raw.get("h_dpt_tm"))
    arr = _dt(raw.get("h_arv_dt"), raw.get("h_arv_tm"))
    if dep is None or arr is None:
        return None
    return TrainSummary(
        train_no=str(raw.get("h_trn_no") or "").lstrip("0"),
        train_name=str(raw.get("h_trn_clsf_nm") or "").strip(),
        date=d,
        dep_station=str(raw.get("h_dpt_rs_stn_nm") or "").strip(),
        arr_station=str(raw.get("h_arv_rs_stn_nm") or "").strip(),
        dep_time=dep,
        arr_time=arr,
    )


def same_train_no(a: str | None, b: str | None) -> bool:
    """`'01472'`와 `'1472'`는 같은 열차다. 선행 0 때문에 조용히 못 찾는 일을 막는다."""
    return str(a or "").lstrip("0") == str(b or "").lstrip("0")


def general_cars(car_infos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """일반실 호차만. 특실(`h_psrm_cl_cd != '1'`)은 자유석 통근 대상이 아니다."""
    return [c for c in car_infos if str(c.get("h_psrm_cl_cd")) == GENERAL_CLASS]


# ── 클라이언트 (동기) ─────────────────────────────────────────────────────
class KorailClient:
    """로그인 세션 1개를 감싼 저수준 클라이언트.

    스레드 안전: `asyncio.to_thread`로 여러 스레드에서 동시에 불릴 수 있으므로
    로그인 구간을 락으로 감싼다. 조회 자체는 `requests.Session`이 스레드 세이프하다.
    """

    def __init__(self, cred: KorailCred) -> None:
        self._cred = cred
        self._lock = threading.Lock()
        self._korail: Any = None
        self._session: DynaPathSession | None = None

    # -- 세션 --------------------------------------------------------------
    def _ensure_login(self) -> DynaPathSession:
        """이미 로그인돼 있으면 그대로 쓴다. **만료 시에만** 재로그인 (D-22)."""
        with self._lock:
            if self._session is not None and getattr(self._korail, "logined", False):
                return self._session
            return self._login_locked()

    def _login_locked(self) -> DynaPathSession:
        from korail2 import Korail  # noqa: PLC0415 — korail2 경로에서만 import

        korail = Korail(self._cred.korail_id, self._cred.korail_pw, auto_login=False)
        session = apply_bypass(korail)  # DynaPath 우회 적용 (D-22)
        if not korail.login():
            raise KorailApiError("LOGIN_FAILED", "코레일 로그인에 실패했습니다")
        self._korail, self._session = korail, session
        return session

    def _relogin(self) -> DynaPathSession:
        with self._lock:
            return self._login_locked()

    @property
    def _key(self) -> str:
        return getattr(self._korail, "_key", "korail1234567890")

    # -- 원시 호출 ---------------------------------------------------------
    def _base(self) -> dict[str, Any]:
        from app.adapters.korail_dynapath import APP_VERSION  # noqa: PLC0415

        return {"Device": DEVICE, "Version": APP_VERSION, "Key": self._key}

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST 1회 + **세션 만료 시에만** 재로그인 후 1회 재시도.

        네트워크 장애 재시도(30초×3)는 여기가 아니라 `seatmap_fetcher`의
        `RetryPolicy`가 담당한다 — 계층을 겹치면 재시도가 곱해진다.
        """
        session = self._ensure_login()
        try:
            return self._post_once(session, url, payload)
        except KorailSessionExpired:
            session = self._relogin()
            return self._post_once(session, url, payload)

    def _post_once(
        self, session: DynaPathSession, url: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        response = session.post(url, data=self._base() | payload, timeout=20)
        response.raise_for_status()
        body = response.json()

        if str(body.get("strResult")) != "FAIL":
            return body

        msg_cd = str(body.get("h_msg_cd") or "")
        msg_txt = str(body.get("h_msg_txt") or "")
        if msg_cd in NEED_LOGIN_CODES:
            raise KorailSessionExpired(msg_cd, msg_txt)
        if "MACRO" in msg_cd.upper() or "MACRO" in msg_txt.upper():
            raise KorailBlocked(msg_cd, msg_txt)
        # 매진은 로그인·차단 판정 뒤에 본다 — 앞의 둘이 더 근본적인 상태다
        if looks_sold_out(msg_cd, msg_txt):
            raise KorailSoldOut(msg_cd, msg_txt)
        raise KorailApiError(msg_cd, msg_txt)

    # -- 조회 3종 ----------------------------------------------------------
    def schedule_view(
        self, d: _date, frm: str, to: str, at: datetime | None = None
    ) -> list[dict[str, Any]]:
        """`frm → to` 열차 목록 (원시 `trn_info` 리스트).

        `at`은 출발 시각 **하한**이다 (D-25). 코레일도 하한 시각 검색이라 그대로 맞는다.
        결과 없음은 예외가 아니라 빈 리스트다.
        """
        payload = {
            "radJobId": "1",  # 직통
            "selGoTrain": "109",  # 전체 열차종
            "txtGdNo": "",
            "txtGoAbrdDt": d.strftime("%Y%m%d"),
            "txtGoEnd": to,
            "txtGoHour": (at or datetime.combine(d, datetime.min.time())).strftime("%H%M%S"),
            "txtGoStart": frm,
            "txtMenuId": "11",
            "txtPsgFlg_1": "1",  # 어른 1명
            "txtPsgFlg_2": "0",
            "txtPsgFlg_3": "0",
            "txtPsgFlg_4": "0",
            "txtPsgFlg_5": "0",
            "txtSeatAttCd_2": "000",
            "txtSeatAttCd_3": "000",
            "txtSeatAttCd_4": "015",
            "txtTrnGpCd": "109",
            "adjStnScdlOfrFlg": "N",
            "ebizCrossCheck": "N",
            "rtYn": "N",
            "srtCheckYn": "N",
        }
        try:
            body = self._post(URL_SCHEDULE, payload)
        except KorailSoldOut:
            # 매진도 '해당 없음'과 같다 — 이 구간에 팔 열차가 없다는 답이다 (D-36).
            # 호출부(find_train)가 None을 받고 전 좌석 판매로 처리한다.
            return []
        except KorailApiError as exc:
            if exc.msg_cd in NO_RESULT_CODES:
                return []
            raise
        return (body.get("trn_infos") or {}).get("trn_info") or []

    def find_train(
        self, d: _date, frm: str, to: str, train_no: str
    ) -> dict[str, Any] | None:
        """구간 + 열차번호로 원시 열차 레코드를 찾는다.

        좌석맵 페이로드에는 이 레코드의 역코드·**운행 순번**이 필요하다.
        구간마다 달라지므로 구간마다 한 번씩 조회해야 한다.
        """
        for raw in self.schedule_view(d, frm, to):
            if same_train_no(raw.get("h_trn_no"), train_no):
                return raw
        return None

    def _research_payload(self, train: dict[str, Any]) -> dict[str, Any]:
        """호차 목록·좌석맵 공통 페이로드 (letskorail 구현 기준, Phase 0 실측)."""
        return {
            "txtArvRsStnCd": train.get("h_arv_rs_stn_cd"),
            "txtArvStnRunOrdr": train.get("h_arv_stn_run_ordr"),
            "txtDptDt": train.get("h_dpt_dt"),
            "txtDptRsStnCd": train.get("h_dpt_rs_stn_cd"),
            "txtDptStnRunOrdr": train.get("h_dpt_stn_run_ordr"),
            "txtGdNo": "",
            "txtMenuId": "11",
            "txtPsrmClCd": GENERAL_CLASS,
            "txtRunDt": train.get("h_run_dt"),
            "txtSeatAttCd": "015",
            "txtTotPsgCnt": "1",
            "txtTrnClsfCd": train.get("h_trn_clsf_cd"),
            "txtTrnGpCd": train.get("h_trn_gp_cd"),
            "txtTrnNo": train.get("h_trn_no"),
        }

    def car_list(self, train: dict[str, Any]) -> list[dict[str, Any]]:
        """호차별 잔여석 (`srcar_info`). 좌석맵을 파기 전에 **어느 호차를 팔 만한지**
        가려내는 데 쓴다 — 잔여 0인 호차는 좌석맵을 받아봐야 전부 판매됨이다."""
        body = self._post(URL_CARS, self._research_payload(train))
        return (body.get("srcar_infos") or {}).get("srcar_info") or []

    def seat_states(self, train: dict[str, Any], car_no: int) -> list[SeatState]:
        """★ 좌석맵. 한 호차의 좌석별 판매 여부."""
        payload = self._research_payload(train) | {"txtSrcarNo": str(car_no)}
        body = self._post(URL_SEATS, payload)
        seat_infos = (body.get("seat_infos") or {}).get("seat_info") or []
        return parse_seat_states(car_no, seat_infos)


# ── 프로세스 내 세션 캐시 ─────────────────────────────────────────────────
# 매 조회마다 로그인하면 호출 예절 위반이자 세션 충돌 위험이다 (D-14 문제 1).
# 자격증명이 바뀌면 새 클라이언트를 만든다.
_clients: dict[tuple[str, str], KorailClient] = {}
_clients_lock = threading.Lock()


def get_client(cred: KorailCred) -> KorailClient:
    key = (cred.korail_id, cred.korail_pw)
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            client = KorailClient(cred)
            _clients[key] = client
        return client


def reset_clients() -> None:
    """테스트용. 프로세스 캐시를 비운다."""
    with _clients_lock:
        _clients.clear()
