"""Fail when a CI job that gates a PR has no local equivalent in `just qa-ci`.

`just qa-ci` exists so that one local command answers "will CI pass". That
answer decays silently: someone adds a job, it runs only on GitHub, and qa-ci
keeps printing its success line. The mapping below is the contract, and this
script is what holds it.

Two things this deliberately does NOT claim, because the first version of it
claimed both and neither was true:

- It compares JOBS, not steps. Adding a step to an existing job, widening a
  matrix, or changing what a reusable workflow does is invisible here. Job-level
  coverage is the floor, not a proof of equivalence.
- Running the same command is not running it in the same environment. CI is
  Ubuntu with pinned toolchains and a clean checkout; a local run is not. See
  `qa-ci` in the justfile for the wording that is actually true.

It discovers the workflows itself rather than reading a hardcoded list, because
a hardcoded list is the same drift bug one level up.

Exit 1 if a job is unmapped, a mapped target is missing from the justfile, a
mapped target is not reachable from `qa-ci`, or a mapping names a job that no
longer exists.
"""

from __future__ import annotations

import platform
import re
import sys
from pathlib import Path
from typing import Final

import yaml

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
WORKFLOW_DIR: Final = REPO_ROOT / ".github" / "workflows"
JUSTFILE: Final = REPO_ROOT / "justfile"

QA_CI_TARGET: Final = "qa-ci"

#: "<workflow file>:<job id>" -> the just target that runs the same commands.
LOCAL_EQUIVALENT: Final[dict[str, str]] = {
    "ci.yml:python-qa": "preflight",
    "ci.yml:architectural-fitness": "preflight",
    "ci.yml:python-unit-tests": "test-unit-ci",
    "ci.yml:dashboard-ui": "dashboard-ci",
    "ci.yml:docs-site": "docs-site-ci",
    "ci.yml:cli-node": "cli-node-ci",
    "ci.yml:submodule-check": "check-submodules",
    "ci.yml:default-workspace-image": "check-default-workspace-image",
    "docs-lint.yml:lint-content": "check-docs-content",
}

#: Jobs with no local target, split by WHY. The first version of this file had
#: one bucket and one prose reason each, and several of those reasons were
#: false: it said osv-scan and pip-audit could not run locally while
#: `just deps-audit-npm` and `just deps-audit-py` already ran exactly those
#: tools, and it said integration tests are skipped on PR branches when ci.yml
#: runs them for PRs targeting `release`. A reason that sounds plausible and is
#: wrong is worse than no reason, so the categories are now distinguishable.

#: Genuinely cannot run outside GitHub.
IMPOSSIBLE_LOCALLY: Final[dict[str, str]] = {
    "ci.yml:dependency-review": "a GitHub action reading the PR's base/head dependency graph",
    "release-gate.yml:dependency-review": "same GitHub action",
    "release-gate.yml:changelog-check": "reads the pull request body through the GitHub API",
}

#: Aggregator jobs: they assert other jobs succeeded and check nothing themselves.
AGGREGATOR_ONLY: Final[frozenset[str]] = frozenset(
    {
        "ci.yml:ci-success",
        "e2e-container.yml:e2e-success",
        "release-gate.yml:release-gate-success",
    }
)

#: Does not run on an ordinary feature-branch PR at all, with the condition that
#: decides it. These are not coverage gaps for the PRs qa-ci is run against.
NOT_RUN_ON_FEATURE_PR: Final[dict[str, str]] = {
    "ci.yml:python-integration-tests": "runs only for PRs with base_ref == release",
    "e2e-container.yml:e2e-container": "gated on the run_full_e2e workflow_dispatch input",
    "release-gate.yml:version-check": "release-gate.yml targets the release branch only",
    "release-gate.yml:codegen-sync": "release-gate.yml targets the release branch only",
    "release-gate.yml:docker-dry-run": "release-gate.yml targets the release branch only",
    "release-gate.yml:osv-scan": "release-gate.yml targets the release branch only",
    "release-gate.yml:pip-audit": "release-gate.yml targets the release branch only",
}

#: CAN run locally; deliberately outside qa-ci, naming the target that does run
#: it. Anyone can close these gaps by hand before pushing, which is only true
#: because this table says so rather than claiming they are unreachable.
RUNNABLE_BUT_EXCLUDED: Final[dict[str, str]] = {
    "ci.yml:osv-scan": "network round-trip to the OSV database; `just deps-audit-npm`",
    "ci.yml:pip-audit": "network round-trip to the PyPI advisory database; `just deps-audit-py`",
    "e2e-container.yml:docker-build": "builds a multi-gigabyte image; `just workspace-build`",
}


