"""Mutation evidence: prove named tests kill reviewed mutation patches.

Run by `.github/workflows/mutation-evidence.yml`, never by hand on a dev
machine: the owner banned local Docker verifier runs (permission prompts), and
agent workspaces have no Docker at all. Dispatch it with
`just mutation-evidence <pr> "<node ids>"`.

The contract, one PR at a time:

1. Every `*.patch` under `.mutations/` on the PR head is a reviewed,
   versioned mutation of non-test source. No free-form expressions are ever
   accepted: inputs are a PR number, pytest node ids and a path, each validated
   against a strict pattern before anything runs.
2. The named tests must PASS on the unmutated head. A red baseline makes every
   kill meaningless ("baseline red, evidence void").
3. Each patch is vetted BEFORE it is applied. Renames and copies are refused
   (git reports only their destination, so a source could escape vetting).
   Every path it names must be
   tracked-or-trackable (not ignored), must not be or sit behind a symlink,
   must not be a named test file, a test module, conftest, pytest config, a
   lockfile, or workflow/CI config. Harness and adapter source beside the tests
   IS allowed: it stands in for production and is where gaps hide. After
   applying, the tree must have changed, and only on those paths. A mutation of a test proves nothing, and a patch that changes
   nothing reads exactly like a kill.
4. Bytecode is cleared before every run (the stale `.pyc` trap) and the tree is
   proven clean after every restore.
5. KILLED means pytest reported a failed test or a collection error. SURVIVED
   means every named test passed. Anything else (an interrupt, a timeout, no
   failure on record) is ERROR. The run fails unless every patch was KILLED.

ISOLATION. This script is trusted; the PR is not. With `--image`, every
command that executes PR code (`uv sync`, which runs build backends, and each
pytest run) runs in a throwaway container: the PR checkout mounted at /work,
its `.git` read-only, no Docker socket, the host uid, no host environment
beyond a fixed list of test variables. PR code therefore cannot rewrite this
script, the report it writes, the git hooks it runs, or reach the runner's
credentials or the Actions cache.

`--host` (workflow input `docker=true`, the DEFAULT) is the exception, for tests that drive
the Docker daemon themselves (docker compose with bind mounts, as the broker
integration suite does): a container holding the Docker socket IS the host, so
PR code runs on the runner host. The remaining guards are the workflow's: no
secrets, a read-only token, no persisted credentials, no cache, same-repo PRs,
and a separate comment job. The limit: a PR written to forge its own verdict
could. Host-mode evidence is for honest PR code, not a security boundary.

A named test that SKIPS, XFAILS or XPASSES voids the baseline: none of those
is a pass, and each would read as one under every mutant.

What a survival means, and what it does not: these are the NAMED tests only. A
narrow selection can prove a kill, never that the wider suite misses the
mutant. And a kill proves the test is real, not that the fix is right for every
input shape production produces.

Usage:

    mutation_evidence.py validate                      # inputs from env
    mutation_evidence.py run --root PR --report FILE (--image IMAGE | --host)
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
#: The only place mutation patches may live. ci.yml `mutations-not-merged`
#: refuses it on main, so every accepted mutations_dir is covered by that check.
MUTATIONS_ROOT: Final = PurePosixPath(".mutations")

ENV_PR: Final = "MUTATION_PR"
ENV_TESTS: Final = "MUTATION_TESTS"
ENV_DIR: Final = "MUTATION_DIR"
ENV_SHA: Final = "MUTATION_SHA"
ENV_DISPATCH_ID: Final = "MUTATION_DISPATCH_ID"

#: Host variables forwarded into the test container. Nothing else crosses.
FORWARDED_ENV: Final = (
    "TEST_TIMESCALEDB_HOST",
    "TEST_TIMESCALEDB_PORT",
    "TEST_EVENTSTORE_HOST",
    "TEST_EVENTSTORE_PORT",
    "TERM",
    "NO_COLOR",
    "COLUMNS",
)
CONTAINER_ROOT: Final = "/work"

MAX_TESTS: Final = 50
MAX_PATCHES: Final = 40
PYTEST_TIMEOUT_SECONDS: Final = 15 * 60
SYNC_TIMEOUT_SECONDS: Final = 20 * 60

_PR_RE: Final = re.compile(r"^[1-9][0-9]{0,6}$")
_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_DISPATCH_ID_RE: Final = re.compile(r"^[A-Za-z0-9-]{0,64}$")
#: `path/to/test_x.py` then zero or more `::Name`, the last may carry a
#: parametrize id in brackets.
_NODE_ID_RE: Final = re.compile(
    r"^(?P<path>[A-Za-z0-9_][A-Za-z0-9_./-]*\.py)"
    r"(?P<rest>(::[A-Za-z_][A-Za-z0-9_]*)*(::[A-Za-z_][A-Za-z0-9_]*\[[A-Za-z0-9_.,=+-]*\])?)$"
)
_DIR_RE: Final = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")

#: What a mutation may touch is decided by the owner (#1941): ANY production
#: source, including harness and adapter code that lives beside the tests (a
#: broker stand-in under tests/ is where an uncaught deny-path mutant lived).
#: Refused: test modules, conftest, the mutations dir, workflow and CI config,
#: pytest configuration (it decides what the named tests even are) and
#: lockfiles.
#: Any `*.lock` (uv, poetry, Cargo, yarn, Pipfile, bun, Gemfile, composer) plus
#: the lockfiles that do not use that suffix.
_LOCKFILES: Final = frozenset(
    {"pnpm-lock.yaml", "package-lock.json", "npm-shrinkwrap.json", "bun.lockb", "go.sum"}
)
#: Every file pytest reads configuration from, at any depth.
_TEST_CONFIG: Final = frozenset(
    {
        "conftest.py", "pyproject.toml", "setup.cfg", "tox.ini",
        "pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml",
    }
)  # fmt: skip
_TEST_DIR_NAMES: Final = frozenset({"tests", "test"})
_FORBIDDEN_PREFIXES: Final = (".github/", "ci/")
_SKIP_WALK: Final = frozenset({".git", ".venv", "node_modules"})

_SUMMARY_LINE_RE: Final = re.compile(r"^(FAILED|ERROR) (\S+)")
_PASSED_RE: Final = re.compile(r"\b(\d+) passed\b")
_SKIPPED_RE: Final = re.compile(r"\b(\d+) skipped\b")
_XFAIL_RE: Final = re.compile(r"\b(\d+) x(?:failed|passed)\b")


class InputError(ValueError):
    """An input failed validation. Nothing has run."""


class Outcome(StrEnum):
    KILLED = "killed"
    SURVIVED = "SURVIVED"
    APPLY_FAILED = "APPLY FAILED"
    NOT_APPLIED = "NOT APPLIED"
    REFUSED = "REFUSED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Inputs:
    pr: int
    tests: tuple[str, ...]
    mutations_dir: PurePosixPath

    @property
    def test_files(self) -> frozenset[str]:
        return frozenset(node_id.split("::", 1)[0] for node_id in self.tests)


@dataclass(frozen=True)
class PytestRun:
    exit_code: int
    failing: tuple[str, ...]
    passed: int
    seconds: float
    skipped: int = 0
    xfail: int = 0


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
    if not pure.is_relative_to(MUTATIONS_ROOT):
        raise InputError(
            f"mutations_dir {raw!r} must be {MUTATIONS_ROOT}/ or a directory under it, "
            "the only place CI refuses on main"
        )
    return pure


def parse_dispatch_id(raw: str) -> str:
    if not _DISPATCH_ID_RE.fullmatch(raw):
        raise InputError(f"dispatch_id {raw!r} must match [A-Za-z0-9-]{{0,64}}")
    return raw


def parse_inputs(pr: str, tests: str, mutations_dir: str) -> Inputs:
    return Inputs(parse_pr(pr), parse_tests(tests), parse_mutations_dir(mutations_dir))


def inputs_from_env(env: dict[str, str]) -> Inputs:
    parse_dispatch_id(env.get(ENV_DISPATCH_ID, ""))
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
    """Why a mutation may not touch `path` by name, or None if it is source."""
    pure = PurePosixPath(path)
    name = pure.name
    if pure.is_relative_to(mutations_dir) or pure.is_relative_to(MUTATIONS_ROOT):
        return "the mutations dir itself"
    if any(path.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES):
        return "workflow or CI config"
    if name in _LOCKFILES or name.endswith(".lock"):
        return "a lockfile"
    if name in _TEST_CONFIG:
        return "conftest or pytest configuration"
    if name == "__init__.py" and any(p in _TEST_DIR_NAMES for p in pure.parts[:-1]):
        # Test package scaffolding, not harness: a raise here is a collection
        # error, which would read as a kill without touching any behaviour.
        return "a test package __init__"
    if (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py"):
        return "a test module"
    if ".test." in name or ".spec." in name:
        return "a test module"
    return None


def parse_numstat(output: str) -> list[str]:
    """Every path named by `git apply --numstat -z` (both sides of a rename)."""
    paths: list[str] = []
    fields = output.split("\0")
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry:
            continue
        parts = entry.split("\t", 2)
        if len(parts) != 3:
            continue
        if parts[2]:
            paths.append(parts[2])
        else:  # rename or copy: source and destination follow as entries
            paths.extend(fields[index : index + 2])
            index += 2
    return sorted(set(paths))


def is_rename_or_copy(summary_line: str) -> bool:
    """A `git apply --summary` line that renames or copies a file."""
    return summary_line.lstrip().startswith(("rename ", "copy "))


def vet_paths(root: Path, paths: list[str], inputs: Inputs) -> list[str]:
    """Every reason the patch may not be applied, path by path."""
    problems: list[str] = []
    real_root = root.resolve()
    test_targets = {(root / t).resolve() for t in inputs.test_files}
    for path in paths:
        try:
            pure = _safe_relative(path, "patched path")
        except InputError as exc:
            problems.append(str(exc))
            continue
        if why := forbidden_reason(path, inputs.mutations_dir):
            problems.append(f"{path} ({why})")
            continue
        if path in inputs.test_files:
            problems.append(f"{path} (a named test file)")
            continue
        lexical = real_root / pure
        resolved = (root / pure).resolve()
        if resolved != lexical:
            problems.append(f"{path} (is or sits behind a symlink)")
            continue
        if resolved in test_targets:
            problems.append(f"{path} (resolves to a named test file)")
            continue
        ignored = _git(root, "check-ignore", "-q", "--no-index", "--", path)
        if ignored.returncode == 0:
            problems.append(f"{path} (git-ignored, invisible to the tree checks)")
    return problems


# --------------------------------------------------------------------------
# Git, bytecode, pytest
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
            paths.append(entries[index])
            index += 1
    return sorted(set(paths))


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
            shutil.rmtree(Path(dirpath) / "__pycache__")
            dirnames.remove("__pycache__")
            removed += 1
        for name in filenames:
            if name.endswith((".pyc", ".pyo")):
                (Path(dirpath) / name).unlink()
                removed += 1
    return removed


def parse_pytest_output(output: str) -> tuple[tuple[str, ...], int, int, int]:
    """(failing ids from the -rfE summary, passed, skipped, xfailed + xpassed)."""
    failing = tuple(
        dict.fromkeys(
            m.group(2) for line in output.splitlines() if (m := _SUMMARY_LINE_RE.match(line))
        )
    )
    passed_matches = _PASSED_RE.findall(output)
    passed = int(passed_matches[-1]) if passed_matches else 0
    skipped_matches = _SKIPPED_RE.findall(output)
    skipped = int(skipped_matches[-1]) if skipped_matches else 0
    summary = next((ln for ln in reversed(output.splitlines()) if _XFAIL_RE.search(ln)), "")
    xfail = sum(int(n) for n in _XFAIL_RE.findall(summary))
    return failing, passed, skipped, xfail


def pytest_args(tests: tuple[str, ...]) -> list[str]:
    # `-m ""` clears the repo's `-m "not integration"` addopt: a named
    # integration test must run, not be deselected into a vacuous pass.
    return [
        "uv", "run", "--frozen", "pytest", "-m", "", "-p", "no:cacheprovider",
        "--color=no", "-rfEsxX", "--", *tests,
    ]  # fmt: skip


@dataclass(frozen=True)
class Sandbox:
    """Runs PR code in a container (see ISOLATION in the module docstring)."""

    image: str

    def command(self, root: Path, args: list[str]) -> list[str]:
        real = root.resolve()
        cmd = [
            "docker", "run", "--rm", "--network", "host",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{real}:{CONTAINER_ROOT}",
            "-v", f"{real / '.git'}:{CONTAINER_ROOT}/.git:ro",
            "-w", CONTAINER_ROOT,
            "-e", "HOME=/tmp", "-e", "UV_CACHE_DIR=/tmp/uv-cache",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
        ]  # fmt: skip
        for name in FORWARDED_ENV:
            if name in os.environ:
                cmd += ["-e", f"{name}={os.environ[name]}"]
        return [*cmd, self.image, *args]


def _host_command(args: list[str]) -> tuple[list[str], dict[str, str]]:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return args, env


def sync_dependencies(root: Path, sandbox: Sandbox | None) -> None:
    """`uv sync`, in the sandbox when there is one: it runs PR-controlled
    build backends."""
    args = ["uv", "sync", "--all-extras", "--frozen"]
    if sandbox is None:
        cmd, env = _host_command(args)
        cwd: Path | None = root
    else:
        cmd, env, cwd = sandbox.command(root, args), dict(os.environ), None
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False,
        timeout=SYNC_TIMEOUT_SECONDS,
    )  # fmt: skip
    print((proc.stdout + proc.stderr)[-5000:], flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"uv sync failed in the sandbox (exit {proc.returncode})")


def make_runner(sandbox: Sandbox | None) -> Runner:
    def run(root: Path, tests: tuple[str, ...]) -> PytestRun:
        if sandbox is None:
            cmd, env = _host_command(pytest_args(tests))
            cwd: Path | None = root
        else:
            cmd, env, cwd = sandbox.command(root, pytest_args(tests)), dict(os.environ), None
        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False,
                timeout=PYTEST_TIMEOUT_SECONDS,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return PytestRun(-1, (), 0, time.monotonic() - started)
        output = proc.stdout + proc.stderr
        print(output[-20000:], flush=True)
        failing, passed, skipped, xfail = parse_pytest_output(output)
        elapsed = time.monotonic() - started
        return PytestRun(proc.returncode, failing, passed, elapsed, skipped, xfail)

    return run


#: Runs the named tests in `root`. Injected so the git machinery is testable
#: without a pytest-in-pytest.
Runner = Callable[[Path, tuple[str, ...]], PytestRun]


def classify(run: PytestRun) -> Outcome:
    """A kill needs a failure ON RECORD: exit 1 (failed) or 2 (collection
    error) AND a FAILED/ERROR line. An interrupt also exits 2, with none."""
    if run.exit_code == 0:
        return Outcome.SURVIVED
    if run.exit_code in {1, 2} and run.failing:
        return Outcome.KILLED
    return Outcome.ERROR


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def evaluate_patch(root: Path, patch: Path, inputs: Inputs, runner: Runner) -> PatchResult:
    name = patch.name
    numstat = _git(root, "apply", "--numstat", "-z", str(patch))
    check = _git(root, "apply", "--check", str(patch))
    if numstat.returncode != 0 or check.returncode != 0:
        why = (check.stderr or numstat.stderr).strip()[:300]
        return PatchResult(name, Outcome.APPLY_FAILED, detail=why)
    summary = _git(root, "apply", "--summary", str(patch)).stdout
    if renames := [line.strip() for line in summary.splitlines() if is_rename_or_copy(line)]:
        # numstat names only a rename's DESTINATION, so the source (which may
        # be ignored, or a test) would escape vetting. A mutation never needs one.
        return PatchResult(name, Outcome.REFUSED, detail=f"renames or copies: {renames}")
    declared = parse_numstat(numstat.stdout)
    if not declared:
        return PatchResult(name, Outcome.NOT_APPLIED, detail="patch names no files")
    problems = vet_paths(root, declared, inputs)
    if problems:
        return PatchResult(name, Outcome.REFUSED, files=tuple(declared), detail="; ".join(problems))
    applied = _git(root, "apply", str(patch))
    if applied.returncode != 0:
        return PatchResult(name, Outcome.APPLY_FAILED, detail=applied.stderr.strip()[:300])
    files = tuple(changed_paths(root))
    if not files:
        return PatchResult(name, Outcome.NOT_APPLIED, detail="patch applied but changed nothing")
    if undeclared := sorted(set(files) - set(declared)):
        return PatchResult(
            name, Outcome.REFUSED, files=files, detail=f"changed undeclared paths {undeclared}"
        )
    clear_bytecode(root)
    run = runner(root, inputs.tests)
    outcome = classify(run)
    detail = (
        "" if outcome is not Outcome.ERROR else f"pytest exit {run.exit_code}, no failure on record"
    )
    return PatchResult(name, outcome, files, run.failing, run.seconds, detail)


def execute(root: Path, inputs: Inputs, sha: str, runner: Runner) -> Evidence:
    evidence = Evidence(pr=inputs.pr, sha=sha, tests=inputs.tests)
    for test_file in sorted(inputs.test_files):
        if not resolve_inside(root, PurePosixPath(test_file), "test path").is_file():
            raise InputError(f"test file {test_file} does not exist on the PR head")
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
    elif evidence.baseline.skipped:
        # A skipped test passes under every mutant, so it would turn real
        # coverage into a SURVIVED (or hide a gap behind other kills). Usually
        # a Docker-backed test in sandbox mode (docker=false).
        evidence.baseline_detail = (
            f"baseline skipped {evidence.baseline.skipped} test(s), evidence void "
            "(Docker-backed? dispatch with docker=true)"
        )
    elif evidence.baseline.xfail:
        # xfail and xpass are not passes either: an xfail(run=False) never
        # executes, and a non-strict xpass is green whether or not it works.
        evidence.baseline_detail = (
            f"baseline has {evidence.baseline.xfail} xfailed/xpassed test(s), evidence void"
        )
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
    """Text that came out of PR code, made safe to sit inside a code span."""
    cleaned = text.replace("`", "'").replace("|", "\\|").replace("\n", " ").replace("@", "@\u200b")
    return cleaned[:300]


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
            result = r.outcome.value + (f" `{_cell(r.detail)}`" if r.detail else "")
            lines.append(
                f"| `{_cell(r.patch)}` | {_code(r.files)} | {result} | "
                f"{_code(r.failing)} | {r.seconds:.1f}s |"
            )
        lines.append("")
    lines += [
        "A kill proves the named test catches the mutant. A survival is against the",
        "named tests only. Patches are evidence for this PR: delete `.mutations/`",
        "before merge (CI enforces it); this comment is the record.",
    ]
    return "\n".join(lines) + "\n"


def render_error(pr: int, sha: str, run_url: str, message: str) -> str:
    return (
        f"{MARKER}\n## Mutation evidence\n\n**FAIL** | PR #{pr} | head `{sha}` | "
        f"[run]({run_url})\n\n`{_cell(message)}`\n"
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
    run = sub.add_parser("run", help="baseline + every patch against a PR checkout")
    run.add_argument("--root", type=Path, required=True, help="the PR checkout")
    run.add_argument("--report", type=Path, required=True)
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--image", help="run PR code in this container image (sandbox)")
    mode.add_argument(
        "--host",
        action="store_true",
        help="run PR code on the host, for tests that need the Docker daemon",
    )
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
    root: Path = args.root.resolve()
    sandbox = None if args.host else Sandbox(args.image)
    try:
        sync_dependencies(root, sandbox)
        evidence = execute(root, inputs, sha, make_runner(sandbox))
    except (InputError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"::error::{exc}")
        report.write_text(render_error(inputs.pr, sha, _run_url(), str(exc)))
        return 1
    report.write_text(render(evidence, _run_url()))
    print(report.read_text())
    return 0 if evidence.ok else 1


if __name__ == "__main__":
    sys.exit(main())
