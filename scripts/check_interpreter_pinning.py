"""Fail when a command this repo runs takes its Python from PATH.

`python3 foo.py` does not name an interpreter. It names whatever the machine's
PATH happens to resolve, which on a GitHub runner is whatever the image ships
this month. The repo requires >=3.12 and pins 3.12 in every `setup-python`
step, so a bare `python3` step passes today for a reason nothing in the repo
states and nothing in the repo protects (#1018, #1242). It breaks on the next
runner image bump, or on a contributor's machine, and the diff that broke it
is not in this repository.

The pinned form is `uv run python`: uv resolves the interpreter from
`pyproject.toml` and provisions it when absent, so the same command means the
same version everywhere.

WHAT COUNTS. A finding is a command whose PROGRAM is `python`, `python3` or
`python3.N` - the first word, after any `VAR=value` assignments, of a command
at the start of a line or after `|`, `;`, `&&`, `(` or `$(`. That single rule
is what separates the cases, and it separates them correctly:

    python3 scripts/x.py                      finding - PATH decides
    curl ... | python3 -m json.tool           finding - PATH decides
    $(python3 -c "import tomllib; ...")       finding - PATH decides, and
                                              tomllib needs >= 3.11
    uv run python scripts/x.py                fine - the program is `uv`
    docker run --rm img python3 --version     fine - the program is `docker`;
                                              the interpreter belongs to a
                                              pinned image, not to this machine
    docker compose exec api python -c "..."   fine - same reason

So delegation to a container is not a special case that had to be written
down. It falls out of asking which program the machine is being asked to run.

WHAT IS IN SCOPE. The justfile and `.github` (workflows and composite
actions): the command files that run against an already-provisioned toolchain.
Deliberately NOT `infra/scripts/bootstrap.sh`, which probes bare `python3` to
decide whether to install one - it runs before a pinned interpreter exists, so
the pinned form is not available to it and the bare call is the correct code.

WHY THERE IS AN ALLOWLIST. Six of the findings live under `.github/`, which
the GitHub App that opens automated PRs cannot write to. They are recorded
below with the exact replacement, and this gate proves the list stays honest
in both directions: a NEW unpinned call fails here, and an allowlisted one
that someone has since fixed fails here too, as a stale entry. Applying the
diff in #1242 and deleting the entry are therefore one change, not two, and
forgetting the second half is not a silent no-op.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

#: The invocation every command file must use.
PINNED_FORM: Final = "uv run python"

#: Unpinned calls that cannot be fixed from this repository's automated PRs,
#: keyed by "<repo-relative path>::<command>" and valued with the replacement.
#: Every one of these is #1242, waiting on a human to apply the diff in the
#: issue; `.github/**` is unwritable to an App token without `workflows`
#: permission. An entry that no longer matches a finding is an ERROR, not a
#: no-op - see the module docstring.
BLOCKED_ON_A_HUMAN: Final[dict[str, str]] = {
    ".github/workflows/_check-version.yml::python3 scripts/workflows/bump_version.py --check": (
        "uv run python scripts/workflows/bump_version.py --check "
        "(#1242: the job needs an astral-sh/setup-uv step first)"
    ),
    ".github/workflows/_check-version.yml::"
    "python3 scripts/workflows/bump_version.py --check-release": (
        "uv run python scripts/workflows/bump_version.py --check-release "
        "(#1242: the job needs an astral-sh/setup-uv step first)"
    ),
    ".github/workflows/_check-version.yml::"
    "python3 -c \"import tomllib;print(tomllib.load(open('pyproject.toml','rb'))"
    "['project']['version'])\")": (
        "uv run python -c ... (#1242: tomllib is 3.11+, so this step does not "
        "merely prefer the pinned interpreter, it requires one)"
    ),
    ".github/workflows/_check-codegen-sync.yml::"
    "python3 scripts/workflows/check_drift.py apps/syn-cli-node/src/generated/ "
    "apps/syn-docs/content/docs/cli/ apps/syn-docs/content/docs/api/ "
    "apps/syn-docs/openapi.json": (
        "uv run python scripts/workflows/check_drift.py ... "
        "(#1242: the job already has astral-sh/setup-uv and does not use it here)"
    ),
    ".github/workflows/release-beta.yaml::"
    "python3 -c \"import tomllib;print(tomllib.load(open('pyproject.toml','rb'))"
    "['project']['version'])\")": (
        "uv run python -c ... (#1242: tomllib is 3.11+; the guard job has no "
        "Python setup step at all)"
    ),
    '.github/workflows/smoke-test.yml::python3 -c "': (
        "uv run python -c ... (#1242: parses `docker compose config` output on "
        "the RUNNER, not in a container)"
    ),
    ".github/actions/setup-vsa/action.yml::"
    'python3 -c \'import json,sys; print(next(p["version"] for p in '
    'json.load(sys.stdin)["packages"] if p["name"]=="vsa-cli"))\')': (
        "uv run python -c ... (#1242: stdlib-only today, so this one is the "
        "cheapest to leave and the cheapest to fix)"
    ),
}


@dataclass(frozen=True)
class Finding:
    """One command that resolves its interpreter from PATH."""

    path: str
    """Repo-relative file the command lives in."""

    line: int
    """1-based line the command starts on, for `file:line` navigation."""

    command: str
    """The command from the interpreter onward, as written."""

    @property
    def key(self) -> str:
        """The allowlist key. Stable across line moves, unlike `file:line`."""
        return f"{self.path}::{self.command}"


#: A command boundary, optional `VAR=value` assignments, then the program.
#: `(?=\s|$)` keeps `python-version:` and `event-sourcing-python` out: those
#: are words containing "python", not requests to run one.
_BARE_INTERPRETER: Final = re.compile(
    r"""
    (?: ^ | [|;&(`] )                       # start of a command
    (?: \s* [A-Za-z_][A-Za-z0-9_]* = \S* )* # VAR=value prefixes
    \s*
    (?P<program> python (?: 3 (?: \.\d+ )? )? )
    (?= \s | $ )
    """,
    re.MULTILINE | re.VERBOSE,
)


def _logical_lines(script: str) -> Iterator[tuple[int, str]]:
    """Backslash continuations joined, comments dropped, 1-based line numbers.

    Joining first is what stops `... api \\` / `python /app/seed.py` from
    reading as a bare invocation when it is an argument to `docker compose
    run`. Comment lines are dropped because a commented-out command is not one.
    """
    physical = script.splitlines()
    index = 0
    while index < len(physical):
        start = index
        parts = [physical[index]]
        while parts[-1].rstrip().endswith("\\") and index + 1 < len(physical):
            index += 1
            parts[-1] = parts[-1].rstrip().removesuffix("\\")
            parts.append(physical[index])
        index += 1
        joined = " ".join(part.strip() for part in parts).strip()
        # `@` and `-` prefix a just recipe line; `#!` is a shebang, not a comment.
        joined = joined.lstrip("@-").strip() if not joined.startswith("#!") else joined
        if joined.startswith("#"):
            continue
        yield start + 1, joined


def unpinned_commands(script: str) -> Iterator[tuple[int, str]]:
    """Every command in one shell script whose program is a bare interpreter.

    The single public rule, applied to text: line offset within `script`, and
    the command as written from the interpreter onward.
    """
    for offset, line in _logical_lines(script):
        for match in _BARE_INTERPRETER.finditer(line):
            yield offset, line[match.start("program") :].strip()


def _run_blocks(document: str) -> Iterator[tuple[int, str]]:
    """Every `run:` body in a workflow or composite action, with its line.

    Parsed rather than grepped so a `name:` or a comment that mentions python
    cannot be mistaken for a step that runs it. `yaml.compose` is used instead
    of `safe_load` because only the node tree carries source marks, and a
    finding without a line number is a finding nobody can act on.
    """
    root = yaml.compose(document)
    stack = [root]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if getattr(key, "value", None) == "run" and isinstance(value, yaml.ScalarNode):
                    # A block scalar's mark is the `|` line; the body starts on
                    # the next one. A plain scalar's mark is the body itself.
                    body_starts_below = value.style in ("|", ">")
                    yield value.start_mark.line + 1 + body_starts_below, value.value
                stack.append(value)
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)


def _command_files(root: Path) -> Iterator[Path]:
    """The files in scope: the justfile, workflows, and composite actions."""
    justfile = root / "justfile"
    if justfile.exists():
        yield justfile
    github = root / ".github"
    yield from sorted(github.glob("workflows/*.y*ml"))
    yield from sorted(github.glob("actions/*/action.y*ml"))


def scan(root: Path) -> list[Finding]:
    """Every command in the repo that resolves Python from PATH."""
    findings: list[Finding] = []
    for path in _command_files(root):
        relative = path.relative_to(root).as_posix()
        text = path.read_text()
        blocks = [(0, text)] if path.name == "justfile" else list(_run_blocks(text))
        for start, script in blocks:
            findings.extend(
                Finding(relative, start + offset - 1 if start else offset, command)
                for offset, command in unpinned_commands(script)
            )
    # Source order, not the order the YAML node tree happened to unwind in: a
    # gate is read as a worklist, top to bottom.
    return sorted(findings, key=lambda finding: (finding.path, finding.line))


def problems(findings: list[Finding]) -> list[str]:
    """What a human has to change, in both directions.

    New unpinned calls, and allowlist entries whose finding is gone. The second
    is the half that keeps the first honest: without it the list would outlive
    the workflow fix and quietly grant a permanent exemption.
    """
    found = {finding.key: finding for finding in findings}
    reported = [
        f"{finding.path}:{finding.line} runs `{finding.command}`, so PATH picks "
        f"the interpreter. Use `{PINNED_FORM}`."
        for finding in findings
        if finding.key not in BLOCKED_ON_A_HUMAN
    ]
    reported.extend(
        f"{key} is allowlisted in scripts/check_interpreter_pinning.py but no "
        f"longer exists. If you applied the #1242 workflow diff, delete the entry."
        for key in sorted(BLOCKED_ON_A_HUMAN)
        if key not in found
    )
    return reported


def main() -> int:
    findings = scan(REPO_ROOT)
    reported = problems(findings)
    if reported:
        print("❌ Python is being taken from PATH instead of the pinned interpreter:")
        for problem in reported:
            print(f"   - {problem}")
        return 1
    print(
        f"✅ interpreter pinning: every Python call in the justfile and .github "
        f"uses `{PINNED_FORM}`, except {len(BLOCKED_ON_A_HUMAN)} under .github/ "
        f"that an App token cannot rewrite (#1242):"
    )
    for key, fix in sorted(BLOCKED_ON_A_HUMAN.items()):
        path, _, command = key.partition("::")
        print(f"    {path}\n      {command}\n      -> {fix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
