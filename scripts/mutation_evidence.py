"""Mutation evidence: prove named tests kill reviewed mutation patches.

Run by `.github/workflows/mutation-evidence.yml`, never by hand on a dev
machine: the owner banned local Docker verifier runs (permission prompts), and
agent workspaces have no Docker at all. Dispatch it with
`just mutation-evidence <pr> "<node ids>"`.

The contract, one PR at a time:

1. Every `*.patch` in the mutations dir on the PR head is a reviewed,
   versioned mutation of non-test source. No free-form expressions are ever
   accepted: inputs are a PR number, pytest node ids and a path, each validated
   against a strict pattern before anything runs.
2. The named tests must PASS on the unmutated head. A red baseline makes every
   kill meaningless ("baseline red, evidence void").
3. Each patch must apply cleanly, must change the tree, and must touch only
   non-test source. A mutation of a test, a conftest or the pytest config
   proves nothing, and a patch that changes nothing reads exactly like a kill.
4. Bytecode is cleared before every run (the stale `.pyc` trap) and the tree is
   proven clean after every restore.
5. KILLED means at least one named test failed. SURVIVED means all passed. The
   run fails if any mutation survived or any patch could not be applied.

What a survival means, and what it does not: these are the NAMED tests only. A
narrow selection can prove a kill, never that the wider suite misses the
mutant. And a kill proves the test is real, not that the fix is right for every
input shape production produces.

Usage (from the PR checkout):

    mutation_evidence.py validate            # inputs from env, exit 1 if bad
    mutation_evidence.py run --report FILE   # baseline + every patch
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

#: The PR comment carries this marker so each run updates one comment.
MARKER: Final = "<!-- mutation-evidence -->"

ENV_PR: Final = "MUTATION_PR"
ENV_TESTS: Final = "MUTATION_TESTS"
ENV_DIR: Final = "MUTATION_DIR"
ENV_SHA: Final = "MUTATION_SHA"

MAX_TESTS: Final = 50
MAX_PATCHES: Final = 40
PYTEST_TIMEOUT_SECONDS: Final = 15 * 60

_PR_RE: Final = re.compile(r"^[1-9][0-9]{0,6}$")
_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
#: One path segment: no leading dash (option injection) and no leading dot
#: other than the mutations dir convention, which is handled separately.
_SEGMENT_RE: Final = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
#: `path/to/test_x.py` then zero or more `::Name`, the last may carry a
#: parametrize id in brackets.
_NODE_ID_RE: Final = re.compile(
    r"^(?P<path>[A-Za-z0-9_][A-Za-z0-9_./-]*\.py)"
    r"(?P<rest>(::[A-Za-z_][A-Za-z0-9_]*)*(::[A-Za-z_][A-Za-z0-9_]*\[[A-Za-z0-9_.,=+-]*\])?)$"
)
_DIR_RE: Final = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")

_TEST_DIR_NAMES: Final = frozenset({"tests", "test"})
_CONFIG_NAMES: Final = frozenset(
    {"conftest.py", "pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini", "uv.lock"}
)
_FORBIDDEN_PREFIXES: Final = (".github/", "ci/fitness/", "lib/")
_SKIP_WALK: Final = frozenset({".git", ".venv", "node_modules"})

_SUMMARY_LINE_RE: Final = re.compile(r"^(FAILED|ERROR) (\S+)")
_PASSED_RE: Final = re.compile(r"\b(\d+) passed\b")


class InputError(ValueError):
    """An input failed validation. Nothing has run."""


class Outcome(StrEnum):
    KILLED = "killed"
    SURVIVED = "SURVIVED"
    APPLY_FAILED = "APPLY FAILED"
    NOT_APPLIED = "NOT APPLIED"
    TOUCHES_TESTS = "INVALID (touches tests/config)"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Inputs:
    pr: int
    tests: tuple[str, ...]
    mutations_dir: PurePosixPath


@dataclass(frozen=True)
class PytestRun:
    exit_code: int
    failing: tuple[str, ...]
    passed: int
    seconds: float


@dataclass(frozen=True)
class PatchResult:
    patch: str
    outcome: Outcome
    files: tuple[str, ...] = ()
    failing: tuple[str, ...] = ()
    seconds: float = 0.0
    detail: str = ""


@dataclass
class Evidence:
    pr: int
    sha: str
    tests: tuple[str, ...]
    baseline: PytestRun | None = None
    baseline_detail: str = ""
    results: list[PatchResult] = field(default_factory=list[PatchResult])

    @property
    def ok(self) -> bool:
        if self.baseline is None or self.baseline_detail:
            return False
        return bool(self.results) and all(r.outcome is Outcome.KILLED for r in self.results)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _safe_relative(path: str, what: str) -> PurePosixPath:
    """A relative path with no `..`, no absolute root and no option-like segment."""
    if not path or path.startswith("/") or "\\" in path or "//" in path:
        raise InputError(f"{what} {path!r} must be a plain relative path")
    pure = PurePosixPath(path)
    for part in pure.parts:
        if part in {"..", "."} or part == ".git":
            raise InputError(f"{what} {path!r} may not contain '.', '..' or '.git' segments")
        if part.startswith("-"):
            raise InputError(f"{what} {path!r} has a segment starting with '-'")
    return pure


def parse_pr(raw: str) -> int:
    if not _PR_RE.fullmatch(raw.strip()):
        raise InputError(f"pr {raw!r} is not a pull request number")
    return int(raw.strip())


def parse_tests(raw: str) -> tuple[str, ...]:
    ids = tuple(raw.split())
    if not ids:
        raise InputError("tests is empty; name at least one pytest node id")
    if len(ids) > MAX_TESTS:
        raise InputError(f"tests names {len(ids)} node ids; the limit is {MAX_TESTS}")
    for node_id in ids:
        match = _NODE_ID_RE.fullmatch(node_id)
        if match is None:
            raise InputError(
                f"test {node_id!r} is not a pytest node id of the form "
                "path/to/test_x.py[::Class]::test_name[param]"
            )
        _safe_relative(match.group("path"), "test path")
    return ids


def parse_mutations_dir(raw: str) -> PurePosixPath:
    value = raw.strip()
    if not _DIR_RE.fullmatch(value):
        raise InputError(f"mutations_dir {raw!r} contains characters outside [A-Za-z0-9_./-]")
    value = value.rstrip("/")
    pure = PurePosixPath(value)
    bad_part = any(p in {"..", ".", ".git"} or p.startswith("-") for p in pure.parts)
    if not value or str(pure) == "." or bad_part:
        raise InputError(f"mutations_dir {raw!r} must stay inside the repository")
    return pure


def parse_inputs(pr: str, tests: str, mutations_dir: str) -> Inputs:
    return Inputs(parse_pr(pr), parse_tests(tests), parse_mutations_dir(mutations_dir))


def inputs_from_env(env: dict[str, str]) -> Inputs:
    return parse_inputs(env.get(ENV_PR, ""), env.get(ENV_TESTS, ""), env.get(ENV_DIR, ""))


def resolve_inside(root: Path, relative: PurePosixPath, what: str) -> Path:
    """Resolve `relative` under `root`, following symlinks, and refuse escapes."""
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise InputError(f"{what} {relative} resolves outside the repository")
    return resolved


def find_patches(root: Path, mutations_dir: PurePosixPath) -> list[Path]:
    directory = resolve_inside(root, mutations_dir, "mutations_dir")
    if not directory.is_dir():
        raise InputError(f"mutations_dir {mutations_dir} does not exist on the PR head")
    patches = sorted(directory.glob("*.patch"))
    if not patches:
        raise InputError(f"no *.patch files in {mutations_dir}")
    if len(patches) > MAX_PATCHES:
        raise InputError(f"{len(patches)} patches; the limit is {MAX_PATCHES}")
    for patch in patches:
        if patch.is_symlink() or not patch.is_file():
            raise InputError(f"{patch.name} must be a regular file, not a symlink")
    return patches


# --------------------------------------------------------------------------
# What a mutation may touch
# --------------------------------------------------------------------------


def forbidden_reason(path: str, mutations_dir: PurePosixPath) -> str | None:
    """Why a mutation may not touch `path`, or None if it is non-test source."""
    pure = PurePosixPath(path)
    name = pure.name
    if pure.is_relative_to(mutations_dir):
        return "the mutations dir itself"
    if any(path.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES):
        return "CI, fitness or submodule path"
    if name in _CONFIG_NAMES:
        return "test or build configuration"
    if any(part in _TEST_DIR_NAMES for part in pure.parts[:-1]):
        return "inside a tests directory"
    if name.startswith("test_") or name.endswith("_test.py"):
        return "a test module"
    return None


# --------------------------------------------------------------------------
# Git and pytest
# --------------------------------------------------------------------------


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, timeout=120
    )


def changed_paths(root: Path) -> list[str]:
    """Every tracked change and untracked (non-ignored) file, repo-relative."""
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    paths: list[str] = []
    entries = out.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in {"R", "C"}:
            index += 1  # the rename source follows as its own entry
    return sorted(paths)


def restore(root: Path) -> None:
    """Return the tree to HEAD and prove it, or raise."""
    _git(root, "checkout", "--", ".")
    _git(root, "clean", "-fd")
    left = changed_paths(root)
    if left:
        raise RuntimeError(f"tree not clean after restore: {left}")


def clear_bytecode(root: Path) -> int:
    """Delete every __pycache__ dir and stray .pyc outside .venv. Returns count."""
    removed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_WALK]
        if "__pycache__" in dirnames:
            shutil.rmtree(Path(dirpath) / "__pycache__", ignore_errors=True)
            dirnames.remove("__pycache__")
            removed += 1
        for name in filenames:
            if name.endswith((".pyc", ".pyo")):
                (Path(dirpath) / name).unlink(missing_ok=True)
                removed += 1
    return removed


def parse_pytest_output(output: str) -> tuple[tuple[str, ...], int]:
    """(failing node ids from the -rfE summary, passed count)."""
    failing = tuple(
        dict.fromkeys(
            m.group(2) for line in output.splitlines() if (m := _SUMMARY_LINE_RE.match(line))
        )
    )
    passed_matches = _PASSED_RE.findall(output)
    passed = int(passed_matches[-1]) if passed_matches else 0
    return failing, passed


def run_pytest(root: Path, tests: tuple[str, ...]) -> PytestRun:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # `-m ""` clears the repo's `-m "not integration"` addopt: a named
    # integration test must run, not be deselected into a vacuous pass.
    cmd = [
        "uv", "run", "--frozen", "pytest", "-m", "", "-p", "no:cacheprovider",
        "--color=no", "-rfE", "--", *tests,
    ]  # fmt: skip
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=root, env=env, capture_output=True, text=True, check=False,
            timeout=PYTEST_TIMEOUT_SECONDS,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return PytestRun(exit_code=-1, failing=(), passed=0, seconds=time.monotonic() - started)
    seconds = time.monotonic() - started
    output = proc.stdout + proc.stderr
    print(output[-20000:], flush=True)
    failing, passed = parse_pytest_output(output)
    return PytestRun(proc.returncode, failing, passed, seconds)


#: Runs the named tests in `root`. Injected so the git machinery is testable
#: without a pytest-in-pytest.
Runner = Callable[[Path, tuple[str, ...]], PytestRun]


def classify(run: PytestRun) -> Outcome:
    """pytest exit 0 = all passed, 1 = a test failed, 2 = collection error."""
    if run.exit_code == 0:
        return Outcome.SURVIVED
    if run.exit_code in {1, 2}:
        return Outcome.KILLED
    return Outcome.ERROR


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def evaluate_patch(root: Path, patch: Path, inputs: Inputs, runner: Runner) -> PatchResult:
    name = patch.name
    check = _git(root, "apply", "--check", str(patch))
    if check.returncode != 0:
        return PatchResult(name, Outcome.APPLY_FAILED, detail=check.stderr.strip()[:300])
    applied = _git(root, "apply", str(patch))
    if applied.returncode != 0:
        return PatchResult(name, Outcome.APPLY_FAILED, detail=applied.stderr.strip()[:300])
    files = tuple(changed_paths(root))
    if not files:
        return PatchResult(name, Outcome.NOT_APPLIED, detail="patch applied but changed nothing")
    bad = [f"{f} ({why})" for f in files if (why := forbidden_reason(f, inputs.mutations_dir))]
    if bad:
        return PatchResult(name, Outcome.TOUCHES_TESTS, files=files, detail="; ".join(bad))
    clear_bytecode(root)
    run = runner(root, inputs.tests)
    outcome = classify(run)
    detail = "" if outcome is not Outcome.ERROR else f"pytest exit {run.exit_code}"
    return PatchResult(name, outcome, files, run.failing, run.seconds, detail)


def execute(root: Path, inputs: Inputs, sha: str, runner: Runner = run_pytest) -> Evidence:
    evidence = Evidence(pr=inputs.pr, sha=sha, tests=inputs.tests)
    for node_id in inputs.tests:
        test_path = PurePosixPath(node_id.split("::", 1)[0])
        if not resolve_inside(root, test_path, "test path").is_file():
            raise InputError(f"test file {test_path} does not exist on the PR head")
    patches = find_patches(root, inputs.mutations_dir)
    dirty = changed_paths(root)
    if dirty:
        raise RuntimeError(f"tree dirty before the baseline (setup changed it): {dirty}")

    clear_bytecode(root)
    evidence.baseline = runner(root, inputs.tests)
    # Anything the baseline wrote into the tree would otherwise be counted as
    # part of the first patch's diff.
    restore(root)
    if evidence.baseline.exit_code != 0:
        evidence.baseline_detail = (
            f"baseline red (pytest exit {evidence.baseline.exit_code}), evidence void"
        )
    elif evidence.baseline.passed == 0:
        evidence.baseline_detail = "baseline ran zero tests, evidence void"
    if evidence.baseline_detail:
        return evidence

    for patch in patches:
        print(f"::group::mutation {patch.name}", flush=True)
        try:
            evidence.results.append(evaluate_patch(root, patch, inputs, runner))
        finally:
            restore(root)
            print("::endgroup::", flush=True)
    return evidence


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _cell(text: str) -> str:
    """Neutralise text that came out of PR code before it reaches markdown."""
    cleaned = text.replace("`", "'").replace("|", "\\|").replace("\n", " ").replace("@", "@\u200b")
    return cleaned[:200]


def _code(items: tuple[str, ...]) -> str:
    return "<br>".join(f"`{_cell(i)}`" for i in items) if items else "-"


def render(evidence: Evidence, run_url: str) -> str:
    verdict = "PASS: every mutation killed" if evidence.ok else "FAIL"
    lines = [
        MARKER,
        "## Mutation evidence",
        "",
        f"**{verdict}** | PR #{evidence.pr} | head `{evidence.sha}` | [run]({run_url})",
        "",
        f"Tests: {_code(evidence.tests)}",
        "",
    ]
    if evidence.baseline is not None:
        base = evidence.baseline
        status = evidence.baseline_detail or f"green ({base.passed} passed)"
        lines.append(f"Baseline (unmutated head): {status}, {base.seconds:.1f}s")
        if base.failing:
            lines.append(f"Baseline failures: {_code(base.failing)}")
        lines.append("")
    if evidence.results:
        lines += [
            "| Patch | Files touched | Result | Failing tests | Duration |",
            "|---|---|---|---|---|",
        ]
        for r in evidence.results:
            result = r.outcome.value + (f" ({_cell(r.detail)})" if r.detail else "")
            lines.append(
                f"| `{_cell(r.patch)}` | {_code(r.files)} | {result} | "
                f"{_code(r.failing)} | {r.seconds:.1f}s |"
            )
        lines.append("")
    lines += [
        "A kill proves the named test catches the mutant. A survival is against the",
        "named tests only. Patches are evidence for this PR: delete the mutations dir",
        "before merge (CI enforces it); this comment is the record.",
    ]
    return "\n".join(lines) + "\n"


def render_error(pr: int, sha: str, run_url: str, message: str) -> str:
    return (
        f"{MARKER}\n## Mutation evidence\n\n**FAIL** | PR #{pr} | head `{sha}` | "
        f"[run]({run_url})\n\n{_cell(message)}\n"
    )


def _run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate the inputs in the environment")
    run = sub.add_parser("run", help="baseline + every patch, from the PR checkout")
    run.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    env = dict(os.environ)

    try:
        inputs = inputs_from_env(env)
    except InputError as exc:
        print(f"::error::{exc}")
        return 1
    if args.command == "validate":
        print(f"inputs ok: pr={inputs.pr} tests={len(inputs.tests)} dir={inputs.mutations_dir}")
        return 0

    sha = env.get(ENV_SHA, "")
    if not _SHA_RE.fullmatch(sha):
        print(f"::error::{ENV_SHA} {sha!r} is not a commit sha")
        return 1
    report: Path = args.report
    try:
        evidence = execute(Path.cwd(), inputs, sha)
    except (InputError, RuntimeError) as exc:
        print(f"::error::{exc}")
        report.write_text(render_error(inputs.pr, sha, _run_url(), str(exc)))
        return 1
    report.write_text(render(evidence, _run_url()))
    print(report.read_text())
    return 0 if evidence.ok else 1


if __name__ == "__main__":
    sys.exit(main())
