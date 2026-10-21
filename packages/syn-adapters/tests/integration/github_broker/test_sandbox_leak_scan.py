"""The S2 leak scan flags any GitHub-token-shaped value, not only the harness's (#1735).

Runs the exact command the integration matrix runs in the sandbox, against
planted files and a controlled env. Every value here is invented.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from sandbox_leak_scan import leak_scan
from test_git_gh_through_broker import GH_CAP, GIT_CAP, REAL_TOKENS

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash"),
]

# Shaped like GitHub tokens, minted by nobody, and absent from REAL_TOKENS.
INVENTED = (
    "ghs_inventedS2planted0000000000000000",
    "ghp_inventedS2planted0000000000000000",
    "gho_inventedS2planted0000000000000000",
    "ghu_inventedS2planted0000000000000000",
    "ghr_inventedS2planted0000000000000000",
    "github_pat_inventedS2planted_000000000000",
)


def _scan(home: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["bash", "-c", leak_scan([str(home)], REAL_TOKENS)],
        env={"PATH": "/usr/bin:/bin", **(env or {})},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result.stdout


def _home_with_capabilities(tmp_path: Path) -> Path:
    gh = tmp_path / ".config" / "gh"
    gh.mkdir(parents=True)
    (gh / "hosts.yml").write_text(f"github.com:\n    oauth_token: {GH_CAP}\n    user: s2\n")
    (tmp_path / ".git-credentials").write_text(
        f"http://x-access-token:{GIT_CAP}@github-git.broker:8081/o/r\n"
    )
    return tmp_path


def test_capabilities_alone_are_clean(tmp_path: Path) -> None:
    home = _home_with_capabilities(tmp_path)
    assert _scan(home, {"GH_TOKEN": GH_CAP}) == ""


@pytest.mark.parametrize("token", INVENTED)
def test_an_invented_token_in_hosts_yml_is_flagged(tmp_path: Path, token: str) -> None:
    assert token not in REAL_TOKENS
    home = _home_with_capabilities(tmp_path)
    (home / ".config" / "gh" / "hosts.yml").write_text(f"github.com:\n    oauth_token: {token}\n")
    assert _scan(home).split() == [str(home / ".config" / "gh" / "hosts.yml")]


@pytest.mark.parametrize("token", INVENTED)
def test_an_invented_token_in_env_is_flagged(tmp_path: Path, token: str) -> None:
    home = _home_with_capabilities(tmp_path)
    assert _scan(home, {"GH_TOKEN": token}).split() == [f"GH_TOKEN={token}"]


def test_a_known_real_token_is_still_flagged(tmp_path: Path) -> None:
    home = _home_with_capabilities(tmp_path)
    (home / "notes").write_text(f"{REAL_TOKENS[0]}\n")
    assert str(home / "notes") in _scan(home).split()
