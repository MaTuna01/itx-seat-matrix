"""역 마스터 CSV 적재 (Phase 2 항목 G, D-25).

공공데이터포털의 역 관련 CSV를 `station` 테이블에 넣는다. **정적 참조 데이터를
런타임에 API로 긁지 않는다** — 쿼터·네트워크 의존이 사라지고, 열차 안에서
네트워크가 나빠도 역 목록은 항상 뜬다.

여러 파일을 **순서와 무관하게** 합칠 수 있다. 컬럼이 서로 다른 파일들
(좌표만 있는 것 / 역코드만 있는 것)을 각각 적재하면 역명 기준으로 병합된다
(`storage/stations.upsert`가 COALESCE로 기존 값을 보존한다).

## 쓰는 법

    # 1) CSV를 아무 디렉터리에 모아둔다 (기본값: data/reference/)
    # 2) 먼저 무엇이 적재될지 확인
    uv run python scripts/load_stations.py --dry-run
    # 3) 실제 적재
    uv run python scripts/load_stations.py

    # 파일을 직접 지정할 수도 있다
    uv run python scripts/load_stations.py path/to/역위치정보.csv

## 알려진 소스

- **한국철도공사_역 위치 정보** (data.go.kr 15127532) — 지역본부/역명/위도/경도/출입구개수.
  **역코드 컬럼이 없다** → 좌표 축만 채운다
- 역코드를 담은 CSV (역코드/역명) → 코드 축을 채운다
- 인코딩은 보통 CP949(EUC-KR)다. UTF-8도 자동 판별한다

## 컬럼 매핑

공공데이터 CSV는 같은 뜻의 컬럼명이 파일마다 다르다. 헤더 이름을 **별칭 표**로
맞춘다 — 새 파일에서 못 알아보는 헤더가 나오면 `--dry-run`이 그대로 보여주므로
아래 표에 한 줄 추가하면 된다.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.models import KST  # noqa: E402
from app.storage.db import get_conn, init_db  # noqa: E402
from app.storage.stations import (  # noqa: E402
    Station,
    count,
    count_with_coords,
    normalize_name,
    upsert,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "data" / "reference"

# 헤더 별칭 → 논리 필드. 비교는 공백·특수문자를 뺀 소문자로 한다.
ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("역명", "역이름", "station", "stationname", "stnnm", "역", "정차역명"),
    "code": ("역코드", "stationcode", "stncd", "코드", "역번호", "stationid"),
    "lat": ("위도", "latitude", "lat", "y좌표", "ycoord"),
    "lng": ("경도", "longitude", "lng", "lon", "x좌표", "xcoord"),
    "line": ("주운행선명", "선명", "노선명", "line", "linename", "mrntnm", "지역본부"),
}


def _slug(header: str) -> str:
    return "".join(ch for ch in str(header).lower() if ch.isalnum())


def map_headers(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """헤더 → 논리 필드 매핑과, 못 알아본 헤더 목록을 돌려준다."""
    mapping: dict[str, str] = {}
    unknown: list[str] = []
    for header in headers:
        slug = _slug(header)
        for field, names in ALIASES.items():
            if slug in {_slug(n) for n in names}:
                # 같은 필드에 여러 컬럼이 매칭되면 첫 번째만 쓴다
                mapping.setdefault(field, header)
                break
        else:
            unknown.append(header)
    return mapping, unknown


def _read_text(path: Path) -> str:
    """공공데이터 CSV는 대개 CP949다. UTF-8(BOM 포함)도 받아준다."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"인코딩을 판별할 수 없다: {path}")


def _to_float(value: str | None) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_rows(path: Path) -> tuple[list[Station], list[str], int]:
    """CSV → Station 목록. (역, 못 알아본 헤더, 건너뛴 행 수)."""
    text = _read_text(path)
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    mapping, unknown = map_headers(headers)

    if "name" not in mapping:
        raise SystemExit(
            f"{path.name}: 역명 컬럼을 찾을 수 없다.\n"
            f"  헤더: {headers}\n"
            f"  → scripts/load_stations.py 의 ALIASES['name']에 실제 헤더명을 추가하라."
        )

    stations: list[Station] = []
    skipped = 0
    for row in reader:
        name = normalize_name(row.get(mapping["name"], ""))
        if not name:
            skipped += 1
            continue
        code = str(row.get(mapping["code"], "") or "").strip() if "code" in mapping else None
        lat = _to_float(row.get(mapping["lat"])) if "lat" in mapping else None
        lng = _to_float(row.get(mapping["lng"])) if "lng" in mapping else None
        line = str(row.get(mapping["line"], "") or "").strip() if "line" in mapping else None
        stations.append(
            Station(name=name, code=code or None, lat=lat, lng=lng, line=line or None)
        )
    return stations, unknown, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="역 마스터 CSV를 station 테이블에 적재한다")
    parser.add_argument("files", nargs="*", type=Path, help=f"CSV 파일 (기본: {DEFAULT_DIR}/*.csv)")
    parser.add_argument("--dry-run", action="store_true", help="적재하지 않고 무엇이 들어갈지만 보여준다")
    args = parser.parse_args()

    files = args.files or sorted(DEFAULT_DIR.glob("*.csv"))
    if not files:
        raise SystemExit(
            f"CSV가 없다. {DEFAULT_DIR} 에 파일을 넣거나 경로를 인자로 주어라.\n"
            "  예: 한국철도공사_역 위치 정보 (data.go.kr 15127532) 다운로드 후 그 디렉터리에 저장"
        )

    now = datetime.now(KST)
    total_parsed = 0

    with get_conn() as conn:
        init_db()
        before, before_coords = count(conn), count_with_coords(conn)

        for path in files:
            if not path.exists():
                print(f"✗ 없는 파일: {path}")
                continue
            stations, unknown, skipped = parse_rows(path)
            total_parsed += len(stations)
            with_coords = sum(1 for s in stations if s.has_coords)
            with_code = sum(1 for s in stations if s.code)

            print(f"\n── {path.name}")
            print(f"   행 {len(stations)}개 (건너뜀 {skipped}) / 좌표 {with_coords} / 역코드 {with_code}")
            if unknown:
                print(f"   ⓘ 못 알아본 헤더 (무시됨): {unknown}")
            for s in stations[:5]:
                print(f"     {s.name:<10} code={s.code or '-':<9} ({s.lat}, {s.lng}) {s.line or ''}")
            if len(stations) > 5:
                print(f"     … 외 {len(stations) - 5}개")

            if not args.dry_run:
                for s in stations:
                    upsert(conn, s, source=path.name, now=now)

        if args.dry_run:
            print(f"\n[dry-run] 적재하지 않았다. 파싱된 행 {total_parsed}개.")
            print(f"          현재 station 테이블: {before}개 (좌표 {before_coords}개)")
            return

        after, after_coords = count(conn), count_with_coords(conn)
        print(f"\n✅ 적재 완료")
        print(f"   station {before} → {after}개 (좌표 {before_coords} → {after_coords}개)")
        no_coords = after - after_coords
        if no_coords:
            print(
                f"   ⓘ 좌표 없는 역 {no_coords}개 — GPS 보정 대상에서 제외된다 (D-13).\n"
                f"     좌표 CSV(15127532)를 함께 적재하면 채워진다."
            )


if __name__ == "__main__":
    main()
