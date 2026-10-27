#!/usr/bin/env python3
"""Score an IMPLEMENTER patch against its case's hidden tests (#1725, #2108 S4).

Standard library only: this file is copied, at a recorded commit, into a
throwaway container from the pinned workspace image (``scripts/eval_referee.py``),
where nothing but Python, git and uv exists. ``scripts/eval_implementer.py``
calls the same functions on a host.

    python3 implementer_scorer.py prepare --pin PIN.json --repo REPO --out DIR
    python3 implementer_scorer.py score --prepared DIR --patch FILE

PIN.json is ``{"id", "commit", "fix_commit", "hidden_tests"}``.

SCORE builds a worktree at the case's pin, applies the agent's patch, writes
each hidden test file as it stands at ``fix_commit`` (over anything the patch
did to that path: the hidden tests are the judge, not the agent's copy of
them) and runs pytest on those files and nothing else.

PASS is not pytest's exit 0. Exit 0 also covers a test that was skipped,
xfailed or deselected, so an agent's conftest that skips the hidden tests would
earn it. The intended hidden tests are the node ids pytest collects from the
hidden files at ``fix_commit``, before any agent code exists; a recording
plugin outside the tree reports how each one ended on the change, and every one
of them must have run and passed. Every file pytest reads its configuration
or plugins from (``conftest.py``, ``pytest.ini``, ``pyproject.toml`` ...) that
the patch touches is also put back as it stands at ``fix_commit``, or removed
if the fix has none: like the hidden tests, how they are run is the judge's. A
patch adding ``-p hooks`` to ``addopts`` would otherwise load a plugin that
rewrites every report to passed before the recorder sees it.

Not closed: the hidden tests import the change, so code it adds runs inside
the pytest process and can forge anything that process reports (#2136).

    PASS   every intended hidden test ran and passed on the agent's change
    FAIL   the patch does not apply, a hidden test failed, or one was skipped,
           xfailed, deselected or never reported
    ERROR  the environment failed: the pin or a hidden file is missing, uv or
           pytest could not run, no test was collected, or the run timed out

ERROR is never the agent's fault and never counts as a FAIL. Exit status: 0
PASS, 1 FAIL, 2 ERROR, and the last line of output is ``RESULT: <outcome>``.

PREPARE AND SCORE --PREPARED split one score in two so the agent's code can run
with the network cut. ``prepare`` does everything that may fetch (collect the
intended node ids at the fix, build the pin's environment) and nothing that
runs agent code. ``score --prepared`` then applies the patch to that prepared
tree and runs the hidden tests. It never syncs: a prepared tree without its
environment is ERROR, never a reason to fetch. A prepared directory scores one
patch; a second ``score`` on it is ERROR.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

TEST_TIMEOUT_SECONDS = 300
SYNC_TIMEOUT_SECONDS = 900
SYNC = ("uv", "sync", "--frozen", "--quiet")
PYTEST = ("uv", "run", "--frozen", "--no-sync", "pytest")
"""How the environment is built and pytest run in a tree. Module-level so a test can point
them at a tiny repository's interpreter and still go through the real worktree and pytest."""
ENVIRONMENT = ".venv"
PATCH_ERRORS = "surrogateescape"
"""How a patch is carried as str: `git diff --binary` promises no encoding for a text
hunk, and surrogateescape maps every byte to a str and back unchanged."""
JUDGE_CONFIG = frozenset(
    {
        "conftest.py",
        "pytest.toml",
        ".pytest.toml",
        "pytest.ini",
        ".pytest.ini",
        "pyproject.toml",
        "tox.ini",
        "setup.cfg",
    }
)
"""File names pytest reads configuration or plugins from, in any directory: judged at the fix."""
"""What SYNC builds inside a tree. `score --prepared` refuses a tree without it."""

PREPARED = "prepared.json"
CONSUMED = "consumed"
_PREPARED_SCHEMA = 1

