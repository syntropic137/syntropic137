#!/usr/bin/env python3
"""Check, admit and score the IMPLEMENTER eval kind (research #1725).

An implementer case is a real merged fix turned back into a task. The agent
gets the tree just before the fix (``commit``, the merge's first parent) and
the issue's statement of the problem, with the fix's own description of the
solution removed. The tests the fix PR added or changed are HIDDEN: they are
not in the agent's checkout at ``commit``, and they are what scores it.

    uv run python scripts/eval_implementer.py check [--suite DIR]
    uv run python scripts/eval_implementer.py admit [--suite DIR] [--case ID]
    uv run python scripts/eval_implementer.py score --case ID --patch FILE [--suite DIR]

SCORE. ``score`` builds a throwaway git worktree at the case's pin, applies the
agent's patch, writes each hidden test file as it stands at ``fix_commit``
(over anything the patch did to that path: the hidden tests are the judge, not
the agent's copy of them) and runs pytest on those files and nothing else.

PASS is not pytest's exit 0. Exit 0 also covers a test that was skipped,
xfailed or deselected, so an agent's conftest that skips the hidden tests would
earn it. The intended hidden tests are the node ids pytest collects from the
hidden files at ``fix_commit``, before any agent code exists; a recording
plugin outside the tree reports how each one ended on the change, and every one
of them must have run and passed. Every ``conftest.py`` the patch touches is
also put back as it stands at ``fix_commit``: like the hidden tests, the test
fixtures are the judge's.

    PASS   every intended hidden test ran and passed on the agent's change
    FAIL   the patch does not apply, a hidden test failed, or one was skipped,
           xfailed, deselected or never reported
    ERROR  the environment failed: the pin or a hidden file is missing, uv or
           pytest could not run, no test was collected, or the run timed out

ERROR is never the agent's fault and never counts as a FAIL. Exit status: 0
PASS, 1 FAIL, 2 ERROR.

ADMISSION. A case belongs in the suite only if its hidden tests discriminate:
``admit`` scores the empty patch (must FAIL: the tests catch the bug at the
pin) and the fix's own non-test diff (must PASS: the tests are satisfiable).
A case that does not hold both is not a case. ``check`` is the offline,
git-only half: shapes, SHAs, ancestry, hidden files present at the fix and the
task not naming the fix's PR.

WHERE IT RUNS. ``score`` runs the agent's code, so it belongs in a workspace,
never on the API host. It needs only git, uv and the repository. See
``evals/implementer-seed-v1/README.md`` for how a patch gets there and for the
leakage the platform does not yet prevent.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from eval_suite import ROOT, DefinitionError, Suite, _read_yaml, _workflow_problems
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

if TYPE_CHECKING:
    from collections.abc import Iterator

DEFAULT_SUITE = ROOT / "evals" / "implementer-seed-v1"
TEST_TIMEOUT_SECONDS = 300
SYNC_TIMEOUT_SECONDS = 900
SYNC = ("uv", "sync", "--frozen", "--quiet")
PYTEST = ("uv", "run", "--frozen", "--no-sync", "pytest")
"""How the environment is built and pytest run in a tree. Module-level so a test can point
them at a tiny repository's interpreter and still go through the real worktree and pytest."""

_RECORDER = "syn_eval_hidden_outcomes"
_RECORDER_SOURCE = '''\
"""Loaded by scripts/eval_implementer.py from outside the tree: how each hidden test ended."""
import json
import os

_ended = {}


def pytest_collection_finish(session):
    _ended["collected"] = [item.nodeid for item in session.items]


def pytest_runtest_logreport(report):
    phases = _ended.setdefault("outcomes", {}).setdefault(report.nodeid, {})
    phases[report.when] = "xfail" if hasattr(report, "wasxfail") else report.outcome


def pytest_sessionfinish(session):
    with open(os.environ["SYN_EVAL_OUTCOMES"], "w") as out:
        json.dump(_ended, out)
'''

Outcome = Literal["PASS", "FAIL", "ERROR"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ImplementerCase(_Frozen):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    source_pr: int = Field(ge=1)
    """The PR that shipped the fix. Never put it in `task`: the agent could fetch it."""
    source_issue: int | None = Field(default=None, ge=1)
    """The issue the task's text is taken from, when there is one."""
    commit: str
    """Full SHA the agent's workspace is pinned to: `fix_commit`'s first parent."""
    fix_commit: str
    """Full SHA of the merge that shipped the fix. The hidden tests are read from here."""
    task: str = Field(min_length=1)
    """The problem as the issue states it, with the fix's description of the solution removed."""
    hidden_tests: tuple[str, ...] = Field(min_length=1)
    """Repo-relative pytest files the fix PR added or changed, run at their `fix_commit` content."""

    @field_validator("commit", "fix_commit")
    @classmethod
    def _full_sha(cls, value: str) -> str:
        if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"{value!r} is not a full 40-character lowercase SHA")
        return value


