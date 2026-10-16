"""Ratchet: tests that no CI job selects, and disarmed (xfail) guards.

CI runs ``pytest -m unit``, so an unmarked test is collected by nothing and can
fail on main indefinitely behind a green check. ``ci/fitness`` is selected
separately, by ``-m architecture``, and is censused separately (#1935). Budgets live in
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

#: The only two pytest exit statuses this gate can read a census from. 0 is a
#: completed collection; 5 is "no tests collected", which a marker filter
#: reaches legitimately once nothing is left to select. Every other status
#: means the run stopped early - notably 2 (Interrupted), which is what a
#: single import error produces - and its summary line undercounts.
_EXIT_OK = 0
_EXIT_NO_TESTS_COLLECTED = 5
_COLLECTED_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+) tests collected")
_COLLECTED_FALLBACK = re.compile(r"(\d+) tests collected")

#: The markers CI selects on: ``pytest -m unit`` and ``pytest -m integration``
#: in ``.github/workflows/ci.yml``. No job runs ``-m e2e``, so ``e2e`` is a
#: label, not a selector - excluding it here once hid 11 tests that ran nowhere
#: (#1428). Add a marker only when a CI job starts selecting it.
CI_SELECTED_MARKERS: tuple[str, ...] = ("unit", "integration")

#: Every test no CI job selects, derived from the selectors above so the two
#: cannot drift apart.
UNMARKED_SELECTOR = " and ".join(f"not {marker}" for marker in CI_SELECTED_MARKERS)

#: ``ci/fitness`` is not a testpath: the Architectural Fitness job reaches it
#: by explicit path, ``pytest ci/fitness/ -m architecture`` (justfile
#: ``fitness-invariants``), and the unit job never sees it. The census above
#: walks testpaths only, so a fitness module marked ``unit`` was invisible to
#: it AND to both jobs: 21 tests, one of them red on main behind a green check
#: (#1935). ``scripts/tests/test_check_test_markers.py`` pins both values to
#: the recipe so they cannot drift from what CI runs.
FITNESS_DIR = "ci/fitness"
FITNESS_SELECTED_MARKER = "architecture"
FITNESS_UNSELECTED_SELECTOR = f"not {FITNESS_SELECTED_MARKER}"


#: The repository this gate guards, for reading its ``.gitmodules``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_GITMODULES_PATH = re.compile(r"^[ \t]*path[ \t]*=[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)


def submodule_paths(root: Path) -> tuple[str, ...]:
    """Every submodule path ``root/.gitmodules`` declares, as posix strings.

    Submodules are other repositories, governed by their own CI and their own
    budgets. Derived from ``.gitmodules`` rather than listed, so a new
    submodule is excluded without anyone remembering to add it: the AW pin to
    be32a683 brought one xfail from AW's own conformance tests and failed this
    gate over a test in another repo (#1992). No file means no submodules.
    """
    gitmodules = root / ".gitmodules"
    if not gitmodules.is_file():
        return ()
    text = gitmodules.read_text(errors="ignore")
    return tuple(m.strip("/") for m in _GITMODULES_PATH.findall(text))


#: This repository's submodules, the default for ``is_excluded``.
SUBMODULE_PATHS: tuple[str, ...] = submodule_paths(_REPO_ROOT)


def is_excluded(path: Path | str, submodules: tuple[str, ...] = SUBMODULE_PATHS) -> bool:
    """True when a path lies under a directory that is not first-party source.

    Matches whole DIRECTORY components, never substrings and never the file
    name: a substring test excluded ``scripts/test_node_modules_policy.py``,
    so a first-party test escaped every guard that shares this function.
    Uses ``as_posix`` so the check behaves identically on Windows separators.

    ``submodules`` are matched as a prefix of a repo-relative ``path`` only:
    ``lib/agentic-workspace`` is a submodule at the root, while a directory
    of that name elsewhere is first-party and still counted.
    """
    parts = Path(path).as_posix().split("/")
    directories = parts[:-1]
    for fragment in EXCLUDED_PATH_FRAGMENTS:
        wanted = fragment.split("/")
        width = len(wanted)
        if any(
            directories[start : start + width] == wanted
            for start in range(len(directories) - width + 1)
        ):
            return True
    for submodule in submodules:
        wanted = submodule.split("/")
        if directories[: len(wanted)] == wanted:
            return True
    return False


def iter_test_files(root: Path) -> list[Path]:
    """Every first-party ``test_*.py`` under ``root``; worktrees and submodules excluded."""
    submodules = submodule_paths(root)
    return sorted(
        p for p in root.rglob("test_*.py") if not is_excluded(p.relative_to(root), submodules)
    )


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


def _tail(output: str, limit: int = 2000) -> str:
    """The last of a captured stream, blank when there was nothing to say."""
    return f"\n{output[-limit:]}" if output.strip() else ""


def collect_census(*args: str) -> int:
    """How many tests pytest can actually collect, or a refusal to guess.

    The exit status decides whether the summary line means anything; the text
    only supplies the number. That order matters, because a run that dies
    halfway through collection still prints a summary, and the count in it is
    short by exactly the tests that failed to import. On a ratchet a smaller
    number reads as progress, so the gate would announce an improvement caused
    by tests disappearing - failing in the reassuring direction, which is the
    one nobody investigates.

    Exit 5 is not a failure here. It is pytest's way of saying a filter matched
    nothing, which is the goal state of the unmarked ratchet, so it is the one
    exit status that is itself the answer: a census of zero.

    Raises:
        SystemExit: pytest did not finish collecting, so there is no census to
            report. Carries pytest's own output, which is where the reason is.
    """
    # No -q: the "N/M tests collected" summary is only emitted without it.
    result = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == _EXIT_NO_TESTS_COLLECTED:
        return 0
    if result.returncode != _EXIT_OK:
        # stdout, not just stderr: pytest reports collection errors on stdout,
        # so a stderr-only diagnostic is usually empty at the exact moment the
        # operator needs to know which module failed to import.
        raise SystemExit(
            f"pytest collection failed (exit {result.returncode}); refusing to"
            " report a census that may be short. A collection break makes the"
            " count go DOWN, which on a ratchet is indistinguishable from"
            f" progress.\n{_tail(result.stdout)}{_tail(result.stderr)}"
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


def fitness_budget(unselected: int) -> Budget:
    """The ci/fitness census. Zero-tolerance with no config entry on purpose.

    A budget in ``fitness-exceptions.toml`` would be a dial for running fewer
    architectural checks than are written, and there is no ratchet to walk
    down: the fix for every count is one marker.
    """
    return Budget(name="fitness-unselected", actual=unselected, allowed=0, issue="#1935")


def main() -> int:
    root = Path.cwd()
    config = tomllib.loads(Path("fitness-exceptions.toml").read_text()).get("test-markers", {})

    total = collect_census()
    unmarked = collect_census("-m", UNMARKED_SELECTOR)
    xfails = count_xfail_markers(root)
    fitness_unselected = collect_census(FITNESS_DIR, "-m", FITNESS_UNSELECTED_SELECTOR)

    budgets = [*evaluate(config, unmarked, xfails), fitness_budget(fitness_unselected)]
    for budget in budgets:
        print(budget.render())
    print(f"  census: {total} tests collected, {unmarked} selected by no CI job")
    print(
        f"  census: {fitness_unselected} tests under {FITNESS_DIR} not marked"
        f" {FITNESS_SELECTED_MARKER}, so the fitness job skips them"
    )

    if any(b.exceeded for b in budgets):
        print(
            "\nA test no job runs is not coverage. Mark it, or lower the budget"
            " in fitness-exceptions.toml only when the count went DOWN. A"
            f" {FITNESS_DIR} test has no budget: mark it {FITNESS_SELECTED_MARKER}."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
