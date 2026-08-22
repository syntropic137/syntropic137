"""Ratchet: tests that no CI job selects, and disarmed (xfail) guards.

CI runs ``pytest -m unit``, so an unmarked test is collected by nothing and can
fail on main indefinitely behind a green check. Budgets live in
``fitness-exceptions.toml`` under ``[test-markers.*]``; both must ratchet to 0.

See docs/retrospectives/2026-08-17-green-checks-that-check-nothing.md

WHY THIS IS A MODULE AND NOT INLINE IN THE JUSTFILE. It used to be a heredoc
inside ``just check-test-markers``, which meant it could not be tested. It then
shipped a false positive: it globbed ``test_*.py`` from the repo root, and
``.claude/worktrees/`` holds full repo copies, so two agent worktrees made it
count the same two xfail markers three times and fail the build over four that
did not exist.

A gate that cries wolf gets muted, which is the exact failure this gate exists
to prevent. An untestable gate is a code smell regardless of whether it is
currently correct, so the logic lives here and
``scripts/tests/test_check_test_markers.py`` pins it.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

#: Directory fragments that never contain first-party tests. ``.claude/worktrees``
#: is the one that caused the false positive: agent worktrees are complete repo
#: copies, so every file in them is a duplicate of a file already counted.
EXCLUDED_PATH_FRAGMENTS: tuple[str, ...] = (
    ".venv",
    ".claude/worktrees",
    "node_modules",
    "site-packages",
)

#: Anchored to the start of a line (indentation allowed) because a decorator
#: always occupies its own line. An unanchored pattern also matched the marker
#: as it appears INSIDE a string literal - which made this gate count its own
#: regression-test fixtures and report three xfails that were not real. A gate
#: that counts its own tests is the same false-positive smell one level down.
_XFAIL_PATTERN = re.compile(r"^[ \t]*@pytest\.mark\.xfail", re.MULTILINE)
_COLLECTED_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+) tests collected")
_COLLECTED_FALLBACK = re.compile(r"(\d+) tests collected")


def is_excluded(path: Path | str) -> bool:
    """True when a path lies under a directory that is not first-party source.

    Uses ``as_posix`` so the check behaves identically on Windows separators.
    """
    text = Path(path).as_posix()
    return any(fragment in text for fragment in EXCLUDED_PATH_FRAGMENTS)


def iter_test_files(root: Path) -> list[Path]:
    """Every first-party ``test_*.py`` under ``root``, worktrees excluded."""
    return sorted(p for p in root.rglob("test_*.py") if not is_excluded(p))


def count_xfail_markers(root: Path) -> int:
    """Count ``@pytest.mark.xfail`` decorators across first-party tests.

    Each disarmed guard is counted once. Files that cannot be decoded are
    skipped rather than crashing the gate - a gate that dies on a stray binary
    is a gate that gets removed.
    """
    return sum(
        len(_XFAIL_PATTERN.findall(path.read_text(errors="ignore")))
        for path in iter_test_files(root)
    )


def parse_collected(output: str) -> int:
    """Extract the collected-test count from pytest's summary line.

    Handles both ``N/M tests collected (K deselected)`` and the bare
    ``N tests collected`` form emitted when nothing is deselected.
    """
    match = _COLLECTED_PATTERN.search(output)
    if match:
        return int(match.group(1))
    fallback = _COLLECTED_FALLBACK.search(output)
    if fallback:
        return int(fallback.group(1))
    msg = "could not parse pytest collection output"
    raise ValueError(msg)


def _collect(*args: str) -> int:
    # No -q: the "N/M tests collected" summary is only emitted without it.
    result = subprocess.run(  # noqa: S603
        ["uv", "run", "pytest", "--collect-only", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return parse_collected(result.stdout)


@dataclass(frozen=True)
class Budget:
    """A ratchet entry: an actual count measured against its allowance."""

    name: str
    actual: int
    allowed: int
    issue: str

    @property
    def exceeded(self) -> bool:
        return self.actual > self.allowed

    def render(self) -> str:
        if self.exceeded:
            return f"  FAIL {self.name}: {self.actual} (budget {self.allowed}) [{self.issue}]"
        if self.allowed > 0:
            return f"  WARN {self.name}: {self.actual}/{self.allowed} - ratchet to 0 [{self.issue}]"
        return f"  ok {self.name}: clean"


def evaluate(config: dict[str, dict[str, object]], unmarked: int, xfails: int) -> list[Budget]:
    """Pair measured counts with their configured budgets."""
    budgets: list[Budget] = []
    for name, actual in (("unmarked", unmarked), ("xfail", xfails)):
        entry = config.get(name, {})
        allowed = int(entry.get("value", 0) or 0)
        issue = str(entry.get("issue", ""))
        budgets.append(Budget(name=name, actual=actual, allowed=allowed, issue=issue))
    return budgets


def main() -> int:
    root = Path.cwd()
    config = tomllib.loads(Path("fitness-exceptions.toml").read_text()).get("test-markers", {})

    total = _collect()
    unmarked = _collect("-m", "not unit and not integration and not e2e")
    xfails = count_xfail_markers(root)

    budgets = evaluate(config, unmarked, xfails)
    for budget in budgets:
        print(budget.render())
    print(f"  census: {total} tests collected, {unmarked} selected by no CI job")

    if any(b.exceeded for b in budgets):
        print(
            "\nA test no job runs is not coverage. Mark it, or lower the budget"
            " in fitness-exceptions.toml only when the count went DOWN."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
