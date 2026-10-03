"""Fitness function: nothing hand-writes a Codex invocation with its sandbox off (#1398).

Delegated Codex runs through ``syn-delegate codex`` with ``--sandbox
workspace-write`` (or ``read-only``); the workspace supplies the seccomp and
AppArmor policy bubblewrap needs. The sandbox bypass was once the documented
workaround, in a shipped workflow prompt that agents copy verbatim. It must not
come back in code, workflows, prompts, docs or fixtures: an agent reads all of
them.

Forms detected (every spelling measured against codex-cli 0.155/0.156 help and
binary strings), case-insensitive, across whitespace, quotes, ``=``, commas and
line breaks, so an argv list split over lines is caught too:

* the sandbox-and-approvals bypass flag, its config/env spellings, and its
  short clap alias (``yolo`` with two leading dashes);
* ``--sandbox`` / ``-s`` with a sandbox-disabling mode;
* ``sandbox_mode`` set to one (``-c sandbox_mode=...``, config.toml, JSON).

Sandbox-disabling modes are ``danger-full-access`` and ``external-sandbox``.

No exemptions. A test that must exercise the platform's own full-access phase
level builds it from ``CODEX_SANDBOX_FLAGS[PhaseSandbox.FULL_ACCESS]``, the one
typed mapping a phase declaration goes through; that mapping names a level, it
is not an invocation, so it is not one of the forms above.

Scope: every file tracked by THIS repository. Submodules under ``lib/`` are
their own repositories with their own checks and are gitlinks here, so
``git ls-files`` never lists their contents.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]

# Built by concatenation so this file does not match its own scan.
_BYPASS = "dangerously" + r"[-_]bypass[-_]approvals[-_]and[-_]sandbox"
_YOLO = r"(?<![\w-])--" + "yolo" + r"(?![\w-])"
_MODES = r"(?:danger" + r"[-_]full[-_]access|external" + r"[-_]sandbox)"
# Separator between an option and its value: space, '=', ':', quotes, commas,
# newlines (an argv list written one element per line).
_SEP = r"""["']?[\s,=:]*["']?"""

FORMS: dict[str, re.Pattern[str]] = {
    "bypass flag": re.compile(_BYPASS, re.IGNORECASE),
    "yolo alias": re.compile(_YOLO, re.IGNORECASE),
    "--sandbox mode": re.compile(r"--sandbox" + _SEP + _MODES, re.IGNORECASE),
    "-s mode": re.compile(r"(?<![\w-])-s" + _SEP + _MODES, re.IGNORECASE),
    "sandbox_mode setting": re.compile(r"sandbox[-_]mode" + _SEP + _MODES, re.IGNORECASE),
}


def _tracked_files(root: Path) -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    return [root / name for name in listed.split("\0") if name]


def _scan(text: str) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for form, pattern in FORMS.items():
        for match in pattern.finditer(text):
            hits.append((form, text.count("\n", 0, match.start()) + 1))
    return hits


def _violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in _tracked_files(root):
        if not path.is_file():
            continue  # gitlinks (submodules) and deleted-but-unstaged files
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary
        lines = text.splitlines()
        for form, lineno in _scan(text):
            line = lines[lineno - 1].strip()[:120] if lineno <= len(lines) else ""
            found.append(f"{path.relative_to(root)}:{lineno}: [{form}] {line}")
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


_DANGER = "danger" + "-full-access"
_EXTERNAL = "external" + "-sandbox"

#: One planted example per form and spelling; each must be caught on its own.
PLANTED: dict[str, tuple[str, str]] = {
    "bypass flag": ("bypass flag", "codex exec --dangerously" + "-bypass-approvals-and-sandbox x"),
    "bypass config key": (
        "bypass flag",
        "dangerously_" + "bypass_approvals_and_sandbox = true",
    ),
    "bypass env/clap id": ("bypass flag", "DANGEROUSLY_" + "BYPASS_APPROVALS_AND_SANDBOX=1"),
    "yolo alias": ("yolo alias", "codex exec --" + "yolo -C /workspace"),
    "--sandbox space": ("--sandbox mode", f"codex exec --sandbox {_DANGER} x"),
    "--sandbox equals": ("--sandbox mode", f"codex exec --sandbox={_DANGER} x"),
    "--sandbox external": ("--sandbox mode", f"codex exec --sandbox {_EXTERNAL} x"),
    "--sandbox argv list": ("--sandbox mode", f'[\n    "--sandbox",\n    "{_DANGER}",\n]'),
    "-s short": ("-s mode", f"codex exec -s {_DANGER} x"),
    "-s argv list": ("-s mode", f'["codex", "exec", "-s", "{_DANGER}"]'),
    "-c sandbox_mode": ("sandbox_mode setting", f'codex exec -c sandbox_mode="{_DANGER}" x'),
    "-c sandbox_mode quoted": (
        "sandbox_mode setting",
        f"codex exec -c 'sandbox_mode=\"{_EXTERNAL}\"' x",
    ),
    "config.toml": ("sandbox_mode setting", f'sandbox_mode = "{_DANGER}"'),
    "json": ("sandbox_mode setting", f'{{"sandbox_mode": "{_DANGER}"}}'),
}

#: Must stay clean: the sandbox kept on, or unrelated look-alikes.
CLEAN = (
    "syn-delegate codex --prompt=x",
    "codex exec --sandbox workspace-write x",
    "codex exec -s read-only x",
    'sandbox_mode = "workspace-write"',
    "PhaseSandbox.FULL_ACCESS",
    "claude -p --dangerously-skip-permissions",
    "not-so-yolo --yolo-free",
)


@pytest.mark.architecture
@pytest.mark.parametrize("name", sorted(PLANTED))
def test_each_planted_form_is_caught(name: str) -> None:
    form, text = PLANTED[name]
    assert form in {hit for hit, _ in _scan(text)}, name


@pytest.mark.architecture
@pytest.mark.parametrize("text", CLEAN)
def test_sandboxed_invocations_stay_clean(text: str) -> None:
    assert _scan(text) == []


@pytest.mark.architecture
def test_planted_files_fail_the_repository_scan(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for index, name in enumerate(sorted(PLANTED)):
        (tmp_path / f"planted-{index}.txt").write_text(PLANTED[name][1] + "\n")
    (tmp_path / "clean.md").write_text("\n".join(CLEAN) + "\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    flagged = {line.split(":", 1)[0] for line in _violations(tmp_path)}
    assert flagged == {f"planted-{index}.txt" for index in range(len(PLANTED))}
