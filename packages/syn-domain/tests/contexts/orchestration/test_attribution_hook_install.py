"""The operator attribution hook reaches the workspace, or says why not.

This exists because the feature was wired end to end, tested on both sides, and
still produced no trailer for four months. Both halves had tests; the join had
none, and the join was what was broken.

So these tests are about the JOIN: the hook's bytes, the path it lands on, the
executable bit git silently requires, and the verification that the install
actually happened rather than merely being attempted.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_hooks import (
    HOOK_FILENAME,
    WORKSPACE_HOOKS_DIR,
    attribution_hook_source,
)

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run nothing.
pytestmark = pytest.mark.unit


@dataclass
class _Result:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class _FakeWorkspace:
    """Records what would reach a real container."""

    injected: list[tuple[str, list[tuple[str, bytes]]]] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)
    exit_codes: dict[str, int] = field(default_factory=dict)

    async def inject_files(
        self, files: list[tuple[str, bytes]], base_path: str = "/workspace"
    ) -> None:
        self.injected.append((base_path, files))

    async def execute(self, argv: list[str], **_: object) -> _Result:
        self.commands.append(argv)
        return _Result(exit_code=self.exit_codes.get(argv[0], 0))


@pytest.fixture
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_OPERATOR_NAME", "Neural Empowerment")
    monkeypatch.setenv("SYN_OPERATOR_EMAIL", "1+n@users.noreply.github.com")


@pytest.fixture
def _unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYN_OPERATOR_NAME", raising=False)
    monkeypatch.delenv("SYN_OPERATOR_EMAIL", raising=False)


async def test_the_hook_is_staged_then_moved_onto_the_hooks_path(
    _configured: None,
) -> None:
    """base_path does not reach the container, so the move is what places it.

    ``copy_to_workspace`` writes relative to the workspace root and takes no
    base_path at all (adapter_copy.py:118-133) - passing one is accepted and
    discarded. Injecting straight to the hooks directory silently put the file
    at /workspace/prepare-commit-msg instead, where git never looks.
    """
    ws = _FakeWorkspace()

    await WorkspaceProvisionHandler._install_attribution_hook(ws)  # type: ignore[arg-type]

    assert ws.injected, "hook was never injected"
    _base, files = ws.injected[0]
    assert files[0][1] == attribution_hook_source()

    shell = " ".join(c[2] for c in ws.commands if c[:2] == ["sh", "-c"])
    assert f"mv /workspace/{files[0][0]} {WORKSPACE_HOOKS_DIR}/{HOOK_FILENAME}" in shell


async def test_the_staging_file_does_not_survive(_configured: None) -> None:
    """A stray file in /workspace is something an agent can commit by accident."""
    ws = _FakeWorkspace()

    await WorkspaceProvisionHandler._install_attribution_hook(ws)  # type: ignore[arg-type]

    _base, files = ws.injected[0]
    staged = files[0][0]
    assert staged.startswith("."), "staging name should be dotted"
    shell = " ".join(c[2] for c in ws.commands if c[:2] == ["sh", "-c"])
    assert f"mv /workspace/{staged}" in shell, "staged file must be moved, not copied"


async def test_the_executable_bit_is_set(_configured: None) -> None:
    """git ignores a hook it cannot execute, and says nothing about it."""
    ws = _FakeWorkspace()

    await WorkspaceProvisionHandler._install_attribution_hook(ws)  # type: ignore[arg-type]

    shell = " ".join(c[2] for c in ws.commands if c[:2] == ["sh", "-c"])
    assert f"chmod +x {WORKSPACE_HOOKS_DIR}/{HOOK_FILENAME}" in shell


async def test_the_hooks_directory_is_created_if_absent(_configured: None) -> None:
    """It does not exist at provision time on every image."""
    ws = _FakeWorkspace()

    await WorkspaceProvisionHandler._install_attribution_hook(ws)  # type: ignore[arg-type]

    shell = " ".join(c[2] for c in ws.commands if c[:2] == ["sh", "-c"])
    assert f"mkdir -p {WORKSPACE_HOOKS_DIR}" in shell


async def test_the_install_is_verified_not_assumed(_configured: None) -> None:
    """A file written is not a hook installed.

    Reporting success without checking the effect is the exact shape of the
    defect this whole feature has been failing on.
    """
    ws = _FakeWorkspace()

    await WorkspaceProvisionHandler._install_attribution_hook(ws)  # type: ignore[arg-type]

    assert ["test", "-x", f"{WORKSPACE_HOOKS_DIR}/{HOOK_FILENAME}"] in ws.commands


async def test_nothing_is_written_when_attribution_is_not_configured(
    _unconfigured: None,
) -> None:
    """The hook no-ops unconfigured; writing it anyway is litter in every workspace."""
    ws = _FakeWorkspace()

    await WorkspaceProvisionHandler._install_attribution_hook(ws)  # type: ignore[arg-type]

    assert ws.injected == []
    assert ws.commands == []


async def test_a_failed_install_does_not_kill_the_phase(_configured: None) -> None:
    """A lost credit must not cost the work.

    Safe only because the install is verified - a silent failure is logged, not
    mistaken for success.
    """
    ws = _FakeWorkspace(exit_codes={"sh": 1})

    await WorkspaceProvisionHandler._install_attribution_hook(ws)  # type: ignore[arg-type]

    assert ["test", "-x", f"{WORKSPACE_HOOKS_DIR}/{HOOK_FILENAME}"] not in ws.commands


def test_the_hook_is_a_mirror_of_the_submodule_not_a_fork() -> None:
    """One source of truth, with a gate that says so.

    agentic-primitives owns this hook. The copy here exists only because
    omni-agent images do not carry it (AgentParadise/agentic-primitives#401).
    A copy that drifts is worse than no copy: two behaviours, one name.
    """
    # Walk up to the repository root rather than counting parents. A miscount
    # makes this test SKIP rather than fail, which is the same fail-open shape
    # the hook itself is a victim of - and it happened while writing this test.
    here = Path(__file__).resolve()
    repo_root = next((p for p in here.parents if (p / "lib/agentic-primitives").is_dir()), None)
    assert repo_root is not None, (
        "could not locate the repository root from this test file; the drift "
        "guard must not silently skip"
    )
    upstream = (
        repo_root
        / "lib/agentic-primitives/providers/workspaces/claude-cli/scripts/git-hooks"
        / HOOK_FILENAME
    )
    if not upstream.is_file():
        pytest.skip("agentic-primitives submodule not checked out")

    assert upstream.read_bytes() == attribution_hook_source(), (
        f"{HOOK_FILENAME} has drifted from the submodule's copy. agentic-primitives "
        f"owns this file; re-mirror it rather than editing the copy here."
    )


def test_the_hook_is_a_valid_shell_script() -> None:
    """It runs as /bin/sh in a container with no interpreter check of our own."""
    src = attribution_hook_source()
    assert src.startswith(b"#!/bin/sh"), "hook must be a POSIX sh script"

    proc = subprocess.run(["/bin/sh", "-n"], input=src, capture_output=True, check=False)
    assert proc.returncode == 0, f"hook is not valid sh: {proc.stderr.decode()}"
