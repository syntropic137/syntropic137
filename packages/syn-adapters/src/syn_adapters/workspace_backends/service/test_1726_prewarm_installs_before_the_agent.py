"""A prewarming setup installs the clones' locked dependencies, frozen, before the agent (#1726).

These EXECUTE the generated setup script, as ``test_setup_phase_script_execution``
does: a ``git`` stub whose clone lays down the lockfiles a case names, and
``uv``/``pnpm``/``cargo`` stubs that record where they ran and with what. The
assertions are about what the script does, not about its text.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from syn_adapters.workspace_backends.service.dependency_prewarm import PREWARM_TIMEOUT_SECONDS
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets

pytestmark = pytest.mark.unit

_REPO = "https://github.com/org/repo-a"

GIT_STUB = """#!/bin/bash
case "$*" in
  clone*)
    for arg in "$@"; do dest="$arg"; done
    printf 'CALL:clone\\n' >> "$CALL_LOG"
    for lock in $FAKE_LOCKS; do mkdir -p "$(dirname "$dest/$lock")"; touch "$dest/$lock"; done
    ;;
esac
exit 0
"""

TOOL_STUB = """#!/bin/bash
printf 'CALL:%s %s @%s\\n' "$(basename "$0")" "$*" "$PWD" >> "$CALL_LOG"
var="FAKE_$(basename "$0" | tr a-z A-Z)_EXIT"
exit "${!var:-0}"
"""


class _Run:
    def __init__(self, proc: subprocess.CompletedProcess[str], calls: list[str], repo: Path):
        self.proc = proc
        self.repo = repo
        # Paths made relative to the clone, so the assertions read like the tree.
        self.calls = [c.replace(str(repo), "<repo>") for c in calls]


@pytest.fixture
def run(tmp_path: Path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (
        ("git", GIT_STUB),
        ("uv", TOOL_STUB),
        ("pnpm", TOOL_STUB),
        ("cargo", TOOL_STUB),
    ):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    (tmp_path / "home").mkdir()
    workspace = tmp_path / "ws"
    log = tmp_path / "calls.log"

    def _run(secrets: SetupPhaseSecrets, locks: str, **exits: int) -> _Run:
        script = secrets.build_setup_script().replace("/workspace", str(workspace))
        (tmp_path / "setup.sh").write_text(script)
        env = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "HOME": str(tmp_path / "home"),
            "CALL_LOG": str(log),
            "FAKE_LOCKS": locks,
            **{f"FAKE_{tool.upper()}_EXIT": str(code) for tool, code in exits.items()},
        }
        proc = subprocess.run(
            ["bash", str(tmp_path / "setup.sh")], capture_output=True, text=True, env=env
        )
        calls = log.read_text().splitlines() if log.exists() else []
        return _Run(proc, calls, workspace / "repos" / "repo-a")

    return _run


def _secrets(*, prewarm: bool = True, clone_repos: bool = True) -> SetupPhaseSecrets:
    return SetupPhaseSecrets(
        repositories=[_REPO],
        repo_tokens={_REPO: "tok-a"},
        clone_repos=clone_repos,
        prewarm=prewarm,
    )


def test_every_locked_ecosystem_is_installed_frozen_in_its_own_directory_after_the_clone(
    run,
) -> None:
    result = run(
        _secrets(),
        "uv.lock pyproject.toml apps/web/pnpm-lock.yaml pnpm-lock.yaml "
        "lib/tool/Cargo.lock lib/tool/Cargo.toml",
    )

    assert result.proc.returncode == 0, result.proc.stderr
    # `cargo --version` is the script probing for a toolchain, not an install.
    installs = [c.split(" @")[0] for c in result.calls if not c.startswith("CALL:cargo --version")]
    assert installs == [
        "CALL:clone",
        "CALL:uv sync --frozen",
        "CALL:pnpm install --frozen-lockfile",
        "CALL:pnpm install --frozen-lockfile",
        "CALL:cargo fetch --locked --manifest-path <repo>/lib/tool/Cargo.toml",
    ]
    assert [c.split(" @")[1] for c in result.calls[1:4]] == ["<repo>", "<repo>/apps/web", "<repo>"]


@pytest.mark.parametrize(
    ("locks", "tool", "expected"),
    [
        ("uv.lock", "uv", "CALL:uv sync --frozen @<repo>"),
        ("pnpm-lock.yaml", "pnpm", "CALL:pnpm install --frozen-lockfile @<repo>"),
    ],
)
def test_a_failed_install_fails_setup_so_no_agent_starts(
    run, locks: str, tool: str, expected: str
) -> None:
    result = run(_secrets(), locks, **{tool: 7})

    assert result.proc.returncode != 0
    assert result.calls[-1] == expected


def test_a_repo_with_no_lockfile_installs_nothing(run) -> None:
    result = run(_secrets(), "README.md")

    assert result.proc.returncode == 0, result.proc.stderr
    assert result.calls == ["CALL:clone"]


def test_a_dependency_directory_is_not_searched_for_lockfiles(run) -> None:
    result = run(_secrets(), "uv.lock node_modules/dep/pnpm-lock.yaml")

    assert result.proc.returncode == 0, result.proc.stderr
    assert result.calls == ["CALL:clone", "CALL:uv sync --frozen @<repo>"]


def test_provisioning_twice_installs_again_and_still_succeeds(run) -> None:
    first = run(_secrets(), "uv.lock")
    second = run(_secrets(), "uv.lock")

    assert first.proc.returncode == 0 and second.proc.returncode == 0, second.proc.stderr
    # The clone is skipped the second time (its guard); the install is not,
    # and a frozen install over a warm environment is a no-op that succeeds.
    assert second.calls.count("CALL:uv sync --frozen @<repo>") == 2


@pytest.mark.parametrize(
    "secrets", [_secrets(prewarm=False), _secrets(clone_repos=False)], ids=["off", "no-clone"]
)
def test_without_prewarm_and_a_checkout_nothing_is_installed(run, secrets) -> None:
    result = run(secrets, "uv.lock pnpm-lock.yaml Cargo.lock Cargo.toml")

    assert result.proc.returncode == 0, result.proc.stderr
    assert not [c for c in result.calls if c != "CALL:clone"]
    assert secrets.setup_timeout_seconds(120) == 120


def test_prewarm_is_off_unless_asked_for() -> None:
    assert SetupPhaseSecrets(repositories=[_REPO]).prewarm is False


def test_only_a_prewarming_setup_gets_the_install_budget() -> None:
    assert _secrets().setup_timeout_seconds(120) == 120 + PREWARM_TIMEOUT_SECONDS
