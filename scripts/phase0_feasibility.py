#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "korail2>=0.4.0",
# ]
# ///
"""ITX 자유석 좌석 매트릭스 — Phase 0 실현 가능성 검증 (일회성 스크립트).

PLAN.md 0절의 6개 항목을 우선순위(3 → 1 → 2 → 5 → 6 → 4) 순으로 확인한다.
본 구현(app/)과 무관하며, 여기서 나온 결과만 PLAN.md 0절 표에 기록한다.

사용법:
    uv run scripts/phase0_feasibility.py --step 0      # 라이브러리 소스 감사 (네트워크 없음)
    uv run scripts/phase0_feasibility.py --step 3 --train 1071 --from 수원 --to 영등포
    uv run scripts/phase0_feasibility.py --step 1 --train 1071 --from 수원 --to 영등포
    uv run scripts/phase0_feasibility.py --step 2 --train 1071 --from 수원 --to 영등포
    uv run scripts/phase0_feasibility.py --step 5 --train 1071 --from 수원 --to 영등포
    uv run scripts/phase0_feasibility.py --step 6 --train 1071 --from 수원 --via 영등포 --to 서울
    uv run scripts/phase0_feasibility.py --step 4      # 저장된 JSON에서 지연 필드 grep (네트워크 없음)

호출 예절 (엄수):
    - step당 필요한 최소 횟수만 호출한다. 자동 재시도·루프 없음.
    - 모든 HTTP 호출 사이 최소 --gap 초(기본 1.2초) 간격.
    - 한 번 실행에서 --max-calls(기본 12) 를 넘으면 즉시 중단한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
RESULTS_DIR = REPO_ROOT / "scripts" / "phase0_results"

# ── 코레일 모바일 비공식 엔드포인트 ─────────────────────────────────
# 출처: korail2(carpedm20) / letskorail(bsangmin) 소스. 좌석맵에 해당하는 것은
# research.* 두 개뿐이며 korail2에는 이 둘이 아예 없다 (→ step 0 참조).
HOST = "https://smart.letskorail.com:443"
MOBILE = f"{HOST}/classes/com.korail.mobile"

URL_SCHEDULE = f"{MOBILE}.seatMovie.ScheduleView"  # 열차 조회
URL_CARS_INFO = f"{MOBILE}.research.TrainResearch"  # 호차별 잔여석 수
URL_CAR_DETAIL = f"{MOBILE}.research.ResidualSeatsResearch.do"  # ★ 좌석별 판매가능 여부
URL_STATION_DATA = f"{MOBILE}.common.stationdata"  # 역 코드 테이블
URL_STATION_INFO = f"{MOBILE}.common.stationinfo"  # 역 부가정보

USER_AGENT = (
    "Dalvik/2.1.0 (Linux; U; Android 11; Pixel 4a (5G) Build/RQ1A.210105.003)"
)
DEVICE = "AD"
DEFAULT_API_VERSION = "231231001"
DEFAULT_KEY = "korail1234567890"

# ── 마스킹 ────────────────────────────────────────────────────────
# 저장 JSON에 개인정보/자격증명이 남지 않게 키 이름 기준으로 지운다.
MASK_KEY_PATTERNS = [
    "pwd", "password", "passwd",
    "mbcrdno", "membno", "memberno", "custnm", "emailadr", "cpno",
    "buy_ps_nm", "hidden", "idx", "key", "uuid",
    "pnr_no", "tk_no", "tknoe", "ticket_no",
    "sale_sqno", "wct_no", "ret_pwd", "crd_no", "card",
    "strdigit", "jrny_no",
]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\b01\d[- ]?\d{3,4}[- ]?\d{4}\b")


def mask_value(v: Any) -> Any:
    if isinstance(v, str):
        return f"***MASKED(len={len(v)})***"
    return "***MASKED***"


def mask(obj: Any) -> Any:
    """재귀적으로 민감 키/패턴을 마스킹한 사본을 반환."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(p in lk for p in MASK_KEY_PATTERNS):
                out[k] = mask_value(v)
            else:
                out[k] = mask(v)
        return out
    if isinstance(obj, list):
        return [mask(x) for x in obj]
    if isinstance(obj, str):
        s = EMAIL_RE.sub("***EMAIL***", obj)
        s = PHONE_RE.sub("***PHONE***", s)
        return s
    return obj


# ── 출력 헬퍼 ─────────────────────────────────────────────────────
def hr(title: str = "") -> None:
    if title:
        print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
    else:
        print("-" * 72)


def say(msg: str) -> None:
    print(msg)


def ask_yn(question: str) -> bool:
    while True:
        a = input(f"{question} [y/n] ").strip().lower()
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False


def now_kst() -> datetime:
    return datetime.now(KST)


# ── .env 로더 (의존성 추가 없이) ───────────────────────────────────
def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        env[k.strip()] = v
    return env


# ── 호출 예산 (재시도 없음, 간격 강제) ──────────────────────────────
class CallBudget:
    def __init__(self, limit: int, gap: float) -> None:
        self.limit = limit
        self.gap = gap
        self.count = 0
        self._last = 0.0
        self.log: list[dict[str, Any]] = []

    def before(self, label: str) -> None:
        if self.count >= self.limit:
            raise SystemExit(
                f"[중단] 호출 상한 {self.limit}회 도달 — '{label}' 호출을 하지 않고 멈춘다. "
                f"(--max-calls 로 조정 가능하나, 코레일 호출 예절상 늘리기 전에 한 번 더 생각할 것)"
            )
        wait = self.gap - (time.monotonic() - self._last)
        if self._last and wait > 0:
            time.sleep(wait)
        self.count += 1
        self._last = time.monotonic()


