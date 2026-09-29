"""Fitness function: nothing tells Codex to turn its own sandbox off (#1398).

Delegated Codex runs through ``syn-delegate codex`` with ``--sandbox
workspace-write`` (or ``read-only``); the workspace supplies the seccomp and
AppArmor policy bubblewrap needs. The bypass flag was once the documented
workaround, in a shipped workflow prompt that agents copy verbatim. It must not
come back in code, workflows, prompts or docs: an agent reads all of them.

Scope: every file tracked by THIS repository. Submodules under ``lib/`` are
their own repositories with their own checks (agentic-workspace tests the
refusal itself), and are gitlinks here, so ``git ls-files`` never lists their
contents.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]

# Codex CLI spellings that disable Codex's sandbox and approvals together.
# Built by concatenation so this file does not match its own scan.
_FORBIDDEN = (
    "--dangerously-" + "bypass-approvals-and-sandbox",
    "dangerously_" + "bypass_approvals_and_sandbox",
    "--" + "yolo",
)


def _tracked_files(root: Path) -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    return [root / name for name in listed.split("\0") if name]


def _violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in _tracked_files(root):
        if not path.is_file():
            continue  # gitlinks (submodules) and deleted-but-unstaged files
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(token in line for token in _FORBIDDEN):
                found.append(f"{path.relative_to(root)}:{lineno}: {line.strip()[:120]}")
    return found


@pytest.mark.architecture
def test_no_codex_sandbox_bypass_anywhere_in_the_repo() -> None:
    violations = _violations(_ROOT)
    if violations:
        pytest.fail(
            "Codex sandbox bypass found (#1398). Delegate with `syn-delegate codex` "
            "(sandbox on); fix the host policy instead of disabling the sandbox "
            "(docs/deployment/apparmor-codex-sandbox.md):\n  " + "\n  ".join(violations)
        )


@pytest.mark.architecture
def test_planted_bypass_is_caught(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for index, token in enumerate(_FORBIDDEN):
        planted = tmp_path / f"workflow-{index}.yaml"
        planted.write_text(f"prompt: run codex exec {token} -C /workspace\n")
    (tmp_path / "clean.md").write_text("syn-delegate codex --prompt=x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    assert len(_violations(tmp_path)) == len(_FORBIDDEN)
