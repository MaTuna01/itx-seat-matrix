#!/usr/bin/env python3
"""시크릿 유출 검사 — pre-commit 훅과 CI가 **같은 규칙**을 공유한다 (D-33, #21).

원래 이 로직은 `scripts/hooks/pre-commit` 안에만 있었다. 훅은 새 클론에서
`git config core.hooksPath scripts/hooks`를 실행해야 켜지고, **켜는 것을 잊으면
아무것도 막지 못한다.** CI는 잊어도 돈다. 그래서 검사를 여기로 옮기고 양쪽이 부른다.

## 두 모드의 입력이 다르다 (여기가 헷갈리는 지점)

    staged   훅. `git diff --cached` 기준 — 지금 커밋되려는 것.
    tree     CI. `git ls-files` 기준 — 이미 추적되고 있는 것 전부.

## ★ CI는 훅을 대체하지 못한다

훅의 3겹 중 **②(`.env`의 실제 값이 커밋 내용에 나타났는가)가 핵심**인데, 이것은
러너에 `.env`가 없어 **원리적으로 불가능하다** — 대조할 원본이 없다. CI에서 ②는
건너뛰고, 건너뛴 사실을 출력한다(조용히 통과시키지 않는다).

대신 CI는 훅이 못 하는 일을 한다: 스테이지가 아니라 **트리 전체**를 보므로
"훅이 꺼진 클론에서 이미 들어와 버린 것"을 잡는다. 둘은 대체가 아니라 보완이다.

`.env`의 실제 값이 새어나가는 경로를 기계로 더 막고 싶으면 GitHub의
Secret scanning / Push protection(public 저장소는 무료)을 저장소 설정에서 켜는 쪽이다 —
그건 코드가 아니라 설정이다.

사용:
    python3 scripts/secret_scan.py --mode staged   # 훅이 부른다
    python3 scripts/secret_scan.py --mode tree     # CI가 부른다
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ".env.example"

# `.env.example`에서 값을 가져도 되는 키 — 시크릿이 아닌 것만.
# 여기 없는 키에 값이 있으면 차단한다(기본 차단). 새 설정을 추가했는데 막히면,
# 정말 시크릿이 아닌 경우에만 이 목록에 넣어라.
PUBLIC_KEYS = {
    "DB_PATH",
    "COOKIE_SECURE",
    "SESSION_DAYS",
    "SESSION_TRANSIENT_HOURS",
    "ADAPTER",
    # Phase 3. VAPID_SUBJECT는 연락처 URI(mailto:)일 뿐이고, 발송 권한은
    # VAPID_PRIVATE_KEY가 쥔다 — 그쪽은 여기 없으므로 값이 채워지면 차단된다 (D-34)
    "VAPID_SUBJECT",
    "SCHEDULER_ENABLED",
    "SCHEDULER_INTERVAL_SECONDS",
    # Phase 4. 로그 레벨 — 시크릿이 아니다 (→ D-39)
    "LOG_LEVEL",
}

# 커밋되면 안 되는 경로 (.gitignore가 이미 막지만 `git add -f`를 뚫고 들어올 수 있다)
FORBIDDEN = (
    # `.env` 뿐 아니라 `.env.local` 같은 변종도. `.env.example`은 ALLOWED_NAMES가 뺀다
    re.compile(r"(^|/)\.env(\..+)?$"),
    # 확장자로 끝나는 형태 — `itx-prod.env`. 배포 때 실제로 이 이름으로 만들었다(DEPLOY.md 4절).
    # 앞의 패턴은 파일명이 `.env`로 **시작**할 때만 걸려서 이쪽을 놓친다.
    re.compile(r"\.env$"),
    re.compile(r"\.db$"),
    re.compile(r"^scripts/phase0_results/"),
)

# 이름만 보고 허용한다 — 유일하게 추적되어야 하는 env 파일
ALLOWED_NAMES = {".env.example"}

# 짧은 값은 검사하지 않는다 — "false"/"30"/"mock" 같은 설정값이 코드에 흔히 나온다
MIN_SECRET_LEN = 12


# ── 순수 검사 함수 (I/O 없음 — 테스트가 여기를 본다) ─────────────────


def parse_env(text: str) -> dict[str, str]:
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("'\"")
    return env


def check_forbidden(paths: list[str]) -> list[str]:
    """커밋되면 안 되는 파일이 들어 있는가."""
    problems = []
    for path in paths:
        if PurePosixPath(path).name in ALLOWED_NAMES:
            continue
        for pattern in FORBIDDEN:
            if pattern.search(path):
                problems.append(f"{path}: 커밋하면 안 되는 파일이다.")
                break
    return problems


def check_env_example(content: str | None) -> list[str]:
    """`.env.example`의 시크릿성 키가 비어 있는가.

    `content`는 모드에 따라 출처가 다르다 — 훅은 스테이지된 내용, CI는 체크아웃된
    파일. 파일이 없으면(`None`) 검사할 것이 없다.
    """
    if content is None:
        return []
    return [
        f"{ENV_EXAMPLE}: {key} 에 값이 채워져 있다. 실제 값은 .env 에만 둬라.\n"
        f"    (시크릿이 아니라면 scripts/secret_scan.py 의 PUBLIC_KEYS 에 추가)"
        for key, value in parse_env(content).items()
        if value and key not in PUBLIC_KEYS
    ]


def check_real_secrets(env_text: str | None, haystack: str) -> list[str]:
    """`.env`의 실제 값이 `haystack`에 나타나는가 — 파일 종류를 가리지 않는다.

    시크릿을 이 스크립트에 적어두지 않고 실행 시점에 `.env`(gitignore됨)에서 읽는다.
    `env_text`가 `None`이면 대조할 원본이 없다 — **CI가 이 상태다.**
    """
    if env_text is None:
        return []
    secrets = {
        key: value
        for key, value in parse_env(env_text).items()
        if len(value) >= MIN_SECRET_LEN and key not in PUBLIC_KEYS
    }
    return [
        f".env 의 {key} 실제 값이 커밋 내용에 들어 있다. "
        f"해당 줄을 지우고 .env 에만 남겨라."
        for key, value in secrets.items()
        if value in haystack
    ]


# ── git 접근 + 모드별 진입점 ─────────────────────────────────────────


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def _lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line]


def find_env_file() -> Path | None:
    """대조할 `.env`를 찾는다 — **워크트리에는 없다.**

    `.env`는 gitignore 대상이라 `git worktree add`로 만든 작업 디렉터리에는 복사되지
    않는다. 워크트리 루트만 보면 파일이 없고, 예전 구현은 그때 **조용히 통과**했다.
    즉 워크트리에서 한 모든 커밋에 대해 훅의 핵심 방어가 꺼져 있었던 셈이다
    (Phase 4 배포 작업을 전부 워크트리에서 했다).

    그래서 메인 체크아웃도 본다: `--git-common-dir`은 워크트리에서도 원본 `.git`을
    가리키므로 그 부모가 메인 작업 트리다.
    """
    candidates = [REPO / ".env"]
    try:
        common = Path(
            git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        )
        candidates.append(common.parent / ".env")
    except subprocess.CalledProcessError:
        pass  # 오래된 git — 워크트리 밖이라면 첫 후보로 충분하다
    return next((path for path in candidates if path.exists()), None)


def scan_staged() -> list[str]:
    """훅 모드 — 지금 커밋되려는 것만 본다. 3겹 전부."""
    paths = _lines(git("diff", "--cached", "--name-only", "--diff-filter=ACMR"))
    problems = check_forbidden(paths)
    # 워킹트리가 아니라 **스테이지된 내용**을 본다 — 커밋되는 건 이쪽이다
    staged_example = git("show", f":{ENV_EXAMPLE}") if ENV_EXAMPLE in paths else None
    problems += check_env_example(staged_example)

    env_path = find_env_file()
    if env_path is None:
        # 조용히 넘어가지 않는다 — 이 침묵이 워크트리에서 ②를 무력화한 원인이었다
        print(
            "  ⚠ 대조할 `.env` 를 찾지 못해 실제 값 검사를 건너뛴다 "
            "(금지 경로와 .env.example 검사는 돌았다).",
            file=sys.stderr,
        )
    problems += check_real_secrets(
        env_path.read_text(encoding="utf-8") if env_path else None,
        git("diff", "--cached"),
    )
    return problems


def scan_tree() -> list[str]:
    """CI 모드 — 추적 중인 파일 전부. ②는 `.env`가 없어 불가능하다."""
    problems = check_forbidden(_lines(git("ls-files")))
    example = REPO / ENV_EXAMPLE
    problems += check_env_example(
        example.read_text(encoding="utf-8") if example.exists() else None
    )
    print(
        f"  검사: 추적 파일 {len(_lines(git('ls-files')))}개 (금지 경로 + "
        f"{ENV_EXAMPLE} 시크릿성 키)\n"
        "  건너뜀: `.env` 실제 값 대조 — 러너에 `.env` 가 없어 원리적으로 불가능하다.\n"
        "          그 방어는 pre-commit 훅(D-33)이 유일하다. "
        "`git config core.hooksPath scripts/hooks` 를 잊지 마라."
    )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="시크릿 유출 검사 (D-33)")
    parser.add_argument("--mode", choices=("staged", "tree"), default="staged")
    args = parser.parse_args(argv)

    problems = scan_staged() if args.mode == "staged" else scan_tree()

    if not problems:
        print("✓ 시크릿 검사 통과")
        return 0

    blocked = "커밋을 막았다" if args.mode == "staged" else "CI 를 실패시켰다"
    print(f"\n✖ {blocked} — 시크릿이 새어나갈 수 있다\n", file=sys.stderr)
    for problem in problems:
        print(f"  • {problem}", file=sys.stderr)
    if args.mode == "staged":
        print("\n  정말 의도한 커밋이라면: git commit --no-verify\n", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
