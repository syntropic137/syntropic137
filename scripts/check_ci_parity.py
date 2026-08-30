"""Fail when a CI job has no local equivalent in `just qa-ci`.

`just qa-ci` claims that a green local run means a green CI run. That claim
decays the moment someone adds a job to ci.yml, and nothing would notice: the
new job would simply run only on GitHub, and qa-ci would keep printing its
success line.

So the mapping below is the contract, and this script is what holds it. Every
job in ci.yml must appear here, mapped either to the just target that mirrors
it or to an explicit reason it cannot run locally. Adding a CI job without
touching this file is the failure this exists to produce.

Exit code 1 if any job is unmapped, any mapped target is missing from the
justfile, or any mapped target is missing from qa-ci's dependency list.
"""

from __future__ import annotations

import platform
import re
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
CI_WORKFLOW: Final = REPO_ROOT / ".github" / "workflows" / "ci.yml"
JUSTFILE: Final = REPO_ROOT / "justfile"

QA_CI_TARGET: Final = "qa-ci"

# CI job name -> the just target that runs the same commands locally.
LOCAL_EQUIVALENT: Final[dict[str, str]] = {
    "python-qa": "preflight",
    "architectural-fitness": "preflight",
    "python-unit-tests": "test-unit-ci",
    "dashboard-ui": "dashboard-ci",
    "docs-site": "docs-site-ci",
    "cli-node": "cli-node-ci",
    "submodule-check": "check-submodules",
    "default-workspace-image": "preflight",
}

# CI job name -> why it has no local equivalent. A reason is a commitment, not
# a shrug: it says what a local run genuinely cannot reach.
NO_LOCAL_EQUIVALENT: Final[dict[str, str]] = {
    "osv-scan": "queries the remote OSV vulnerability database",
    "pip-audit": "queries the remote PyPI advisory database",
    "dependency-review": "a GitHub API action with no local equivalent",
    "python-integration-tests": "needs live services; CI also skips it on PR branches",
    "ci-success": "an aggregator job, not a check of its own",
}

# python-qa's test-debt step is stricter than `just test-debt`, so qa-ci runs it
# through its own target. Listed here so the dependency check below sees it.
EXTRA_QA_CI_DEPS: Final[frozenset[str]] = frozenset({"check-test-debt"})

_JOB_RE: Final = re.compile(r"^  ([a-z0-9][a-z0-9_-]*):\s*$")

_PY_VERSION_RE: Final = re.compile(r'python-version:\s*"?(\d+\.\d+)"?')


def ci_python_version(workflow: str) -> str | None:
    """The Python minor version CI pins, or None if it pins none."""
    match = _PY_VERSION_RE.search(workflow)
    return match.group(1) if match else None


def local_python_version() -> str:
    """The running interpreter's minor version, e.g. "3.12"."""
    major, minor, *_ = platform.python_version_tuple()
    return f"{major}.{minor}"


def ci_job_names(workflow: str) -> list[str]:
    """Every job key under `jobs:` in the workflow, in file order."""
    lines = workflow.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "jobs:")
    except StopIteration:
        raise SystemExit("no `jobs:` block found in ci.yml") from None
    names: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith((" ", "\t", "#")):
            break  # left the jobs block
        match = _JOB_RE.match(line)
        if match:
            names.append(match.group(1))
    return names


def just_targets(justfile: str) -> set[str]:
    """Every recipe name defined in the justfile."""
    return set(re.findall(r"^([a-z0-9][a-z0-9_-]*)\s*:", justfile, re.MULTILINE))


def qa_ci_dependencies(justfile: str) -> set[str]:
    """Every target `qa-ci` reaches, transitively.

    Transitive rather than direct because a check is just as run when it sits
    inside `preflight`; comparing only the header would report a check as
    missing the moment someone moved it one level down.
    """
    if re.search(rf"^{QA_CI_TARGET}:", justfile, re.MULTILINE) is None:
        raise SystemExit(f"no `{QA_CI_TARGET}` target found in the justfile")
    seen: set[str] = set()
    stack = [QA_CI_TARGET]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        match = re.search(rf"^{re.escape(current)}:([^\n]*)", justfile, re.MULTILINE)
        if match:
            stack.extend(match.group(1).split())
    return seen


def main() -> int:
    workflow = CI_WORKFLOW.read_text()
    justfile = JUSTFILE.read_text()

    jobs = ci_job_names(workflow)
    targets = just_targets(justfile)
    deps = qa_ci_dependencies(justfile)

    problems: list[str] = []

    for job in jobs:
        if job in LOCAL_EQUIVALENT:
            target = LOCAL_EQUIVALENT[job]
            if target not in targets:
                problems.append(
                    f"CI job {job!r} maps to just target {target!r}, which does not exist"
                )
            elif target not in deps:
                problems.append(
                    f"CI job {job!r} maps to {target!r}, which `{QA_CI_TARGET}` does not run"
                )
        elif job not in NO_LOCAL_EQUIVALENT:
            problems.append(
                f"CI job {job!r} has no entry in scripts/check_ci_parity.py. "
                f"Add it to LOCAL_EQUIVALENT (and to `{QA_CI_TARGET}`), or to "
                f"NO_LOCAL_EQUIVALENT with the reason it cannot run locally."
            )

    known = set(LOCAL_EQUIVALENT) | set(NO_LOCAL_EQUIVALENT)
    for stale in sorted(known - set(jobs)):
        problems.append(
            f"{stale!r} is mapped in check_ci_parity.py but is no longer a job in ci.yml"
        )

    for dep in EXTRA_QA_CI_DEPS:
        if dep not in deps:
            problems.append(f"`{QA_CI_TARGET}` no longer runs {dep!r}")

    if problems:
        print("❌ local QA has drifted from CI:")
        for problem in problems:
            print(f"   - {problem}")
        return 1

    # A warning, not a failure: the fix is to install another interpreter, and
    # that is the repo owner's call, not something a lint should force. See #1018.
    pinned = ci_python_version(workflow)
    local = local_python_version()
    if pinned is not None and pinned != local:
        print(
            f"⚠️  Python {local} locally, {pinned} in CI. Test results here are "
            f"not evidence about the interpreter CI runs (see #1018)."
        )

    covered = sum(1 for job in jobs if job in LOCAL_EQUIVALENT)
    print(
        f"✓ CI parity: {covered} of {len(jobs)} ci.yml jobs run locally via "
        f"`just {QA_CI_TARGET}`; the rest are documented as remote-only"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