_RECORDER = "syn_eval_hidden_outcomes"
_RECORDER_SOURCE = '''\
"""Loaded by scripts/implementer_scorer.py from outside the tree: how each hidden test ended."""
import json
import os
import re

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
EXIT_CODES: dict[Outcome, int] = {"PASS": 0, "FAIL": 1, "ERROR": 2}


@dataclass(frozen=True)
class Pin:
    """What scoring needs from a case: where the bug is, where the fix is, what judges."""

    id: str
    commit: str
    fix_commit: str
    hidden_tests: tuple[str, ...]

    @classmethod
    def from_json(cls, text: str) -> Pin:
        raw = json.loads(text)
        return cls(
            id=str(raw["id"]),
            commit=str(raw["commit"]),
            fix_commit=str(raw["fix_commit"]),
            hidden_tests=tuple(str(p) for p in raw["hidden_tests"]),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "commit": self.commit,
                "fix_commit": self.fix_commit,
                "hidden_tests": list(self.hidden_tests),
            }
        )


@dataclass(frozen=True)
class TestRun:
    __test__ = False  # not a pytest class

    outcome: Outcome
    detail: str
    """Why: the failing step, or the tail of pytest's output."""


@dataclass(frozen=True)
class _Recorded:
    collected: tuple[str, ...]
    outcomes: dict[str, dict[str, str]]
    """node id -> {setup|call|teardown: passed|failed|skipped|xfail}, as pytest reported them."""


class _EnvironmentFailure(Exception):
    """Something other than the agent's change stopped the run: always ERROR."""


def git(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """git in `repo`, every byte in and out kept: no newline translation, no decode error."""
    ran = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        input=None if stdin is None else stdin.encode("utf-8", PATCH_ERRORS),
    )
    return subprocess.CompletedProcess(
        ran.args,
        ran.returncode,
        ran.stdout.decode("utf-8", PATCH_ERRORS),
        ran.stderr.decode("utf-8", PATCH_ERRORS),
    )


_git = git


def read_patch(path: Path) -> str:
    """A patch file as the scorer carries it: every byte, CRLF and non-UTF-8 included."""
    return path.read_bytes().decode("utf-8", PATCH_ERRORS)


@contextmanager
def _worktree(repo: Path, sha: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="implementer-eval-") as tmp:
        tree = Path(tmp) / "tree"
        _add_worktree(repo, sha, tree)
        try:
            yield tree
        finally:
            _git(repo, "worktree", "remove", "--force", str(tree))


def _add_worktree(repo: Path, sha: str, tree: Path) -> None:
    added = _git(repo, "worktree", "add", "--detach", "--quiet", str(tree), sha)
    if added.returncode != 0:
        raise _EnvironmentFailure(f"git worktree add {sha}: {added.stderr.strip()}")
    _check_out_submodules(repo, tree)


def _check_out_submodules(repo: Path, tree: Path) -> None:
    """Check out each submodule at the commit the pin records, from `repo`'s own clone of it.

    Never from the network: the environment has nothing to fetch, and a
    submodule commit the local clone lacks is an ERROR, not something to go
    and get.

    Never through `git config` or `git submodule` either: `tree` is a worktree
    of `repo`, so both write the config every worktree and the main checkout
    share. That once repointed every checkout's submodule URLs at a scratch
    worktree. Each submodule is a plain `--shared` clone at its gitlink instead,
    which writes only inside `tree`.
    """
    paths = _git(tree, "config", "--file", ".gitmodules", "--get-regexp", r"submodule\..*\.path")
    for line in paths.stdout.splitlines():
        _, path = line.split(maxsplit=1)
        listed = _git(tree, "ls-tree", "HEAD", path).stdout.split()
        if len(listed) < 3 or listed[1] != "commit":
            continue
        gitlink, source, target = listed[2], (repo / path).resolve(), tree / path
        cloned = _git(
            target.parent, "clone", "--quiet", "--shared", "--no-checkout", str(source), str(target)
        )
        checked = (
            cloned.returncode == 0
            and _git(target, "checkout", "--quiet", "--detach", gitlink).returncode == 0
        )
        if not checked:
            detail = cloned.stderr.strip() or f"{gitlink} is not in {source}"
            raise _EnvironmentFailure(f"submodule {path} at the pin: {detail}")


def score_patch(pin: Pin, patch: str, repo: Path) -> TestRun:
    """Apply `patch` at the case's pin, restore the hidden tests and run only them."""
    try:
        expected = _intended_hidden_tests(pin, repo)
        with _worktree(repo, pin.commit) as tree:
            # The environment is built from the pin, before the patch: a failure
            # here is the environment's, and the agent's change cannot cause it.
            _run(tree, list(SYNC), "uv sync at the pin")
            return _judge(pin, patch, repo, tree, expected)
    except _EnvironmentFailure as exc:
        return TestRun(outcome="ERROR", detail=str(exc))


def prepare(pin: Pin, repo: Path, out: Path) -> TestRun | None:
    """Everything `score --prepared` needs that may touch the network. None when ready.

    Collects the intended node ids at the fix and builds the pin's environment in
    `out/tree`, a worktree of `repo` that outlives this call. No agent code runs.
    """
    try:
        if out.exists() and any(out.iterdir()):
            raise _EnvironmentFailure(f"{out} is not empty: prepare a fresh directory")
        out.mkdir(parents=True, exist_ok=True)
        expected = _intended_hidden_tests(pin, repo)
        tree = out / "tree"
        _add_worktree(repo, pin.commit, tree)
        _run(tree, list(SYNC), "uv sync at the pin")
    except _EnvironmentFailure as exc:
        return TestRun(outcome="ERROR", detail=str(exc))
    (out / PREPARED).write_text(
        json.dumps(
            {
                "schema": _PREPARED_SCHEMA,
                "pin": json.loads(pin.to_json()),
                "repo": str(repo.resolve()),
                "expected": list(expected),
            }
        )
    )
    return None


def score_prepared(out: Path, patch: str) -> TestRun:
    """Score `patch` on a tree `prepare` built. Never syncs, never fetches; one patch per tree."""
    try:
        pin, repo, expected = _read_prepared(out)
        # Claimed before anything runs, so a crash mid-score cannot leave a
        # half-patched tree that a second score would read as the pin.
        try:
            (out / CONSUMED).touch(exist_ok=False)
        except FileExistsError as exc:
            raise _EnvironmentFailure(
                f"{out} already scored a patch: prepare a fresh directory for each patch"
            ) from exc
        tree = out / "tree"
        head = _git(tree, "rev-parse", "HEAD").stdout.strip()
        if head != pin.commit:
            raise _EnvironmentFailure(f"prepared tree is at {head or 'nothing'}, not {pin.commit}")
        dirty = _git(tree, "status", "--porcelain", "--untracked-files=no").stdout.strip()
        if dirty:
            raise _EnvironmentFailure(f"prepared tree is not clean at the pin:\n{dirty}")
        if not (tree / ENVIRONMENT).is_dir():
            raise _EnvironmentFailure(
                f"prepared tree has no {ENVIRONMENT}: score --prepared never syncs, so the"
                " environment must come from prepare"
            )
        return _judge(pin, patch, repo, tree, expected)
    except _EnvironmentFailure as exc:
        return TestRun(outcome="ERROR", detail=str(exc))


def _read_prepared(out: Path) -> tuple[Pin, Path, tuple[str, ...]]:
    try:
        raw = json.loads((out / PREPARED).read_text())
        if raw["schema"] != _PREPARED_SCHEMA:
            raise _EnvironmentFailure(f"{out / PREPARED}: schema {raw['schema']!r} is not known")
        pin = Pin.from_json(json.dumps(raw["pin"]))
        expected = tuple(str(n) for n in raw["expected"])
        repo = Path(str(raw["repo"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _EnvironmentFailure(f"{out} is not a prepared directory: {exc!r}") from exc
    if not expected:
        raise _EnvironmentFailure(f"{out / PREPARED} names no intended hidden test")
    return pin, repo, expected


def _judge(pin: Pin, patch: str, repo: Path, tree: Path, expected: tuple[str, ...]) -> TestRun:
    """Apply the patch to a tree at the pin, put the judge's files back, run the hidden tests."""
    if patch.strip():
        applied = _git(tree, "apply", "--whitespace=nowarn", "-", stdin=patch)
        if applied.returncode != 0:
            return TestRun(outcome="FAIL", detail=f"patch does not apply: {applied.stderr.strip()}")
    touched = {*_patched_paths(tree, patch), *_changed_tracked_paths(tree)}
    judged = {p for p in touched if Path(p).name in JUDGE_CONFIG}
    for path in sorted(judged | set(pin.hidden_tests)):
        _restore_from_fix(repo, tree, pin.fix_commit, path)
    return _run_hidden_tests(tree, pin.hidden_tests, expected)


def _intended_hidden_tests(pin: Pin, repo: Path) -> tuple[str, ...]:
    """The node ids the hidden files hold, collected at `fix_commit` where no agent code exists."""
    with _worktree(repo, pin.fix_commit) as tree:
        _run(tree, list(SYNC), "uv sync at the fix")
        try:
            ran, recorded = _pytest(tree, ["--collect-only", "-n", "0", *pin.hidden_tests])
        except subprocess.TimeoutExpired as exc:
            raise _EnvironmentFailure(f"collecting the hidden tests at the fix: {exc}") from exc
    if ran.returncode != 0 or recorded is None or not recorded.collected:
        tail = "\n".join((ran.stderr + ran.stdout).strip().splitlines()[-15:])
        raise _EnvironmentFailure(
            f"collecting the hidden tests at the fix: exit {ran.returncode}\n{tail}"
        )
    return recorded.collected


def _changed_tracked_paths(tree: Path) -> list[str]:
    """Every tracked path the applied patch changed, a rename's source and a delete included.

    `git apply --numstat` names only a rename's destination, so a patch moving
    `conftest.py` away would take the judge's fixtures with it unseen.
    """
    listed = _git(tree, "diff", "--name-only", "--no-renames", "-z", "HEAD")
    if listed.returncode != 0:
        raise _EnvironmentFailure(f"listing what the patch changed: {listed.stderr.strip()}")
    return [p for p in listed.stdout.split("\0") if p]


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
        if Path(path).name in JUDGE_CONFIG:
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
    """Run pytest in `tree` with the recorder loaded from outside it. Raises `TimeoutExpired`.

    `UV_OFFLINE` is set: running the tests never fetches, so anything that
    would is refused by uv instead of quietly working on a networked host.
    """
    with tempfile.TemporaryDirectory(prefix="implementer-recorder-") as tmp:
        (Path(tmp) / f"{_RECORDER}.py").write_text(_RECORDER_SOURCE)
        record = Path(tmp) / "outcomes.json"
        env = dict(os.environ, SYN_EVAL_OUTCOMES=str(record), UV_OFFLINE="1")
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
        recorded = _read_record(record)
    return ran, recorded


def _read_record(record: Path) -> _Recorded | None:
    try:
        raw = json.loads(record.read_text())
        collected = tuple(str(n) for n in raw.get("collected", ()))
        outcomes = {
            str(nodeid): {str(when): str(how) for when, how in phases.items()}
            for nodeid, phases in raw.get("outcomes", {}).items()
        }
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    return _Recorded(collected=collected, outcomes=outcomes)


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


def report(run: TestRun) -> int:
    """Print the run with its verdict on the last line; return its exit status."""
    print(f"{run.detail}\nRESULT: {run.outcome}")
    return EXIT_CODES[run.outcome]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="network on: everything before the agent's code")
    prep.add_argument("--pin", type=Path, required=True, help="the case as PIN.json")
    prep.add_argument("--repo", type=Path, required=True, help="git repository holding the pin")
    prep.add_argument("--out", type=Path, required=True, help="a fresh directory to prepare")
    score = commands.add_parser("score", help="offline: one patch on a prepared tree")
    score.add_argument("--prepared", type=Path, required=True)
    score.add_argument("--patch", type=Path, required=True, help="the agent's unified diff")
    args = parser.parse_args(argv)

    if args.command == "prepare":
        try:
            pin = Pin.from_json(args.pin.read_text())
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return report(TestRun(outcome="ERROR", detail=f"{args.pin}: {exc!r}"))
        failed = prepare(pin, args.repo, args.out)
        if failed is not None:
            return report(failed)
        print(f"prepared {pin.id} at {pin.commit} in {args.out}")
        return 0
    try:
        patch = read_patch(args.patch)
    except OSError as exc:
        return report(TestRun(outcome="ERROR", detail=f"{args.patch}: {exc}"))
    return report(score_prepared(args.prepared, patch))


if __name__ == "__main__":
    sys.exit(main())