class ImplementerSuite(_Frozen):
    suite: Suite
    cases: tuple[ImplementerCase, ...]

    def case(self, case_id: str) -> ImplementerCase:
        for case in self.cases:
            if case.id == case_id:
                return case
        raise DefinitionError(f"no case {case_id!r}; the suite holds {[c.id for c in self.cases]}")


class _Recorded(_Frozen):
    collected: tuple[str, ...] = ()
    outcomes: dict[str, dict[str, str]] = Field(default_factory=dict)
    """node id -> {setup|call|teardown: passed|failed|skipped|xfail}, as pytest reported them."""


class TestRun(_Frozen):
    outcome: Outcome
    detail: str
    """Why: the failing step, or the tail of pytest's output."""


def load_suite(directory: Path, root: Path = ROOT) -> ImplementerSuite:
    """Parse a suite and check it against its workflow file. Raises `DefinitionError`."""
    try:
        suite = Suite.model_validate(_read_yaml(directory / "suite.yaml"))
        case_files = sorted((directory / "cases").glob("*.yaml"))
        cases = tuple(ImplementerCase.model_validate(_read_yaml(p)) for p in case_files)
    except (OSError, ValidationError, yaml.YAMLError) as exc:
        raise DefinitionError(str(exc)) from exc

    problems: list[str] = []
    if not cases:
        problems.append(f"{directory}/cases holds no case")
    for path, case in zip(case_files, cases, strict=True):
        if path.stem != case.id:
            problems.append(f"{path.name}: file name must be the case id {case.id!r}")
        if f"#{case.source_pr}" in case.task:
            problems.append(
                f"{case.id}: task names #{case.source_pr}; the agent could fetch the fix"
            )
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        problems.append(f"duplicate case ids: {sorted(ids)}")
    for ref in suite.workflows:
        problems.extend(_workflow_problems(ref, root))
    if problems:
        raise DefinitionError("\n".join(problems))
    return ImplementerSuite(suite=suite, cases=cases)


def _git(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, input=stdin
    )


def check_commits(loaded: ImplementerSuite, repo: Path) -> list[str]:
    """What git says is wrong with each case: missing SHAs, wrong parent, absent tests."""
    problems: list[str] = []
    for case in loaded.cases:
        missing = [
            sha
            for sha in (case.commit, case.fix_commit)
            if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0
        ]
        if missing:
            problems.append(f"{case.id}: commit(s) {missing} not in {repo}")
            continue
        parent = _git(repo, "rev-parse", f"{case.fix_commit}^1").stdout.strip()
        if parent != case.commit:
            problems.append(f"{case.id}: commit is not fix_commit's first parent ({parent})")
        for path in case.hidden_tests:
            if _git(repo, "cat-file", "-e", f"{case.fix_commit}:{path}").returncode != 0:
                problems.append(f"{case.id}: hidden test {path} is not in fix_commit")
    return problems


def fix_patch(case: ImplementerCase, repo: Path) -> str:
    """The fix's own change without its hidden tests: the reference solution."""
    excluded = [f":(exclude){path}" for path in case.hidden_tests]
    return _git(repo, "diff", "--binary", case.commit, case.fix_commit, "--", ".", *excluded).stdout


@contextmanager
def _worktree(repo: Path, sha: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="implementer-eval-") as tmp:
        tree = Path(tmp) / "tree"
        added = _git(repo, "worktree", "add", "--detach", "--quiet", str(tree), sha)
        if added.returncode != 0:
            raise _EnvironmentFailure(f"git worktree add {sha}: {added.stderr.strip()}")
        try:
            _check_out_submodules(repo, tree)
            yield tree
        finally:
            _git(repo, "worktree", "remove", "--force", str(tree))


def _check_out_submodules(repo: Path, tree: Path) -> None:
    """Check out each submodule at the commit the pin records, from `repo`'s own clone of it.

    Never from the network: the environment has nothing to fetch, and a
    submodule commit the local clone lacks is an ERROR, not something to go
    and get.
    """
    paths = _git(tree, "config", "--file", ".gitmodules", "--get-regexp", r"submodule\..*\.path")
    for line in paths.stdout.splitlines():
        key, path = line.split(maxsplit=1)
        name = key.removeprefix("submodule.").removesuffix(".path")
        _git(tree, "config", f"submodule.{name}.url", str((repo / path).resolve()))
    updated = _git(
        tree, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "--quiet"
    )
    if updated.returncode != 0:
        raise _EnvironmentFailure(f"submodules at the pin: {updated.stderr.strip()}")


class _EnvironmentFailure(Exception):
    """Something other than the agent's change stopped the run: always ERROR."""


