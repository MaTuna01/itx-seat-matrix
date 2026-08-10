#!/usr/bin/env python3
"""DB 백업 — `.backup` 으로 일관 스냅샷을 떠서 S3에 올린다 (#60).

리전 이관 이후 `data/itx.db`의 사본이 **어디에도 없었다.** 서울 EBS 볼륨 하나에만 있고,
그 안에 코레일 자격증명(Fernet 암호)과 푸시 기기 등록, 그리고 저장소에 없는
station·train_stop 캐시가 들어 있다 (D-29 — 소스 CSV는 `data/`가 gitignore라 없다).

## 파일 복사가 아니라 `.backup` 이다 (D-41)

`journal_mode = WAL`이라 가장 최근 커밋이 `itx.db-wal`에 있다. `itx.db`만 복사하면 파일은
정상적으로 열리고 앱도 잘 뜨는데 **방금 등록한 자격증명이나 푸시 기기만 없다.**
가장 나쁜 종류의 조용한 실패다. `sqlite3.Connection.backup`은 온라인 백업 API라
**앱을 내리지 않고도** 일관된 단일 파일을 만든다.

## 떴다고 끝이 아니다 — 내용을 확인한다

빈 DB도 `.backup`은 성공한다. 검증 없이 올리면 **"백업이 있다"는 잘못된 안심**을 얻는다.
`user`와 `station`이 비어 있으면 실패로 처리한다 — 그 둘이 0인 정상 상태는 없다
(가입이 잠겨 있어 계정은 항상 있고, station 캐시는 화면이 뜨는 전제다).
`subscription`·`push_device`는 0일 수 있으므로 세지만 막지 않는다.

## 성공 시각을 파일로 남긴다 — `deploy_check.sh`가 읽는다

알림 종류는 5개로 고정이라 늘리지 않는다 (PLAN 8절). 로그만 남기면 아무도 안 본다.
그래서 성공 시각을 `STAMP_PATH`에 적고, `deploy_check.sh`가 그 나이를 **배포마다** 찍는다 —
백업이 조용히 멈춘 것이 다음 배포 화면에 드러난다.

**경고(`!`)이지 치명(`✗`)이 아니다.** 낡은 백업 때문에 배포가 롤백되면 안 된다.

## EC2 호스트에서 돈다 — 표준 라이브러리 + AWS CLI

호스트에는 uv도 boto3도 없다. S3 업로드는 `aws s3 cp`에 맡긴다. 자격은 **IAM 인스턴스
프로파일**에서 오므로 이 파일에도, 디스크에도 키가 없다.

종료 코드: 0 = 성공 / 1 = 실패 (systemd가 journal에 남긴다)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 조정 예정 값은 로직에 인라인하지 않는다 (D-17).
# 비어 있으면 백업으로 인정하지 않는 테이블. 나머지는 세기만 한다
REQUIRED_TABLES = ("user", "station")
COUNTED_TABLES = ("user", "subscription", "station", "train_stop", "push_device")

# systemd 유닛의 `StateDirectory=itx-backup` 이 이 디렉터리를 만들어 준다 (0755).
# `deploy_check.sh` 는 `ubuntu` 로 도므로 읽을 수 있어야 한다
STAMP_PATH = Path("/var/lib/itx-backup/last_success")


def snapshot(src: Path, dest: Path) -> None:
    """`.backup` 으로 일관 스냅샷을 만든다 (D-41). 앱을 내리지 않아도 된다."""
    source = sqlite3.connect(src)
    try:
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def count_rows(conn: sqlite3.Connection) -> dict[str, int]:
    """`COUNTED_TABLES` 의 행 수. 없는 테이블은 -1 로 표시한다."""
    counts: dict[str, int] = {}
    for table in COUNTED_TABLES:
        try:
            counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            counts[table] = -1
    return counts


def problems(counts: dict[str, int]) -> list[str]:
    """백업으로 인정할 수 없는 사유. 빈 목록이면 통과다."""
    found: list[str] = []
    for table in REQUIRED_TABLES:
        n = counts.get(table, -1)
        if n < 0:
            found.append(f"{table} 테이블이 없다")
        elif n == 0:
            found.append(f"{table} 가 비어 있다")
    return found


def s3_key(now: datetime) -> str:
    """`itx-2026-08-10.db` — 날짜 하나당 하나. 같은 날 두 번 돌면 덮어쓴다.

    수명 주기 정책이 지우기 쉬운 평평한 이름을 쓴다. 시각까지 넣으면 하루에 여러 개가
    쌓여 "하루 1개, 30일" 이라는 약속이 흐려진다.
    """
    return f"itx-{now.strftime('%Y-%m-%d')}.db"


def upload(local: Path, s3_uri: str, key: str) -> None:
    """`aws s3 cp`. 자격은 IAM 인스턴스 프로파일에서 온다 — 디스크에 키가 없다."""
    if shutil.which("aws") is None:
        raise RuntimeError(
            "aws CLI 가 없다 — sudo apt-get install -y awscli (DEPLOY.md 9절)"
        )
    dest = f"{s3_uri.rstrip('/')}/{key}"
    proc = subprocess.run(  # noqa: S603 — 인자를 리스트로 넘긴다(셸 없음)
        ["aws", "s3", "cp", str(local), dest, "--only-show-errors"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"업로드 실패 ({proc.returncode}): {proc.stderr.strip()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="itx.db 를 S3에 백업한다 (#60)")
    parser.add_argument("db", type=Path, help="itx.db 경로")
    parser.add_argument(
        "--s3-uri",
        default=os.environ.get("ITX_BACKUP_S3_URI"),
        help="s3://버킷/접두사. 기본값은 환경변수 ITX_BACKUP_S3_URI",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="스냅샷과 검증만 한다 (업로드·기록 없음). 손으로 확인할 때",
    )
    parser.add_argument(
        "--stamp",
        type=Path,
        default=STAMP_PATH,
        help=f"성공 시각을 적을 파일 (기본 {STAMP_PATH})",
    )
    parser.add_argument("--now", default=None, help="기준 시각(ISO8601, KST). 테스트용")
    args = parser.parse_args(argv)

    now = datetime.now(KST) if args.now is None else datetime.fromisoformat(args.now)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    now = now.astimezone(KST)

    db_path = args.db.expanduser()
    if not db_path.exists():
        print(f"백업 실패: {db_path} 가 없다")
        return 1
    if not args.no_upload and not args.s3_uri:
        print("백업 실패: --s3-uri 도 ITX_BACKUP_S3_URI 도 없다 (DEPLOY.md 9절)")
        return 1

    # 임시 파일은 0600으로 만든다 — Fernet 암호문이지만 SECRET_KEY와 짝이 맞으면 풀린다
    fd, tmp_name = tempfile.mkstemp(prefix="itx-backup-", suffix=".db")
    os.close(fd)
    tmp = Path(tmp_name)
    tmp.chmod(0o600)

    try:
        try:
            snapshot(db_path, tmp)
        except sqlite3.Error as exc:
            print(f"백업 실패: 스냅샷을 뜨지 못했다 ({exc})")
            return 1

        conn = sqlite3.connect(tmp)
        try:
            counts = count_rows(conn)
        finally:
            conn.close()

        summary = " / ".join(f"{t}={n}" for t, n in counts.items())
        found = problems(counts)
        if found:
            print(f"백업 실패: {', '.join(found)} — 올리지 않는다 ({summary})")
            return 1

        size_kb = tmp.stat().st_size // 1024
        if args.no_upload:
            print(f"검증 통과 (업로드 생략): {size_kb}KB / {summary}")
            return 0

        key = s3_key(now)
        try:
            upload(tmp, args.s3_uri, key)
        except RuntimeError as exc:
            print(f"백업 실패: {exc}")
            return 1

        # 성공 기록은 업로드가 끝난 뒤에만 — 이 파일의 나이가 곧 "마지막 성공"이다
        try:
            args.stamp.parent.mkdir(parents=True, exist_ok=True)
            args.stamp.write_text(now.isoformat() + "\n", encoding="utf-8")
        except OSError as exc:
            # 업로드는 됐다. 기록만 실패한 것을 성공으로 덮지 않는다 —
            # deploy_check 가 낡았다고 경고하는 편이 낫다
            print(f"백업은 됐으나 성공 기록에 실패했다 ({exc})")
            return 1

        print(f"백업 성공: {key} ({size_kb}KB) / {summary}")
        return 0
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