def unmapped_reasons() -> dict[str, str]:
    """Every job that has no local target, with its reason."""
    reasons = {job: f"impossible locally: {why}" for job, why in IMPOSSIBLE_LOCALLY.items()}
    reasons.update(dict.fromkeys(AGGREGATOR_ONLY, "aggregator job, checks nothing itself"))
    reasons.update(
        {job: f"not run on a feature PR: {why}" for job, why in NOT_RUN_ON_FEATURE_PR.items()}
    )
    reasons.update(
        {job: f"runnable locally, excluded: {why}" for job, why in RUNNABLE_BUT_EXCLUDED.items()}
    )
    return reasons


def pr_triggered_workflows(workflow_dir: Path) -> dict[str, dict[str, object]]:
    """Every workflow that runs on `pull_request`, keyed by file name.

    Discovered, not listed: a hardcoded set of files would drift exactly the way
    the job mapping drifts, and nothing would catch it.
    """
    found: dict[str, dict[str, object]] = {}
    for path in sorted(workflow_dir.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text())
        if not isinstance(document, dict):
            continue
        # PyYAML resolves the bare key `on` to the boolean True.
        triggers = document.get("on", document.get(True))
        names = set(triggers) if isinstance(triggers, (dict, list)) else {triggers}
        if "pull_request" in names:
            found[path.name] = document
    return found


def job_ids(document: dict[str, object]) -> list[str]:
    """The job ids of one parsed workflow."""
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        raise SystemExit("workflow has no `jobs:` mapping")
    return [str(name) for name in jobs]


def just_targets(justfile: str) -> set[str]:
    """Every recipe name DEFINED in the justfile, not merely mentioned."""
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


def ci_python_version(workflow: str) -> str | None:
    """The Python minor version CI pins, or None if it pins none."""
    match = re.search(r'python-version:\s*"?(\d+\.\d+)"?', workflow)
    return match.group(1) if match else None


def local_python_version() -> str:
    """The running interpreter's minor version, e.g. "3.12"."""
    major, minor, *_ = platform.python_version_tuple()
    return f"{major}.{minor}"


def find_problems(
    workflows: dict[str, dict[str, object]], justfile: str
) -> tuple[list[str], int, int]:
    """Every way the mapping and the justfile currently disagree."""
    targets = just_targets(justfile)
    reachable = qa_ci_dependencies(justfile)

    unmapped = unmapped_reasons()
    problems: list[str] = []
    keys: set[str] = set()
    covered = 0

    for filename, document in sorted(workflows.items()):
        for job in job_ids(document):
            key = f"{filename}:{job}"
            keys.add(key)
            if key in LOCAL_EQUIVALENT:
                target = LOCAL_EQUIVALENT[key]
                if target not in targets:
                    problems.append(f"{key} maps to just target {target!r}, which does not exist")
                elif target not in reachable:
                    problems.append(
                        f"{key} maps to {target!r}, which `{QA_CI_TARGET}` does not run"
                    )
                else:
                    covered += 1
            elif key not in unmapped:
                problems.append(
                    f"{key} has no entry in scripts/check_ci_parity.py. Add it to "
                    f"LOCAL_EQUIVALENT (and to `{QA_CI_TARGET}`), or to one of "
                    f"IMPOSSIBLE_LOCALLY / AGGREGATOR_ONLY / NOT_RUN_ON_FEATURE_PR "
                    f"/ RUNNABLE_BUT_EXCLUDED with the reason."
                )

    for stale in sorted((set(LOCAL_EQUIVALENT) | set(unmapped)) - keys):
        problems.append(
            f"{stale!r} is mapped in check_ci_parity.py but is no longer a "
            f"pull_request-triggered job"
        )

    return problems, covered, len(keys)


def main() -> int:
    workflows = pr_triggered_workflows(WORKFLOW_DIR)
    if not workflows:
        print("❌ no pull_request-triggered workflows found; refusing to report parity")
        return 1

    problems, covered, total = find_problems(workflows, JUSTFILE.read_text())

    if problems:
        print("❌ local QA has drifted from CI:")
        for problem in problems:
            print(f"   - {problem}")
        return 1

    # A warning, not a failure: the fix is to install another interpreter, and
    # that is the repo owner's call, not something a lint should force. See #1018.
    pinned = ci_python_version((WORKFLOW_DIR / "ci.yml").read_text())
    local = local_python_version()
    if pinned is not None and pinned != local:
        print(
            f"⚠️  Python {local} locally, {pinned} in CI. Test results here are "
            f"not evidence about the interpreter CI runs (see #1018)."
        )

    print(
        f"✓ CI parity: {covered} of {total} pull_request-triggered jobs across "
        f"{len(workflows)} workflows run locally via `just {QA_CI_TARGET}`."
    )
    print(
        f"  Of the rest: {len(IMPOSSIBLE_LOCALLY)} impossible locally, "
        f"{len(AGGREGATOR_ONLY)} aggregators, {len(NOT_RUN_ON_FEATURE_PR)} not run "
        f"on a feature PR, and {len(RUNNABLE_BUT_EXCLUDED)} that DO run locally "
        f"but are excluded on cost:"
    )
    for job, why in sorted(RUNNABLE_BUT_EXCLUDED.items()):
        print(f"    {job} -- {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