def score_patch(case: ImplementerCase, patch: str, repo: Path) -> TestRun:
    """Apply `patch` at the case's pin, restore the hidden tests and run only them."""
    try:
        expected = _intended_hidden_tests(case, repo)
        with _worktree(repo, case.commit) as tree:
            # The environment is built from the pin, before the patch: a failure
            # here is the environment's, and the agent's change cannot cause it.
            _run(tree, list(SYNC), "uv sync at the pin")
            if patch.strip():
                applied = _git(tree, "apply", "--whitespace=nowarn", "-", stdin=patch)
                if applied.returncode != 0:
                    return TestRun(
                        outcome="FAIL", detail=f"patch does not apply: {applied.stderr.strip()}"
                    )
            judged = {p for p in _patched_paths(tree, patch) if Path(p).name == "conftest.py"}
            for path in sorted(judged | set(case.hidden_tests)):
                _restore_from_fix(repo, tree, case.fix_commit, path)
            return _run_hidden_tests(tree, case.hidden_tests, expected)
    except _EnvironmentFailure as exc:
        return TestRun(outcome="ERROR", detail=str(exc))


def _intended_hidden_tests(case: ImplementerCase, repo: Path) -> tuple[str, ...]:
    """The node ids the hidden files hold, collected at `fix_commit` where no agent code exists."""
    with _worktree(repo, case.fix_commit) as tree:
        _run(tree, list(SYNC), "uv sync at the fix")
        try:
            ran, recorded = _pytest(tree, ["--collect-only", "-n", "0", *case.hidden_tests])
        except subprocess.TimeoutExpired as exc:
            raise _EnvironmentFailure(f"collecting the hidden tests at the fix: {exc}") from exc
    if ran.returncode != 0 or recorded is None or not recorded.collected:
        tail = "\n".join((ran.stderr + ran.stdout).strip().splitlines()[-15:])
        raise _EnvironmentFailure(
            f"collecting the hidden tests at the fix: exit {ran.returncode}\n{tail}"
        )
    return recorded.collected


def _patched_paths(tree: Path, patch: str) -> list[str]:
    """Every path the patch names, both sides of a rename, as git apply reads it."""
    if not patch.strip():
        return []
    listed = _git(tree, "apply", "--numstat", "-z", "-", stdin=patch).stdout
    fields = listed.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(fields) - 1:
        _, _, path = fields[i].split("\t", 2)
        if path:
            paths.append(path)
            i += 1
        else:
            paths += fields[i + 1 : i + 3]
            i += 3
    return paths


def _restore_from_fix(repo: Path, tree: Path, fix_commit: str, path: str) -> None:
    """Make `path` in `tree` what it is at `fix_commit`, absent if the fix has no such file."""
    target = tree / path
    if _git(repo, "cat-file", "-e", f"{fix_commit}:{path}").returncode != 0:
        if path.endswith("conftest.py"):
            target.unlink(missing_ok=True)
            return
        raise _EnvironmentFailure(f"hidden test {path} is not in {fix_commit}")
    shown = subprocess.run(
        ["git", "-C", str(repo), "show", f"{fix_commit}:{path}"], capture_output=True
    )
    if shown.returncode != 0:
        raise _EnvironmentFailure(f"{path} at the fix: {shown.stderr.decode().strip()}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(shown.stdout)


def _pytest(
    tree: Path, args: list[str]
) -> tuple[subprocess.CompletedProcess[str], _Recorded | None]:
    """Run pytest in `tree` with the recorder loaded from outside it. Raises `TimeoutExpired`."""
    with tempfile.TemporaryDirectory(prefix="implementer-recorder-") as tmp:
        (Path(tmp) / f"{_RECORDER}.py").write_text(_RECORDER_SOURCE)
        record = Path(tmp) / "outcomes.json"
        env = dict(os.environ, SYN_EVAL_OUTCOMES=str(record))
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [tmp, env.get("PYTHONPATH")]))
        command = [*PYTEST, "-q", "-p", "no:cacheprovider", "-p", _RECORDER, *args]
        try:
            ran = subprocess.run(
                command,
                cwd=tree,
                capture_output=True,
                text=True,
                env=env,
                timeout=TEST_TIMEOUT_SECONDS,
            )
        except OSError as exc:
            raise _EnvironmentFailure(f"{' '.join(command)}: {exc}") from exc
        try:
            recorded = _Recorded.model_validate(json.loads(record.read_text()))
        except (OSError, ValueError):
            recorded = None
    return ran, recorded


