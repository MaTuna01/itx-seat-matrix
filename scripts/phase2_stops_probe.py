"""Phase 2 항목 A 최종 검증 — 실적(과거) + 계획(미래) 조합이 성립하는지 (일회성).

**대상: 한국철도공사_열차운행정보 (data.go.kr 15125762)**

## 앞선 세 차례 프로브로 확정된 것

- 오퍼레이션: `travelerTrainRunInfo2`(운행정보) / `travelerTrainRunPlan2`(운행계획) / `codes2`
- **필터 표기는 `cond[필드::연산자]`**. 평범한 `run_ymd=`는 조용히 무시되고 전체
  데이터셋(798,791건)이 페이지네이션돼 돌아온다 — 에러가 안 나서 더 위험하다.
- **`cond[trn_no::…]` 는 없다.** 열차번호로 못 거른다 (스펙 확정).
- ★ **운행정보는 "실제 운행된" 실적 데이터라 과거만 있다.** 내일(D+1) 조회 = 0건.
  운행계획은 미래 3개월을 덮지만 **시종착역만** 준다 (중간 정차역 없음).

## 그래서 남은 설계 가설

정차역 **순서**는 시각표 사실이라 거의 변하지 않는다. 따라서:
  ① 최근 운행일의 **운행정보**에서 열차별 정차 순서·시각을 받아 `train_stop`에 캐시
  ② 대상일 운행 여부·시종착 시각은 **운행계획**으로 확인
이 조합이 성립하는지가 이 프로브의 질문이다.

- S1 운행정보의 **가장 최신 가용일**은 언제인가 (전일? 2일 전?) + 일자별 건수
- S2 그 날짜에서 열차 1472의 **전체 정차역**이 순서·시각과 함께 조립되는가
- S3 **요일 안정성** — 같은 열차의 정차 순서가 최근 여러 날에 걸쳐 동일한가
      (동일하면 캐시가 안전하다. 다르면 요일별로 따로 캐시해야 한다)
- S4 운행계획이 **대상일(내일)에 그 열차가 운행하는지** 알려주는가
- S5 역 마스터(역코드+역명) 수집량

실행:
    uv run python scripts/phase2_stops_probe.py
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
OP_PLAN = "travelerTrainRunPlan2"

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "scripts" / "phase2_results"
TIMEOUT = 30

SAMPLE_TRAIN_NO = "1472"
PAGE_SIZE = 1000
MAX_PAGES = 15


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
    return urllib.parse.unquote(key)


def mask(text: str, key: str) -> str:
    out, raw = text, normalize_key(key)
    for form in {key, raw, urllib.parse.quote(raw, safe=""), urllib.parse.quote_plus(raw)}:
        if form:
            out = out.replace(form, "***SERVICE_KEY***")
    return out


LOG: list[dict] = []


def call(op: str, params: dict[str, str], key: str, label: str = "") -> str:
    query = urllib.parse.urlencode(
        {"serviceKey": normalize_key(key), "returnType": "JSON", **params}
    )
    req = urllib.request.Request(f"{BASE}/{op}?{query}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        raw = f'{{"_local_error": "{type(e).__name__}: {e}"}}'
    LOG.append({"label": label or op, "op": op, "params": params, "body": mask(raw, key)[:8000]})
    return raw


def parse(raw: str) -> dict:
    try:
        return json.loads(raw)
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


def total_of(raw: str) -> int | None:
    return body_of(raw).get("totalCount")


def day_filter(d: date) -> dict[str, str]:
    s = d.strftime("%Y%m%d")
    return {"cond[run_ymd::GTE]": s, "cond[run_ymd::LTE]": s}


def step(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def stop_list(rows: list[dict], train_no: str) -> list[dict]:
    hit = [r for r in rows if str(r.get("trn_no") or "").lstrip("0") == train_no.lstrip("0")]
    return sorted(hit, key=lambda r: int(r.get("trn_run_sn") or 0))


def main() -> None:
    key = load_service_key()
    RESULTS.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # ── S1. 가장 최신 가용일 찾기 ─────────────────────────────────────
    step("S1 — 운행정보의 최신 가용일 + 일자별 건수 (오늘부터 뒤로 훑는다)")
    available: list[tuple[date, int]] = []
    for back in range(0, 11):
        d = today - timedelta(days=back)
        total = total_of(call(OP_INFO, {**day_filter(d), "numOfRows": "1"}, key, f"count {d}"))
        mark = "✅" if total else "  "
        print(f"  {mark} {d} ({'월화수목금토일'[d.weekday()]})  {total}건")
        if total:
            available.append((d, total))

    if not available:
        sys.exit("\n  ✗ 최근 11일 내 운행정보가 없다. 보유 기간을 다시 확인해야 한다.")

    freshest, fresh_total = available[0]
    print(f"\n  → 최신 가용일 {freshest} ({fresh_total}건)")
    print(f"     오늘 기준 지연 {(today - freshest).days}일")

    # ── S2. 하루치 받아 정차역 조립 ───────────────────────────────────
    step(f"S2 — ★ {freshest} 하루치를 trn_no로 묶어 정차역 조립")
    pages = -(-fresh_total // PAGE_SIZE)
    print(f"  {fresh_total}건 = {PAGE_SIZE}건씩 {pages}페이지 (최대 {MAX_PAGES}페이지까지 받는다)")

    rows: list[dict] = []
    for page in range(1, min(pages, MAX_PAGES) + 1):
        items = items_of(
            call(
                OP_INFO,
                {**day_filter(freshest), "numOfRows": str(PAGE_SIZE), "pageNo": str(page)},
                key,
                f"{freshest} page {page}",
            )
        )
        if not items:
            break
        rows.extend(items)
    print(f"  받은 행 {len(rows)}건")

    by_train: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_train[str(r.get("trn_no") or "")].append(r)
    print(f"  열차 {len(by_train)}편 / 열차당 평균 정차 {len(rows) / max(len(by_train), 1):.1f}개")

    stops = stop_list(rows, SAMPLE_TRAIN_NO)
    if stops:
        print(f"\n  ── 열차 {SAMPLE_TRAIN_NO} 전체 정차역 ({len(stops)}개) ──")
        for s in stops:
            print(
                f"     {str(s.get('trn_run_sn')):>3}  {str(s.get('stn_nm') or ''):<8}"
                f" {str(s.get('stn_cd') or ''):>8}"
                f"  도착 {str(s.get('trn_arvl_dt'))[:19]:<19}"
                f"  출발 {str(s.get('trn_dptre_dt'))[:19]:<19}  {s.get('stop_se_nm')}"
            )
    else:
        print(f"\n  ⚠ {SAMPLE_TRAIN_NO}가 이 범위에 없다. 정차 많은 열차 3편을 대신 보여준다:")
        for tno in sorted(by_train, key=lambda k: -len(by_train[k]))[:3]:
            names = [str(r.get("stn_nm")) for r in sorted(by_train[tno], key=lambda r: int(r.get("trn_run_sn") or 0))]
            print(f"     {tno}: {' → '.join(names[:14])}{' …' if len(names) > 14 else ''}")

    print(f"\n  정차구분 값 종류: {sorted({str(r.get('stop_se_nm')) for r in rows})}")

    # ── S3. 요일 안정성 ───────────────────────────────────────────────
    step("S3 — 정차 순서가 날짜에 걸쳐 동일한가 (캐시 안전성)")
    print("  같으면 train_stop 캐시가 안전하다. 다르면 요일별로 나눠 캐시해야 한다.")
    signatures: dict[str, list[str]] = {}
    for d, total in available[:4]:
        if d == freshest:
            sig = [str(s.get("stn_nm")) for s in stops]
        else:
            # 해당 날짜에서 표본 열차만 찾기 위해 역 필터로 좁힌다 (호출 절약)
            got: list[dict] = []
            for page in range(1, min(-(-total // PAGE_SIZE), MAX_PAGES) + 1):
                items = items_of(
                    call(
                        OP_INFO,
                        {**day_filter(d), "numOfRows": str(PAGE_SIZE), "pageNo": str(page)},
                        key,
                        f"{d} page {page}",
                    )
                )
                if not items:
                    break
                got.extend(items)
                if stop_list(got, SAMPLE_TRAIN_NO):
                    break
            sig = [str(s.get("stn_nm")) for s in stop_list(got, SAMPLE_TRAIN_NO)]
        signatures[str(d)] = sig
        label = "월화수목금토일"[d.weekday()]
        print(f"  {d} ({label}) {len(sig):>2}개  {' → '.join(sig[:10])}{' …' if len(sig) > 10 else ''}")

    distinct = {tuple(v) for v in signatures.values() if v}
    print(f"\n  → 서로 다른 정차 패턴 {len(distinct)}종")
    if len(distinct) == 1:
        print("  ✅ 날짜와 무관하게 동일 — 열차번호 단위 캐시로 충분하다")
    elif len(distinct) > 1:
        print("  ⚠ 날짜별로 다르다 — 요일 구분이 필요할 수 있다 (평일/주말 확인)")

    # ── S4. 운행계획으로 대상일 운행 여부 ─────────────────────────────
    step("S4 — 운행계획: 내일 그 열차가 운행하는지 알 수 있는가")
    tomorrow = today + timedelta(days=1)
    plan_total = total_of(call(OP_PLAN, {**day_filter(tomorrow), "numOfRows": "1"}, key, "plan count"))
    print(f"  내일({tomorrow}) 운행계획 {plan_total}건")
    if plan_total:
        plan_rows: list[dict] = []
        for page in range(1, min(-(-plan_total // PAGE_SIZE), MAX_PAGES) + 1):
            items = items_of(
                call(
                    OP_PLAN,
                    {**day_filter(tomorrow), "numOfRows": str(PAGE_SIZE), "pageNo": str(page)},
                    key,
                    f"plan page {page}",
                )
            )
            if not items:
                break
            plan_rows.extend(items)
        hit = [r for r in plan_rows if str(r.get("trn_no") or "").lstrip("0") == SAMPLE_TRAIN_NO]
        print(f"  받은 계획 {len(plan_rows)}건 / 열차 {len({str(r.get('trn_no')) for r in plan_rows})}편")
        for r in hit:
            print(
                f"  ✅ {SAMPLE_TRAIN_NO}: {r.get('dptre_stn_nm')}({str(r.get('trn_plan_dptre_dt'))[:19]})"
                f" → {r.get('arvl_stn_nm')}({str(r.get('trn_plan_arvl_dt'))[:19]})"
            )
        if not hit:
            print(f"  ⚠ 내일 계획에 {SAMPLE_TRAIN_NO}가 없다 (운휴이거나 번호가 다르다)")

    # ── S5. 역 마스터 ─────────────────────────────────────────────────
    step("S5 — 역 마스터(역코드+역명) 수집량")
    stations = {(str(r.get("stn_cd")), str(r.get("stn_nm"))) for r in rows}
    print(f"  하루치 표본에서 역 {len(stations)}개")
    for cd, nm in sorted(stations)[:10]:
        print(f"     {cd:>8}  {nm}")

    out = RESULTS / "stops_probe.json"
    out.write_text(json.dumps(LOG, ensure_ascii=False, indent=2), encoding="utf-8")
    step("요약 — 이것만 알려주면 된다")
    print(f"  S1 최신 가용일 : {freshest} (오늘-{(today - freshest).days}일), 하루 {fresh_total}건")
    print(f"  S2 정차역 조립 : {'성공 (' + str(len(stops)) + '개)' if stops else '표본 열차 미발견'}")
    print(f"  S3 정차 패턴   : {len(distinct)}종 {'(동일 = 캐시 안전)' if len(distinct) == 1 else ''}")
    print(f"  S4 내일 계획   : {plan_total}건")
    print(f"  S5 역 마스터   : {len(stations)}개")
    print(f"\n  원시 응답: {out}   총 호출 {len(LOG)}회")


if __name__ == "__main__":
    main()
