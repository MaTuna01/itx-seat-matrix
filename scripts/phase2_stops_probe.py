"""Phase 2 항목 A 최종 검증 — 하루치 정차역을 실제로 조립해 본다 (일회성).

**대상: 한국철도공사_열차운행정보 (data.go.kr 15125762)**
`https://apis.data.go.kr/B551457/run/v2/travelerTrainRunInfo2`

## 앞선 두 차례 프로브로 확정된 것

- 오퍼레이션: `travelerTrainRunInfo2` / `travelerTrainRunPlan2` / `codes2`
- **파라미터는 `cond[필드::연산자]` 형식이다.** 평범한 `run_ymd=`는 조용히 무시된다
  (1·2차 프로브가 전부 `totalCount=798791`을 받은 이유). 포털 페이지에 박혀 있는
  swagger 정의에서 확인했다.
- **`cond[trn_no::…]` 필터는 없다** — 스펙 수준에서 확정. 열차번호로는 못 거른다.
- 쓸 수 있는 필터: `cond[run_ymd::GTE]`/`[::LTE]`, `cond[stn_cd::EQ]`/`[stn_nm::EQ]`,
  `cond[mrnt_cd::EQ]`/`[mrnt_nm::EQ]`
- 응답 필드: `run_ymd, trn_no, trn_run_sn(운행순번), stn_cd, stn_nm,
  trn_arvl_dt, trn_dptre_dt, stop_se_cd/nm(정차구분), mrnt_cd/nm, uppln_dn_se_cd`

## 이번 프로브가 답할 것 (마지막)

- R1 **날짜 필터가 실제로 먹는가** (totalCount가 798791에서 하루치로 줄어드는가)
- R2 하루치 **볼륨과 페이지 수** — `train_stop` 캐시 적재 비용
- R3 ★ 특정 열차(1472)의 **전체 정차역이 순서·시각과 함께 조립되는가**
      = `get_stops()`가 성립하는지 여부. 여기가 Phase 0 항목 5를 뒤집는 지점이다
- R4 같은 응답에서 **역 마스터(역코드+역명)** 를 함께 뽑을 수 있는가 (항목 G)
- R5 `codes2`의 `cond[type::EQ]`에 어떤 값이 유효한가

실행:
    uv run python scripts/phase2_stops_probe.py

원시 응답은 `scripts/phase2_results/`에 저장한다 (gitignore 대상, 키는 마스킹).
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

BASE = "https://apis.data.go.kr/B551457/run/v2"
OP_INFO = "travelerTrainRunInfo2"
OP_CODES = "codes2"

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "scripts" / "phase2_results"
TIMEOUT = 30

SAMPLE_TRAIN_NO = "1472"  # Phase 0에서 쓴 무궁화호 (천안→수원→영등포)
PAGE_SIZE = 1000
MAX_PAGES = 12  # 폭주 방지. 넘으면 잘렸다고 보고한다


def _from_env(name: str) -> str:
    import os

    if value := os.environ.get(name):
        return value.strip()
    env_file = ROOT / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def load_service_key() -> str:
    if key := _from_env("DATA_GO_KR_SERVICE_KEY"):
        return key
    sys.exit("DATA_GO_KR_SERVICE_KEY 가 .env 에 없다.")


def normalize_key(key: str) -> str:
    """Encoding/Decoding 어느 형태든 정확히 한 번만 인코딩되게 만든다."""
    return urllib.parse.unquote(key)


def mask(text: str, key: str) -> str:
    out, raw = text, normalize_key(key)
    for form in {key, raw, urllib.parse.quote(raw, safe=""), urllib.parse.quote_plus(raw)}:
        if form:
            out = out.replace(form, "***SERVICE_KEY***")
    return out


def call(op: str, params: dict[str, str], key: str) -> tuple[int, str]:
    # cond[...] 대괄호는 quote_via 기본(quote_plus)으로 인코딩돼도 게이트웨이가 받는다
    query = urllib.parse.urlencode(
        {"serviceKey": normalize_key(key), "returnType": "JSON", **params}
    )
    req = urllib.request.Request(f"{BASE}/{op}?{query}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def parse(body: str) -> dict:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def body_of(raw: str) -> dict:
    return ((parse(raw).get("response") or {}).get("body")) or {}


def items_of(raw: str) -> list[dict]:
    node = body_of(raw).get("items") or {}
    if isinstance(node, dict):
        item = node.get("item") or []
        return item if isinstance(item, list) else [item]
    return node if isinstance(node, list) else []


def err_of(raw: str) -> str | None:
    data = parse(raw)
    if hdr := (data.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader"):
        return f"{hdr.get('errMsg')} ({hdr.get('returnReasonCode')})"
    h = (data.get("response") or {}).get("header") or {}
    if h and str(h.get("resultCode")) not in ("0", "00"):
        return f"{h.get('resultMsg')} ({h.get('resultCode')})"
    return None


def step(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def main() -> None:
    key = load_service_key()
    RESULTS.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    target = date.today() + timedelta(days=1)
    day = ymd(target)
    day_filter = {"cond[run_ymd::GTE]": day, "cond[run_ymd::LTE]": day}

    def fetch(label: str, params: dict[str, str]) -> tuple[list[dict], int | None]:
        status, raw = call(OP_INFO, params, key)
        log.append({"label": label, "params": params, "status": status, "body": mask(raw, key)[:8000]})
        if e := err_of(raw):
            print(f"  ✗ {label}: {e}")
            return [], None
        b = body_of(raw)
        return items_of(raw), b.get("totalCount")

    # ── R1. 날짜 필터가 먹는가 ────────────────────────────────────────
    step(f"R1 — cond[run_ymd::GTE/LTE] 가 실제로 먹는가  (대상일 {target})")
    _, total_all = fetch("무필터", {"numOfRows": "1"})
    _, total_day = fetch("날짜 필터", {**day_filter, "numOfRows": "1"})
    print(f"  무필터   totalCount = {total_all}")
    print(f"  날짜필터 totalCount = {total_day}")
    if total_day is None or total_all is None:
        sys.exit("  → 응답 오류. 위 메시지를 확인할 것.")
    if total_day == total_all:
        print("  ✗ 여전히 같다 — 필터가 무시된다. cond 표기를 다시 봐야 한다.")
        sys.exit(1)
    print(f"  ✅ 필터 동작 확인 ({total_all} → {total_day}, {total_all / max(total_day,1):.0f}배 축소)")

    pages = -(-total_day // PAGE_SIZE)
    print(f"\n  R2 — 하루치 {total_day}건 = {PAGE_SIZE}건씩 {pages}페이지")
    if pages > MAX_PAGES:
        print(f"  ⚠ {MAX_PAGES}페이지까지만 받는다 (전체 적재는 별도 스크립트에서)")

    # ── R2/R3. 하루치를 받아 열차별로 묶는다 ──────────────────────────
    step("R3 — ★ 하루치를 열차번호로 묶어 전체 정차역이 조립되는가")
    rows: list[dict] = []
    for page in range(1, min(pages, MAX_PAGES) + 1):
        items, _ = fetch(
            f"page {page}", {**day_filter, "numOfRows": str(PAGE_SIZE), "pageNo": str(page)}
        )
        if not items:
            break
        rows.extend(items)
        print(f"     page {page}: 누적 {len(rows)}건")

    by_train: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_train[str(r.get("trn_no") or "")].append(r)

    print(f"\n  받은 행 {len(rows)}건 / 열차 {len(by_train)}편")
    wrong_day = {str(r.get("run_ymd")) for r in rows} - {day}
    print(f"  응답에 섞인 다른 운행일자: {sorted(wrong_day) or '없음 (필터 정확)'}")

    # 대상 열차 조립
    key_train = next(
        (k for k in by_train if k.lstrip("0") == SAMPLE_TRAIN_NO.lstrip("0")), None
    )
    if key_train is None:
        print(f"\n  ⚠ 열차 {SAMPLE_TRAIN_NO}는 이 페이지 범위에 없다.")
        sample = sorted(by_train, key=lambda k: -len(by_train[k]))[:1]
        key_train = sample[0] if sample else None
        if key_train:
            print(f"     대신 정차역이 가장 많은 열차 {key_train}로 보여준다.")

    if key_train:
        stops = sorted(by_train[key_train], key=lambda r: int(r.get("trn_run_sn") or 0))
        print(f"\n  ── 열차 {key_train} 전체 정차역 ({len(stops)}개) ──")
        for s in stops:
            print(
                f"     {str(s.get('trn_run_sn')):>3}  {str(s.get('stn_nm') or ''):<8}"
                f" {str(s.get('stn_cd') or ''):>8}"
                f"  도착 {str(s.get('trn_arvl_dt'))[:19]:<19}"
                f"  출발 {str(s.get('trn_dptre_dt'))[:19]:<19}"
                f"  {s.get('stop_se_nm')}"
            )
        kinds = sorted({str(r.get("stop_se_nm")) for r in rows})
        print(f"\n  정차구분 값 종류: {kinds}")

    # ── R4. 역 마스터 ─────────────────────────────────────────────────
    step("R4 — 같은 응답에서 역 마스터(역코드+역명)를 뽑을 수 있는가")
    stations = {(str(r.get("stn_cd")), str(r.get("stn_nm"))) for r in rows}
    print(f"  이 표본에서만 역 {len(stations)}개 확보")
    for cd, nm in sorted(stations)[:12]:
        print(f"     {cd:>8}  {nm}")

    # ── R5. codes2 ────────────────────────────────────────────────────
    step("R5 — codes2: cond[type::EQ] 에 유효한 값 찾기")
    for t in ["stn", "station", "역", "STN", "mrnt", "line", "stop_se", "uppln_dn_se"]:
        status, raw = call(OP_CODES, {"cond[type::EQ]": t, "numOfRows": "5"}, key)
        log.append({"label": f"codes2 type={t}", "status": status, "body": mask(raw, key)[:3000]})
        items, total = items_of(raw), body_of(raw).get("totalCount")
        flag = "✅" if items else "  "
        print(f"  {flag} type={t!r:<14} totalCount={total} items={len(items)}")
        for it in items[:3]:
            print(f"        {json.dumps(it, ensure_ascii=False)[:150]}")

    out = RESULTS / "stops_probe.json"
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    step("요약")
    print(f"  R1 날짜 필터: {'동작' if total_day != total_all else '무시됨'}")
    print(f"  R2 하루치: {total_day}건 ({pages}페이지 @ {PAGE_SIZE})")
    print(f"  R3 정차역 조립: {'성공' if key_train else '실패'}")
    print(f"  R4 역 마스터: 표본에서 {len(stations)}개")
    print(f"\n  원시 응답: {out}   총 호출 {len(log)}회")


if __name__ == "__main__":
    main()
