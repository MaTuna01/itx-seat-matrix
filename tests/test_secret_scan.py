"""시크릿 검사 규칙 (D-33, #21).

훅과 CI가 이 로직을 공유하게 되면서 **훅을 고치면 CI도 같이 틀어진다.** 그래서
규칙에 테스트를 붙인다. 여기서 검사하는 것은 "막아야 할 것을 막는가"와
"막지 말아야 할 것을 통과시키는가" 양쪽이다 — 후자가 무너지면 훅이 짜증나서
`--no-verify`가 습관이 되고, 그게 훅이 죽는 실제 경로다.

`scripts/`는 패키지가 아니므로(`app/`과 달리 import 대상이 아니다) 파일 경로로 적재한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "secret_scan.py"
_spec = importlib.util.spec_from_file_location("secret_scan", _PATH)
assert _spec and _spec.loader
secret_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(secret_scan)


class TestForbiddenPaths:
    """커밋되면 안 되는 파일."""

    def test_env_and_variants_are_blocked(self) -> None:
        blocked = [
            ".env",
            "web/.env",
            ".env.local",
            ".env.production",
            # 배포 때 실제로 만든 이름 (DEPLOY.md 4절) — 확장자가 뒤에 오는 형태
            "itx-prod.env",
            "deploy/staging.env",
        ]
        problems = secret_scan.check_forbidden(blocked)
        assert len(problems) == len(blocked), problems

    def test_env_example_is_the_only_tracked_env_file(self) -> None:
        assert secret_scan.check_forbidden([".env.example"]) == []

    def test_db_files_are_blocked(self) -> None:
        assert secret_scan.check_forbidden(["data/itx.db", "itx-migrate.db"])
        assert len(secret_scan.check_forbidden(["a.db", "b.db"])) == 2

    def test_phase0_results_are_blocked(self) -> None:
        assert secret_scan.check_forbidden(["scripts/phase0_results/raw.json"])

    def test_ordinary_files_pass(self) -> None:
        assert (
            secret_scan.check_forbidden(
                [
                    "app/main.py",
                    "PLAN.md",
                    "web/src/SeatMatrix.jsx",
                    "scripts/secret_scan.py",
                    # 이름에 db/env가 들어가지만 그런 파일이 아니다
                    "app/storage/db.py",
                    "app/config.py",
                    "docs/environment.md",
                ]
            )
            == []
        )

    def test_one_problem_per_path_even_if_multiple_patterns_match(self) -> None:
        """`.env`는 두 패턴에 다 걸리지만 메시지는 하나여야 한다."""
        assert len(secret_scan.check_forbidden([".env"])) == 1


class TestEnvExample:
    """`.env.example`의 시크릿성 키는 비어 있어야 한다 (기본 차단)."""

    def test_filled_secret_key_is_blocked(self) -> None:
        problems = secret_scan.check_env_example(
            "SECRET_KEY=hQ2yA1nQ8vJZ0pQ7cX5rT3uW9sB6dF4gH8kL2mN0oP4=\n"
        )
        assert len(problems) == 1
        assert "SECRET_KEY" in problems[0]

    def test_empty_values_pass(self) -> None:
        assert (
            secret_scan.check_env_example(
                "SECRET_KEY=\nVAPID_PRIVATE_KEY=\nKORAIL_PW=\n"
            )
            == []
        )

    def test_public_keys_may_have_values(self) -> None:
        assert (
            secret_scan.check_env_example(
                "ADAPTER=mock\nLOG_LEVEL=INFO\nDB_PATH=data/itx.db\n"
                "SCHEDULER_ENABLED=true\nVAPID_SUBJECT=mailto:you@example.com\n"
            )
            == []
        )

    def test_unknown_key_with_value_is_blocked_by_default(self) -> None:
        """허용 목록에 없는 새 키는 일단 막는다 — 시크릿일 수 있다."""
        assert secret_scan.check_env_example("NEW_TOKEN=abc123\n")

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        assert (
            secret_scan.check_env_example(
                "# SECRET_KEY=looks_filled_but_is_a_comment\n\n   \nSECRET_KEY=\n"
            )
            == []
        )

    def test_quoted_empty_value_passes(self) -> None:
        assert secret_scan.check_env_example('SECRET_KEY=""\n') == []

    def test_missing_file_is_not_a_problem(self) -> None:
        """`.env.example`이 스테이지되지 않았거나 없을 때 (CI 포함)."""
        assert secret_scan.check_env_example(None) == []


class TestRealSecrets:
    """`.env`의 실제 값이 커밋 내용에 나타났는가 — 훅의 핵심 방어."""

    ENV = (
        "SECRET_KEY=hQ2yA1nQ8vJZ0pQ7cX5rT3uW9sB6dF4gH8kL2mN0oP4=\n"
        "ADAPTER=korail2\n"
        "SESSION_DAYS=30\n"
    )

    def test_secret_pasted_into_any_file_is_caught(self) -> None:
        diff = "+++ b/DEPLOY.md\n+    SECRET_KEY=hQ2yA1nQ8vJZ0pQ7cX5rT3uW9sB6dF4gH8kL2mN0oP4=\n"
        problems = secret_scan.check_real_secrets(self.ENV, diff)
        assert len(problems) == 1
        assert "SECRET_KEY" in problems[0]

    def test_clean_diff_passes(self) -> None:
        assert secret_scan.check_real_secrets(self.ENV, "+ print('hello')\n") == []

    def test_short_config_values_are_not_treated_as_secrets(self) -> None:
        """`korail2`/`30` 같은 값은 코드에 흔히 나온다 — 여기서 걸리면 훅이 못 쓴다."""
        diff = '+ADAPTER = "korail2"\n+SESSION_DAYS = 30\n'
        assert secret_scan.check_real_secrets(self.ENV, diff) == []

    def test_without_env_file_nothing_is_checked(self) -> None:
        """★ CI가 정확히 이 상태다 — 러너에 `.env`가 없다.

        이 검사는 CI에서 **원리적으로 불가능하다**(대조할 원본이 없다). 통과하는 것이
        "안전 확인됨"이 아니라 "검사 안 함"이라는 뜻이고, 그래서 CI 출력에 건너뛴
        사실을 찍는다. 이 테스트는 그 공백을 문서로 못 박아두는 용도다 —
        누군가 "CI가 있으니 훅은 필요 없다"고 결론내지 않도록.
        """
        leaked = "hQ2yA1nQ8vJZ0pQ7cX5rT3uW9sB6dF4gH8kL2mN0oP4="
        assert secret_scan.check_real_secrets(None, leaked) == []


class TestParseEnv:
    def test_strips_surrounding_quotes(self) -> None:
        parsed = secret_scan.parse_env("A='one'\nB=\"two\"\nC=three\n")
        assert parsed == {"A": "one", "B": "two", "C": "three"}

    def test_value_containing_equals_is_kept_whole(self) -> None:
        """Fernet 키는 `=`로 끝난다 — partition이 아니라 split이면 잘려나간다."""
        parsed = secret_scan.parse_env("SECRET_KEY=abc=def==\n")
        assert parsed["SECRET_KEY"] == "abc=def=="