BUDGET: CallBudget  # main에서 초기화


def api_call(
    session: requests.Session,
    method: str,
    url: str,
    payload: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    """단발 호출. 재시도하지 않는다. 결과를 BUDGET.log에 남기고 dict를 반환."""
    BUDGET.before(label)
    started = now_kst()
    say(f"  → [{BUDGET.count}] {label}: {method} {url}")

    record: dict[str, Any] = {
        "label": label,
        "method": method,
        "url": url,
        "request": mask(payload),
        "at_kst": started.isoformat(),
    }
    try:
        if method == "GET":
            r = session.get(url, params=payload, timeout=20)
        else:
            r = session.post(url, data=payload, timeout=20)
        record["http_status"] = r.status_code
        try:
            body = r.json()
        except ValueError:
            body = None
            record["raw_text_head"] = r.text[:2000]
        record["response"] = mask(body) if body is not None else None
    except Exception as e:  # 네트워크 오류도 관찰 대상
        record["error"] = f"{type(e).__name__}: {e}"
        BUDGET.log.append(record)
        say(f"     ✗ 예외: {record['error']}")
        return record

    if isinstance(body := record.get("response"), dict):
        say(
            f"     ← strResult={body.get('strResult')} "
            f"h_msg_cd={body.get('h_msg_cd')} h_msg_txt={str(body.get('h_msg_txt', ''))[:60]!r}"
        )
    BUDGET.log.append(record)
    return record


def body_of(record: dict[str, Any]) -> dict[str, Any] | None:
    b = record.get("response")
    return b if isinstance(b, dict) else None


def is_fail(record: dict[str, Any]) -> bool:
    b = body_of(record)
    return b is None or b.get("strResult") == "FAIL"


def msg_code(record: dict[str, Any]) -> str:
    b = body_of(record)
    return str(b.get("h_msg_cd", "")) if b else ""


# ── 결과 저장 ─────────────────────────────────────────────────────
def save_result(step: str, name: str, data: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = now_kst().strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"step{step}_{name}_{ts}.json"
    envelope = {
        "step": step,
        "name": name,
        "saved_at_kst": now_kst().isoformat(),
        "calls": BUDGET.log,
        **data,
    }
    path.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    say(f"\n[저장] {path.relative_to(REPO_ROOT)}  (호출 {BUDGET.count}회)")
    return path


# ── 세션/로그인 ───────────────────────────────────────────────────
def anon_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def login_korail(env: dict[str, str], account: str) -> tuple[Any, requests.Session, str]:
    """korail2로 로그인. (korail 객체, 세션, 로그인에 쓴 Key) 반환."""
    from korail2 import Korail  # noqa: PLC0415  (uv run 스크립트, 지연 import)

    if account == "sub":
        kid, kpw = env.get("KORAIL_SUB_ID"), env.get("KORAIL_SUB_PW")
        if not kid or not kpw:
            raise SystemExit(
                "[중단] .env에 KORAIL_SUB_ID / KORAIL_SUB_PW 가 없다. "
                "부계정 검증(step 2)은 부계정 자격증명이 있어야 한다."
            )
    else:
        kid, kpw = env.get("KORAIL_ID"), env.get("KORAIL_PW")
        if not kid or not kpw:
            raise SystemExit("[중단] .env에 KORAIL_ID / KORAIL_PW 가 없다.")

    BUDGET.before("login")  # 로그인도 호출 예산에 포함 (실제로는 code.do + Login 2회)
    say(f"  → [{BUDGET.count}] login: 계정={account} (id는 출력하지 않음)")
    k = Korail(kid, kpw, auto_login=False)
    ok = k.login()
    if not ok:
        raise SystemExit("[중단] 로그인 실패. 자격증명/차단 여부 확인 필요.")
    say(f"     ← 로그인 성공 (회원번호/이름/이메일은 마스킹, 저장하지 않음)")
    BUDGET.log.append(
        {
            "label": "login",
            "method": "POST",
            "url": "com.korail.mobile.login.Login",
            "request": {"account": account, "id": "***MASKED***", "pw": "***MASKED***"},
            "at_kst": now_kst().isoformat(),
            "response": {"logined": True, "profile": "***MASKED***"},
        }
    )
    return k, k._session, getattr(k, "_key", DEFAULT_KEY)


# ── 코레일 조회 3종 ───────────────────────────────────────────────
def req_base(api_version: str, key: str) -> dict[str, Any]:
    return {"Device": DEVICE, "Version": api_version, "Key": key}


def schedule_view(
    session: requests.Session,
    dep: str,
    arr: str,
    date: str,
    time_: str,
    api_version: str,
    key: str,
    label: str = "ScheduleView(열차조회)",
) -> dict[str, Any]:
    payload = req_base(api_version, key) | {
        "radJobId": "1",  # 1: 직통
        "selGoTrain": "109",  # 전체
        "txtGdNo": "",
        "txtGoAbrdDt": date,
        "txtGoEnd": arr,
        "txtGoHour": time_,
        "txtGoStart": dep,
        "txtMenuId": "11",
        "txtPsgFlg_1": "1",  # 어른 1
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
    return api_call(session, "POST", URL_SCHEDULE, payload, f"{label} {dep}→{arr}")


def pick_train(record: dict[str, Any], train_no: str) -> dict[str, Any] | None:
    b = body_of(record)
    if not b:
        return None
    infos = (b.get("trn_infos") or {}).get("trn_info") or []
    for t in infos:
        if str(t.get("h_trn_no", "")).lstrip("0") == str(train_no).lstrip("0"):
            return t
    return None


def train_research_payload(
    train: dict[str, Any], api_version: str, key: str, psrm_cl_cd: str = "1"
) -> dict[str, Any]:
    """호차 목록/좌석맵 공통 페이로드 (letskorail 구현 기준)."""
    return req_base(api_version, key) | {
        "txtArvRsStnCd": train.get("h_arv_rs_stn_cd"),
        "txtArvStnRunOrdr": train.get("h_arv_stn_run_ordr"),
        "txtDptDt": train.get("h_dpt_dt"),
        "txtDptRsStnCd": train.get("h_dpt_rs_stn_cd"),
        "txtDptStnRunOrdr": train.get("h_dpt_stn_run_ordr"),
        "txtGdNo": "",
        "txtMenuId": "11",
        "txtPsrmClCd": psrm_cl_cd,  # 1: 일반실
        "txtRunDt": train.get("h_run_dt"),
        "txtSeatAttCd": "015",
        "txtTotPsgCnt": "1",
        "txtTrnClsfCd": train.get("h_trn_clsf_cd"),
        "txtTrnGpCd": train.get("h_trn_gp_cd"),
        "txtTrnNo": train.get("h_trn_no"),
    }


def cars_info(
    session: requests.Session, train: dict[str, Any], api_version: str, key: str
) -> dict[str, Any]:
    payload = train_research_payload(train, api_version, key)
    return api_call(session, "POST", URL_CARS_INFO, payload, "TrainResearch(호차 잔여석)")


def residual_seats(
    session: requests.Session,
    train: dict[str, Any],
    car_no: str,
    api_version: str,
    key: str,
) -> dict[str, Any]:
    payload = train_research_payload(train, api_version, key) | {"txtSrcarNo": car_no}
    return api_call(
        session,
        "POST",
        URL_CAR_DETAIL,
        payload,
        f"ResidualSeatsResearch(★좌석맵, {car_no}호차)",
    )


def summarize_cars(record: dict[str, Any]) -> list[dict[str, Any]]:
    b = body_of(record) or {}
    cars = (b.get("srcar_infos") or {}).get("srcar_info") or []
    for c in cars:
        say(
            f"     · {c.get('h_srcar_no')}호차 {c.get('h_psrm_cl_nm')} "
            f"좌석 {c.get('h_seat_cnt')} / 잔여 {c.get('h_rest_seat_cnt')}"
        )
    return cars


def summarize_seatmap(record: dict[str, Any]) -> dict[str, Any]:
    b = body_of(record) or {}
    seats = (b.get("seat_infos") or {}).get("seat_info") or []
    keys = [s.get("h_con_seat_no") for s in seats if s.get("h_con_seat_no") != "0A"]
    sale_y = [s for s in seats if s.get("h_sale_psb_flg") == "Y"]
    sale_n = [s for s in seats if s.get("h_sale_psb_flg") == "N"]
    info = {
        "max_seat_no": b.get("h_max_seat_no"),
        "psb_seat_cnt": b.get("h_psb_seat_cnt"),
        "returned_seat_count": len(keys),
        "sale_psb_Y": len(sale_y),
        "sale_psb_N": len(sale_n),
        "seat_keys": keys,
        "seat_info_sample": mask(seats[:3]),
    }
    say(
        f"     · 좌석 응답 {len(keys)}건 (판매가능 Y={len(sale_y)} / N={len(sale_n)}), "
        f"h_max_seat_no={b.get('h_max_seat_no')} h_psb_seat_cnt={b.get('h_psb_seat_cnt')}"
    )
    say(f"     · 좌석키 앞부분: {keys[:12]}")
    return info


def resolve_segment(
    session: requests.Session,
    args: argparse.Namespace,
    dep: str,
    arr: str,
    key: str,
) -> dict[str, Any]:
    rec = schedule_view(session, dep, arr, args.date, args.time, args.api_version, key)
    if is_fail(rec):
        raise SystemExit(
            f"[중단] 열차 조회 실패 ({dep}→{arr}, h_msg_cd={msg_code(rec)}). "
            "로그인 필요/조회 조건 문제일 수 있다. 자동 재시도는 하지 않는다."
        )
    train = pick_train(rec, args.train)
    if not train:
        b = body_of(rec) or {}
        nos = [
            f"{t.get('h_trn_clsf_nm')}-{t.get('h_trn_no')} "
            f"{t.get('h_dpt_tm', '')[:4]}"
            for t in (b.get("trn_infos") or {}).get("trn_info", [])
        ]
        raise SystemExit(
            f"[중단] {dep}→{arr} {args.date} {args.time} 조회 결과에 열차 {args.train} 없음.\n"
            f"       조회된 열차: {nos}\n"
            "       --time 을 출발시각 이전으로 조정해서 다시 시도할 것."
        )
    say(
        f"     · 열차 {train.get('h_trn_clsf_nm')}-{train.get('h_trn_no')} "
        f"{train.get('h_dpt_rs_stn_nm')}({train.get('h_dpt_tm', '')[:4]}) → "
        f"{train.get('h_arv_rs_stn_nm')}({train.get('h_arv_tm', '')[:4]}) "
        f"운행순번 {train.get('h_dpt_stn_run_ordr')}→{train.get('h_arv_stn_run_ordr')} "
        f"지연필드 h_expct_dlay_hr={train.get('h_expct_dlay_hr')!r}"
    )
    return train


def first_general_car(cars: list[dict[str, Any]], want: str | None) -> str:
    if want:
        return f"{int(want):04d}"
    for c in cars:
        if c.get("h_psrm_cl_cd") == "1":
            return str(c.get("h_srcar_no"))
    if cars:
        return str(cars[0].get("h_srcar_no"))
    raise SystemExit("[중단] 호차 목록이 비어 있어 좌석맵을 조회할 수 없다.")


# ══════════════════════════════════════════════════════════════════
# step 0 — 라이브러리 소스 감사 (네트워크 호출 없음)
# ══════════════════════════════════════════════════════════════════
def step0() -> None:
    hr("step 0 — 라이브러리 소스 감사: '좌석맵에 해당하는 함수'가 무엇인가")
    import inspect

    import korail2

    # Korail 클래스가 정의된 실제 모듈을 봐야 한다 (__init__.py는 re-export만 한다)
    impl = sys.modules[korail2.Korail.__module__]
    src = inspect.getsource(impl)
    public = [m for m in dir(korail2.Korail) if not m.startswith("_")]
    say(f"korail2 구현 파일: {inspect.getsourcefile(impl)}")
    say(f"korail2.Korail 공개 메서드: {public}")

    probes = {
        "ResidualSeatsResearch (좌석별 잔여 조회)": "ResidualSeats",
        "TrainResearch (호차별 잔여석)": "TrainResearch",
        "seat_infos (좌석맵 배열 파싱)": "seat_infos",
        "tk_seat_info (내 승차권의 좌석 — 좌석맵 아님)": "tk_seat_info",
        "h_sale_psb_flg (좌석 판매가능 플래그)": "h_sale_psb_flg",
        "reserve (예약 = 실제 예약 생성)": "def reserve",
    }
    say("\nkorail2 소스 내 문자열 존재 여부:")
    for name, needle in probes.items():
        say(f"  {'있음' if needle in src else '없음'} — {name}")

    say(
        "\n[관찰]\n"
        "  · korail2가 노출하는 열차 조회는 search_train / search_train_allday 뿐이고,\n"
        "    반환값은 열차 단위 플래그(h_gen_rsv_cd: 00 없음 / 11 예약가능 / 13 매진)다.\n"
        "    좌석 '단위' 정보는 reserve() 흐름 안에서도 나오지 않는다 — 좌석 지정 자체가 없다.\n"
        "  · 좌석맵에 해당하는 엔드포인트는 코레일 모바일 API의\n"
        f"      {URL_CARS_INFO}   (호차별 잔여석 수)\n"
        f"      {URL_CAR_DETAIL}  (좌석별 h_sale_psb_flg = 판매가능 Y/N)\n"
        "    두 개이며, 이를 감싼 라이브러리는 letskorail(bsangmin) 이다.\n"
        "    이름이 research.* 이고 reservation/certification.* 계열과 분리돼 있다는 점이\n"
        "    항목 3(순수 조회) 판정의 1차 신호 — 다만 실측으로 확인해야 한다 (step 3).\n"
        "  · 지연 정보 필드 h_expct_dlay_hr 는 두 라이브러리 모두 ScheduleView 응답에서 읽는다\n"
        "    (항목 4는 별도 호출 없이 step 5/6 응답으로 판정 가능).\n"
        "  · 열차번호 → 전체 정차역 목록을 주는 함수/엔드포인트는 두 라이브러리 어디에도 없다\n"
        "    (항목 5는 이 사실 위에서 대안을 따져야 한다 — step 5).\n"
    )
    save_result("0", "library_audit", {"korail2_public_methods": public})


# ══════════════════════════════════════════════════════════════════
# step 3 — 좌석맵 조회가 순수 조회인가  ★최우선
# ══════════════════════════════════════════════════════════════════
def step3(args: argparse.Namespace, env: dict[str, str]) -> None:
    hr("step 3 — 좌석맵 조회의 순수성 (항목 3, no면 프로젝트 재검토)")
    say(
        "계획: 로그인 → 예약/승차권 목록 스냅샷(전) → 좌석맵 1회 조회 → 정지 →\n"
        "      폰 확인 → 예약/승차권 목록 스냅샷(후) → 자동 비교 + 사용자 확인 결합 판정\n"
    )
    from korail2 import NoResultsError

    korail, session, key = login_korail(env, args.account)

    def snapshot(when: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, fn in (("reservations", korail.reservations), ("tickets", korail.tickets)):
            BUDGET.before(f"{name}({when})")
            say(f"  → [{BUDGET.count}] {name} ({when})")
            try:
                items = fn()
                out[name] = [mask(vars(i)) for i in items]
                say(f"     ← {len(items)}건")
            except NoResultsError:
                out[name] = []
                say("     ← 0건 (NoResultsError)")
            except Exception as e:
                out[name] = {"error": f"{type(e).__name__}: {e}"}
                say(f"     ✗ {type(e).__name__}: {e}")
        return out

    before = snapshot("전")

    say("\n[좌석맵 조회 — 이 실행에서 단 1회만 수행한다]")
    train = resolve_segment(session, args, args.dep, args.arr, key)
    cars_rec = cars_info(session, train, args.api_version, key)
    if is_fail(cars_rec):
        say(f"     ✗ 호차 조회 실패 (h_msg_cd={msg_code(cars_rec)}) — 좌석맵 호출은 하지 않는다.")
        save_result("3", "purity_aborted", {"verdict": "INCONCLUSIVE", "reason": "cars_info failed"})
        return
    cars = summarize_cars(cars_rec)
    car_no = first_general_car(cars, args.car)
    seat_rec = residual_seats(session, train, car_no, args.api_version, key)
    seat_summary = None
    if is_fail(seat_rec):
        say(f"     ✗ 좌석맵 조회 실패 (h_msg_cd={msg_code(seat_rec)})")
    else:
        seat_summary = summarize_seatmap(seat_rec)

    hr()
    say(
        "🛑 여기서 멈춘다. 지금 폰에서 코레일 앱을 열고 다음을 확인할 것:\n"
        "   1) 하단 '승차권 확인' / '예약승차권 조회' 에 새 예약이 생겼는가\n"
        "   2) 장바구니 / 발권대기(결제대기) 목록에 항목이 생겼는가\n"
        "   3) 알림/문자로 예약 관련 메시지가 왔는가\n"
        "   (좌석맵 호출은 방금 1회만 했다. 이후 스크립트는 조회 목록만 다시 읽는다.)\n"
    )
    trace_in_app = ask_yn("폰에서 예약/장바구니/발권대기 흔적이 하나라도 보이는가?")
    note = input("메모(선택, 없으면 엔터): ").strip()

    after = snapshot("후")

    def keyset(snap: dict[str, Any], name: str) -> int:
        v = snap.get(name)
        return len(v) if isinstance(v, list) else -1

    diff = {
        "reservations_before": keyset(before, "reservations"),
        "reservations_after": keyset(after, "reservations"),
        "tickets_before": keyset(before, "tickets"),
        "tickets_after": keyset(after, "tickets"),
    }
    auto_changed = (
        diff["reservations_before"] != diff["reservations_after"]
        or diff["tickets_before"] != diff["tickets_after"]
    )

    if auto_changed or trace_in_app:
        verdict = "NOT_PURE"
        headline = "❌ 항목 3 = NO — 좌석맵 조회가 흔적을 남긴다. PLAN.md 0절대로 프로젝트 재검토."
    elif seat_summary is None:
        verdict = "INCONCLUSIVE"
        headline = "⚠️ 좌석맵 호출 자체가 실패해 순수성 판정 불가."
    else:
        verdict = "PURE"
        headline = "✅ 항목 3 = YES — 자동 비교·앱 확인 모두 흔적 없음. 순수 조회로 판정."

    hr()
    say(headline)
    say(f"  자동 비교: 예약 {diff['reservations_before']}→{diff['reservations_after']}, "
        f"승차권 {diff['tickets_before']}→{diff['tickets_after']}")
    say(f"  앱 확인(사용자): 흔적 {'있음' if trace_in_app else '없음'}")

    save_result(
        "3",
        "purity",
        {
            "verdict": verdict,
            "headline": headline,
            "account": args.account,
            "train": mask(train),
            "cars": mask(cars),
            "seatmap_summary": seat_summary,
            "reservation_diff": diff,
            "snapshot_before": before,
            "snapshot_after": after,
            "user_reported_trace": trace_in_app,
            "user_note": note,
        },
    )


# ══════════════════════════════════════════════════════════════════
# step 1 — 비로그인 조회 가능 여부
# ══════════════════════════════════════════════════════════════════
def step1(args: argparse.Namespace) -> None:
    hr("step 1 — 비로그인으로 좌석맵/열차조회가 되는가 (항목 1)")
    say(
        "소스 레벨 사실: korail2/letskorail 모두 Korail 객체 생성 시 로그인을 강제하지 않는다.\n"
        "세션 강제는 서버가 h_msg_cd=P058(로그인 필요)로 응답할 때 발생한다.\n"
        "→ 로그인 없는 세션으로 ScheduleView → TrainResearch → ResidualSeatsResearch 순서로\n"
        "  각 1회 호출해 '어느 호출부터 세션을 요구하는지'를 관찰한다.\n"
    )
    session = anon_session()
    key = DEFAULT_KEY  # 로그인 전 기본 Key (letskorail 상수)
    stages: dict[str, Any] = {}

    sched = schedule_view(session, args.dep, args.arr, args.date, args.time, args.api_version, key)
    stages["ScheduleView"] = {"ok": not is_fail(sched), "h_msg_cd": msg_code(sched)}
    if is_fail(sched):
        say("     ✗ 열차 조회부터 실패 → 비로그인 불가(또는 요청 형식 문제). 이후 호출 생략.")
        save_result("1", "anonymous", {"verdict": "NO", "stages": stages})
        return

    train = pick_train(sched, args.train)
    if not train:
        say("     ! 지정 열차를 못 찾음 — 비로그인 조회 자체는 성공했다는 사실만 기록하고 중단.")
        save_result("1", "anonymous", {"verdict": "PARTIAL", "stages": stages})
        return
    say(f"     · 비로그인 상태에서 열차 {train.get('h_trn_no')} 조회 성공")

    cars_rec = cars_info(session, train, args.api_version, key)
    stages["TrainResearch"] = {"ok": not is_fail(cars_rec), "h_msg_cd": msg_code(cars_rec)}
    seat_summary = None
    if is_fail(cars_rec):
        say("     ✗ 호차 조회에서 세션 요구 → 좌석맵 호출 생략.")
    else:
        cars = summarize_cars(cars_rec)
        car_no = first_general_car(cars, args.car)
        seat_rec = residual_seats(session, train, car_no, args.api_version, key)
        stages["ResidualSeatsResearch"] = {
            "ok": not is_fail(seat_rec),
            "h_msg_cd": msg_code(seat_rec),
        }
        if not is_fail(seat_rec):
            seat_summary = summarize_seatmap(seat_rec)

    ok_all = all(v.get("ok") for v in stages.values()) and len(stages) == 3
    first_blocked = next((k for k, v in stages.items() if not v.get("ok")), None)
    verdict = "YES" if ok_all else "NO"
    hr()
    if ok_all:
        say("✅ 항목 1 = YES — 비로그인으로 좌석맵까지 조회된다. 자격증명 저장 설계 전부 삭제 대상.")
    else:
        say(f"❌ 항목 1 = NO — '{first_blocked}' 호출부터 세션을 요구한다 "
            f"(h_msg_cd={stages[first_blocked]['h_msg_cd']}).")

    save_result(
        "1",
        "anonymous",
        {
            "verdict": verdict,
            "first_blocked_call": first_blocked,
            "stages": stages,
            "seatmap_summary": seat_summary,
        },
    )


# ══════════════════════════════════════════════════════════════════
# step 2 — 조회 전용 부계정
# ══════════════════════════════════════════════════════════════════
def step2(args: argparse.Namespace, env: dict[str, str]) -> None:
    hr("step 2 — 예매 이력 없는 조회 전용 부계정으로 좌석맵 접근 (항목 2)")
    say(
        "⚠️ 실행 전 확인: 지금 폰의 코레일 앱은 '본계정'으로 로그인돼 있어야 하고,\n"
        "   이 step 이후에도 그 상태가 유지되는지가 세션 충돌 검증의 핵심이다.\n"
    )
    if not ask_yn("지금 폰 코레일 앱이 본계정으로 로그인된 상태인가?"):
        raise SystemExit("[중단] 본계정 로그인 상태에서 다시 실행할 것 (세션 충돌을 관찰해야 한다).")

    korail, session, key = login_korail(env, "sub")
    stages: dict[str, Any] = {}

    train = resolve_segment(session, args, args.dep, args.arr, key)
    stages["ScheduleView"] = {"ok": True}
    cars_rec = cars_info(session, train, args.api_version, key)
    stages["TrainResearch"] = {"ok": not is_fail(cars_rec), "h_msg_cd": msg_code(cars_rec)}
    seat_summary = None
    if not is_fail(cars_rec):
        cars = summarize_cars(cars_rec)
        car_no = first_general_car(cars, args.car)
        seat_rec = residual_seats(session, train, car_no, args.api_version, key)
        stages["ResidualSeatsResearch"] = {
            "ok": not is_fail(seat_rec),
            "h_msg_cd": msg_code(seat_rec),
        }
        if not is_fail(seat_rec):
            seat_summary = summarize_seatmap(seat_rec)

    hr()
    say(
        "🛑 지금 폰의 코레일 앱을 확인할 것:\n"
        "   1) 여전히 본계정으로 로그인돼 있는가 (강제 로그아웃/재로그인 요구가 뜨지 않는가)\n"
        "   2) 정기권/승차권 화면이 그대로 열리는가 (검표 상황을 가정)\n"
    )
    main_ok = ask_yn("본계정 앱이 로그아웃되지 않고 그대로인가?")
    note = input("메모(선택, 없으면 엔터): ").strip()

    seat_ok = bool(seat_summary)
    verdict = "YES" if (seat_ok and main_ok) else ("SESSION_CONFLICT" if seat_ok else "NO")
    if verdict == "YES":
        say("✅ 항목 2 = YES — 부계정으로 좌석맵 조회 가능 + 본계정 세션 무사. 부계정 방식 채택 가능.")
    elif verdict == "SESSION_CONFLICT":
        say("⚠️ 부계정 조회는 되지만 본계정 세션이 흔들렸다 — 계정 분리로도 충돌이 안 풀린다는 뜻.")
    else:
        say("❌ 항목 2 = NO — 부계정으로 좌석맵 접근 불가.")

    save_result(
        "2",
        "sub_account",
        {
            "verdict": verdict,
            "stages": stages,
            "seatmap_summary": seat_summary,
            "main_app_session_intact": main_ok,
            "user_note": note,
        },
    )


# ══════════════════════════════════════════════════════════════════
# step 5 — 열차번호+날짜 → 정차역 목록 + 역별 도착시각
# ══════════════════════════════════════════════════════════════════
def step5(args: argparse.Namespace, env: dict[str, str]) -> None:
    hr("step 5 — 정차역 목록 + 역별 도착시각 파생 가능성 (항목 5, 원칙 1의 전제)")
    key = DEFAULT_KEY
    session = anon_session()
    if args.account != "none":
        try:
            _, session, key = login_korail(env, args.account)
        except SystemExit as e:
            say(f"  (로그인 생략: {e})")
            session = anon_session()

    rec = schedule_view(session, args.dep, args.arr, args.date, args.time, args.api_version, key)
    if is_fail(rec):
        say(f"     ✗ 조회 실패 (h_msg_cd={msg_code(rec)})")
        save_result("5", "stops", {"verdict": "INCONCLUSIVE"})
        return

    b = body_of(rec) or {}
    train = pick_train(rec, args.train)
    say("\n[응답 최상위 키]")
    say(f"  {sorted(b.keys())}")
    if train:
        say("\n[열차 1건의 전체 필드 — get_stops() 설계 근거]")
        for k in sorted(train.keys()):
            say(f"  {k:28s} = {train[k]!r}")

    stop_like = [k for k in (train or {}) if re.search(r"stn|ordr|tm|dt", k)]
    say(
        "\n[관찰]\n"
        f"  · 정차역/순번 관련 필드: {stop_like}\n"
        "  · ScheduleView는 '조회한 dep→arr 한 쌍'만 돌려준다. 전체 정차역 배열은 없다.\n"
        "    다만 h_dpt_stn_run_ordr / h_arv_stn_run_ordr(운행 순번)로 두 역의 상대 위치는 안다.\n"
        "  → 열차번호만으로 전 정차역을 얻으려면 (a) 역 쌍을 훑는 다중 조회(호출 폭증, 예절 위반),\n"
        "    (b) 외부 소스(공공데이터포털 열차 정차역 API 등), (c) 노선 정차 패턴 정적 데이터 중 택1.\n"
    )

    station_db = None
    if args.station_db:
        st = api_call(session, "GET", URL_STATION_DATA, {}, "stationdata(역 코드 테이블)")
        sb = body_of(st) or {}
        stns = (sb.get("stns") or {}).get("stn") or []
        say(f"     · 역 코드 테이블 {len(stns)}건 (샘플: {[s.get('h_stn_nm') for s in stns[:8]]})")
        station_db = {"count": len(stns), "sample": mask(stns[:8])}

    save_result(
        "5",
        "stops",
        {
            "verdict": "PARTIAL",
            "train_fields": mask(train) if train else None,
            "top_level_keys": sorted(b.keys()),
            "stop_related_fields": stop_like,
            "station_db": station_db,
        },
    )


# ══════════════════════════════════════════════════════════════════
# step 6 — 좌석 유니버스: 전체 좌석+상태인가, 구매 가능 좌석만인가
# ══════════════════════════════════════════════════════════════════
def step6(args: argparse.Namespace, env: dict[str, str]) -> None:
    hr("step 6 — 좌석맵 응답이 전체 좌석+상태인가, 구매 가능 좌석만인가 (항목 6 → D-18)")
    if not args.via:
        raise SystemExit("[중단] --via <중간역> 이 필요하다. 예: --from 수원 --via 영등포 --to 서울")

    key = DEFAULT_KEY
    session = anon_session()
    if args.account != "none":
        try:
            _, session, key = login_korail(env, args.account)
        except SystemExit as e:
            say(f"  (로그인 생략: {e})")

    results: dict[str, Any] = {}
    car_used: str | None = args.car and f"{int(args.car):04d}"

    for tag, (dep, arr) in {
        "segA": (args.dep, args.via),
        "segB": (args.via, args.arr),
    }.items():
        say(f"\n[{tag}] {dep} → {arr}")
        train = resolve_segment(session, args, dep, arr, key)
        cars_rec = cars_info(session, train, args.api_version, key)
        if is_fail(cars_rec):
            say(f"     ✗ 호차 조회 실패 (h_msg_cd={msg_code(cars_rec)})")
            results[tag] = {"error": msg_code(cars_rec)}
            continue
        cars = summarize_cars(cars_rec)
        if car_used is None:
            car_used = first_general_car(cars, None)
        seat_rec = residual_seats(session, train, car_used, args.api_version, key)
        if is_fail(seat_rec):
            say(f"     ✗ 좌석맵 실패 (h_msg_cd={msg_code(seat_rec)})")
            results[tag] = {"error": msg_code(seat_rec)}
            continue
        results[tag] = summarize_seatmap(seat_rec)

    hr()
    a, b = results.get("segA"), results.get("segB")
    verdict = "INCONCLUSIVE"
    if a and b and "seat_keys" in a and "seat_keys" in b:
        ka, kb = set(a["seat_keys"]), set(b["seat_keys"])
        only_a, only_b = sorted(ka - kb), sorted(kb - ka)
        same_size_as_max = str(len(ka)) == str(a.get("max_seat_no")) or a["sale_psb_N"] > 0
        say(f"  segA 좌석 {len(ka)}건 (Y={a['sale_psb_Y']}/N={a['sale_psb_N']})")
        say(f"  segB 좌석 {len(kb)}건 (Y={b['sale_psb_Y']}/N={b['sale_psb_N']})")
        say(f"  segA에만 있는 좌석: {only_a[:20]}{' …' if len(only_a) > 20 else ''}")
        say(f"  segB에만 있는 좌석: {only_b[:20]}{' …' if len(only_b) > 20 else ''}")
        if not only_a and not only_b and (a["sale_psb_N"] > 0 or b["sale_psb_N"] > 0):
            verdict = "FULL_UNIVERSE"
            say("✅ 항목 6 = 전체 좌석+상태 — 두 구간의 좌석 집합이 동일하고 N(판매됨) 상태가 함께 온다.")
            say("   → 병합은 단순 조인. PLAN.md 5절 '부재 추론 규칙'은 불필요(삭제 후보).")
        elif a["sale_psb_N"] == 0 and b["sale_psb_N"] == 0:
            verdict = "AVAILABLE_ONLY"
            say("⚠️ 항목 6 = 구매 가능 좌석만 — 모든 응답이 Y뿐이고 좌석 집합이 구간마다 다르다.")
            say("   → 5절 '좌석 유니버스 = 전 구간 합집합' 부재 추론 규칙을 적용해야 한다.")
        else:
            verdict = "MIXED"
            say("❓ 판정 애매 — 저장된 원시 응답의 h_sale_psb_flg 분포를 직접 확인할 것.")
        results["comparison"] = {
            "only_in_segA": only_a,
            "only_in_segB": only_b,
            "same_seat_set": not only_a and not only_b,
            "max_seat_matches_count": same_size_as_max,
        }

    save_result("6", "seat_universe", {"verdict": verdict, "car_no": car_used, **results})


# ══════════════════════════════════════════════════════════════════
# step 4 — 지연 정보 필드 유무 (저장된 JSON grep, 네트워크 없음)
# ══════════════════════════════════════════════════════════════════
def step4() -> None:
    hr("step 4 — 응답 내 지연 정보 필드 (항목 4, 추가 호출 없음)")
    if not RESULTS_DIR.exists():
        raise SystemExit("[중단] scripts/phase0_results/ 가 없다. step 5 또는 6을 먼저 실행할 것.")

    pat = re.compile(r"dlay|delay|dly|expct|late", re.IGNORECASE)
    hits: list[dict[str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}"
                if pat.search(str(k)):
                    hits.append({"path": p, "value": v})
                walk(v, p)
        elif isinstance(node, list):
            for i, v in enumerate(node[:50]):
                walk(v, f"{path}[{i}]")

    files = sorted(RESULTS_DIR.glob("*.json"))
    for f in files:
        try:
            walk(json.loads(f.read_text(encoding="utf-8")), f.name)
        except ValueError:
            continue

    uniq: dict[str, set[str]] = {}
    for h in hits:
        field = h["path"].rsplit(".", 1)[-1]
        uniq.setdefault(field, set()).add(repr(h["value"]))

    say(f"검사한 파일 {len(files)}개, 지연 관련 키 {len(uniq)}종")
    for field, vals in sorted(uniq.items()):
        sample = sorted(vals)[:6]
        say(f"  {field:24s} 관측값 {sample}")

    if "h_expct_dlay_hr" in uniq:
        vals = uniq["h_expct_dlay_hr"]
        say(
            "\n✅ 항목 4 = 있음 — ScheduleView 응답에 h_expct_dlay_hr(예상 지연, hhmm)가 온다.\n"
            f"   관측값: {sorted(vals)[:6]}\n"
            "   ('000'/''이면 지연 없음. 실제 지연 발생 시각에 다시 관측해 단위를 확정할 것)\n"
            "   → DelayPort 실구현이 공짜. 외부 지연 API 검증 불필요."
        )
        verdict = "YES"
    else:
        say("\n❌ 항목 4 = 없음 — 저장된 응답에서 지연 필드를 찾지 못했다. ZeroDelay 유지.")
        verdict = "NO"

    save_result("4", "delay_fields", {"verdict": verdict, "fields": {k: sorted(v) for k, v in uniq.items()}})


# ══════════════════════════════════════════════════════════════════
def main() -> None:
    global BUDGET

    p = argparse.ArgumentParser(description="Phase 0 실현 가능성 검증 (일회성)")
    p.add_argument("--step", required=True, choices=["0", "1", "2", "3", "4", "5", "6"])
    p.add_argument("--train", help="열차번호 (예: 1071)")
    p.add_argument("--from", dest="dep", help="탑승역")
    p.add_argument("--to", dest="arr", help="하차역")
    p.add_argument("--via", help="step 6용 중간역 (인접 구간 2개를 만든다)")
    p.add_argument("--date", help="운행일 YYYYMMDD (기본: 오늘 KST)")
    p.add_argument("--time", help="조회 기준시각 HHMMSS (기본: 지금 KST)")
    p.add_argument("--car", help="호차 번호 (기본: 첫 일반실 호차)")
    p.add_argument("--account", default="main", choices=["main", "sub", "none"],
                   help="사용할 계정 (.env). none = 로그인하지 않음")
    p.add_argument("--gap", type=float, default=1.2, help="호출 간 최소 간격(초)")
    p.add_argument("--max-calls", type=int, default=12, help="이번 실행의 호출 상한")
    p.add_argument("--api-version", default=DEFAULT_API_VERSION)
    p.add_argument("--station-db", action="store_true", help="step 5에서 역 코드 테이블도 받는다")
    args = p.parse_args()

    now = now_kst()
    args.date = args.date or now.strftime("%Y%m%d")
    args.time = args.time or now.strftime("%H%M%S")

    BUDGET = CallBudget(limit=args.max_calls, gap=args.gap)
    env = load_env()

    say(f"[Phase 0] step {args.step} — {now.isoformat()} (KST)")
    say(f"          호출 상한 {args.max_calls}회 / 간격 {args.gap}s / 재시도 없음")

    needs_train = args.step in ("1", "2", "3", "5", "6")
    if needs_train and not (args.train and args.dep and args.arr):
        raise SystemExit("[중단] --train / --from / --to 가 필요하다.")

    try:
        match args.step:
            case "0":
                step0()
            case "1":
                step1(args)
            case "2":
                step2(args, env)
            case "3":
                step3(args, env)
            case "4":
                step4()
            case "5":
                step5(args, env)
            case "6":
                step6(args, env)
    except KeyboardInterrupt:
        say("\n[중단] 사용자 인터럽트. 지금까지의 호출 로그는 저장되지 않았다.")
        sys.exit(130)


if __name__ == "__main__":
    main()