def _run_hidden_tests(tree: Path, tests: tuple[str, ...], expected: tuple[str, ...]) -> TestRun:
    try:
        ran, recorded = _pytest(tree, ["-n", "0", *tests])
    except subprocess.TimeoutExpired:
        # The environment is already built, so a hang is in the code under
        # test: the pin's (the case is not admitted) or the change's.
        return TestRun(outcome="FAIL", detail=f"hidden tests ran past {TEST_TIMEOUT_SECONDS}s")
    tail = "\n".join((ran.stderr + ran.stdout).strip().splitlines()[-15:])
    detail = f"pytest exit {ran.returncode}\n{tail}"
    outcome = _outcome_of(ran.returncode)
    if outcome != "PASS":
        return TestRun(outcome=outcome, detail=detail)
    unproven = _not_passed(expected, recorded)
    if unproven:
        listed = "\n".join(f"  {nodeid}: {how}" for nodeid, how in unproven)
        return TestRun(
            outcome="FAIL",
            detail=f"{len(unproven)} of {len(expected)} hidden tests did not run and pass:\n{listed}\n{detail}",
        )
    return TestRun(outcome="PASS", detail=detail)


def _not_passed(expected: tuple[str, ...], recorded: _Recorded | None) -> list[tuple[str, str]]:
    """Each intended hidden test without proof that it ran and passed, and how it ended instead.

    Proof is a `call` phase that passed with every phase passing and no xfail
    marker. Anything else (skipped, xfailed, xpassed, deselected, never
    reported, no record at all) is not a pass, whatever pytest exited with.
    """
    if recorded is None:
        return [(nodeid, "no outcome was recorded: pytest did not finish") for nodeid in expected]
    missing: list[tuple[str, str]] = []
    for nodeid in expected:
        phases = recorded.outcomes.get(nodeid)
        if not phases:
            how = "collected but not run" if nodeid in recorded.collected else "not collected"
            missing.append((nodeid, how))
        elif phases.get("call") != "passed" or any(o != "passed" for o in phases.values()):
            missing.append((nodeid, ", ".join(f"{w} {o}" for w, o in phases.items())))
    return missing


def _outcome_of(pytest_exit: int) -> Outcome:
    """pytest's exit code as a verdict on the change.

    0 every test passed. 1 a test failed. 2 a hidden test could not be
    collected: with the environment already built at the pin, that is the
    change failing to provide what the tests import, so it is the agent's.
    3 (internal error), 4 (usage) and 5 (nothing collected) say nothing about
    the change.
    """
    if pytest_exit == 0:
        return "PASS"
    if pytest_exit in (1, 2):
        return "FAIL"
    return "ERROR"


def _run(tree: Path, command: list[str], step: str) -> None:
    """Run a setup `step` in `tree`. Any failure, timeout included, is the environment's."""
    try:
        ran = subprocess.run(
            command, cwd=tree, capture_output=True, text=True, timeout=SYNC_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _EnvironmentFailure(f"{step}: {exc}") from exc
    if ran.returncode != 0:
        raise _EnvironmentFailure(f"{step} exited {ran.returncode}: {ran.stderr.strip()[-2000:]}")


def admit(case: ImplementerCase, repo: Path) -> list[str]:
    """Why the case does not discriminate: empty if its hidden tests FAIL at the pin and PASS at the fix."""
    problems: list[str] = []
    for label, patch, required in (
        ("the pin", "", "FAIL"),
        ("the fix", fix_patch(case, repo), "PASS"),
    ):
        run = score_patch(case, patch, repo)
        last = run.detail.strip().splitlines()[-1] if run.detail.strip() else ""
        print(f"{case.id}: {run.outcome} at {label}: {last}")
        if run.outcome != required:
            problems.append(
                f"{case.id}: hidden tests at {label} must {required}, got {run.outcome}\n{run.detail}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check", "admit", "score"])
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--repo", type=Path, default=ROOT, help="git repository holding every pin")
    parser.add_argument("--case", help="case id (score: required; admit: default every case)")
    parser.add_argument("--patch", type=Path, help="score: the agent's unified diff")
    args = parser.parse_args(argv)

    try:
        loaded = load_suite(args.suite)
        if args.command == "score":
            if args.case is None or args.patch is None:
                parser.error("score needs --case and --patch")
            result = score_patch(loaded.case(args.case), args.patch.read_text(), args.repo)
            print(f"RESULT: {result.outcome}\n{result.detail}")
            return {"PASS": 0, "FAIL": 1, "ERROR": 2}[result.outcome]
        problems = check_commits(loaded, args.repo)
        if args.command == "admit" and not problems:
            chosen = [loaded.case(args.case)] if args.case else list(loaded.cases)
            for case in chosen:
                found = admit(case, args.repo)
                print(f"{case.id}: {'admitted' if not found else 'NOT admitted'}")
                problems.extend(found)
    except DefinitionError as exc:
        print(f"suite definition is invalid:\n{exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"{loaded.suite.id} v{loaded.suite.version}: {len(loaded.cases)} case(s) OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
