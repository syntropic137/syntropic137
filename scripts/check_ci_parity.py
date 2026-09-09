"""Fail when a CI job that gates a PR has no local equivalent in `just qa-ci`.

`just qa-ci` exists so that one local command answers "will CI pass". That
answer decays silently: someone adds a job, it runs only on GitHub, and qa-ci
keeps printing its success line. The mapping below is the contract, and this
script is what holds it.

It checks two things. The job mapping below is the first. The second exists
because the job mapping alone was not enough: a gate added as a STEP inside an
already-mapped job was invisible to it (#1124), so `gate_problems()` also walks
what the workflows actually run. What that walk covers, and what it does not:

COVERED - a gate here must be reachable from `just qa-ci` or the check fails:
- a `run:` block naming a `scripts/*.py` or a `just` recipe;
- in a workflow's own steps, in a local composite action (`uses: ./.github/
  actions/...`), or in a local reusable workflow (`uses: ./.github/
  workflows/...`), followed transitively.

NOT COVERED - stated here because an undocumented blind spot is how #1124
arrived in the first place:
- A third-party action (`uses: owner/repo@ref`). Its implementation is not in
  this repository, so nothing here can read what it runs.
- A `run:` block whose gate is bespoke inline shell rather than a named script
  or recipe. Proving an arbitrary shell block is "the same check" as some local
  command needs both executed and their behaviour compared, which is a
  different and far more expensive kind of check than this one.
- Whether a matrix is as wide locally as in CI, and whether the environment
  matches at all. CI is Ubuntu with pinned toolchains and a clean checkout; a
  local run is not. See `qa-ci` in the justfile for the wording that is true.

The way to keep a gate inside those blind spots visible is to give it a name:
put it in a `scripts/*.py` or a `just` recipe, and this file will see it.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

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


#: Gates a PR-gating workflow runs that deliberately have no local equivalent,
#: keyed by the token this file prints ("scripts/x.py" or "just x"). A gate
#: inside a job that is already excluded above is NOT listed here: it inherits
#: its job's recorded reason. An entry here is a decision someone wrote down,
#: not a gap nobody noticed.
STEPS_WITHOUT_A_LOCAL_TARGET: Final[dict[str, str]] = {}

_SCRIPT_RE: Final = re.compile(r"scripts/([a-z0-9_]+\.py)")
#: `just` followed by its recipe words. Flags and shell operators end the run,
#: and which of the captured words are recipes is decided against the justfile.
_JUST_RE: Final = re.compile(r"\bjust\s+((?:[a-z0-9][a-z0-9_-]*\s+)*[a-z0-9][a-z0-9_-]*)")


@dataclass(frozen=True)
class Gate:
    """One command a PR-gating workflow runs, and the path CI took to reach it."""

    kind: Literal["script", "recipe"]
    name: str
    source: str

    @property
    def token(self) -> str:
        """How a human writes this gate, and how the exception table keys it."""
        return f"scripts/{self.name}" if self.kind == "script" else f"just {self.name}"


def _run_gates(script: str, source: str, recipes: set[str]) -> list[Gate]:
    """Every gate one `run:` block invokes.

    A `just` word counts only when the justfile defines a recipe by that name,
    which is what separates a recipe from an argument or from the word "just"
    in prose. A recipe CI names but the justfile does not define is not a parity
    risk: that run fails loudly on the runner the first time it happens.
    """
    gates = [Gate("script", name, source) for name in _SCRIPT_RE.findall(script)]
    for words in _JUST_RE.findall(script):
        gates.extend(Gate("recipe", w, source) for w in words.split() if w in recipes)
    return gates


def _steps_of(document: object) -> list[tuple[str, object]]:
    """The steps a workflow or composite action document runs, with their job id.

    One function for both because the difference between `jobs.<id>.steps` and
    `runs.steps` is a spelling, and the caller has no use for the distinction.
    """
    if not isinstance(document, dict):
        return []
    runs = document.get("runs")
    if isinstance(runs, dict) and isinstance(runs.get("steps"), list):
        return [("", step) for step in runs["steps"]]
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        return []
    found: list[tuple[str, object]] = []
    for job_id, job in jobs.items():
        if isinstance(job, dict):
            found.extend((str(job_id), step) for step in job.get("steps", []) or [])
            if isinstance(job.get("uses"), str):
                found.append((str(job_id), {"uses": job["uses"]}))
    return found


def _resolve_local_uses(reference: str, repo_root: Path) -> Path | None:
    """The file a `uses: ./...` reference names, or None if it is not ours.

    Third-party actions (`owner/repo@ref`) resolve to None on purpose: their
    implementation is not in this repository, so nothing here can read it.
    """
    if not reference.startswith("./"):
        return None
    target = repo_root / reference[2:].split("@")[0]
    if target.is_dir():
        for name in ("action.yml", "action.yaml"):
            if (target / name).is_file():
                return target / name
        return None
    return target if target.is_file() else None


def workflow_gates(document: object, source: str, repo_root: Path, recipes: set[str]) -> list[Gate]:
    """Every gate reachable from a workflow document, following what it calls.

    WHY THIS EXISTS (issue #1124). The job mapping compares JOBS, so a gate
    added as a step inside an existing job is invisible to it, and one already
    was: `scripts/check_openapi_drift.py` ran as a step in `python-qa` with no
    `just` target at all while the parity check reported full coverage.

    Closing that for `scripts/*.py` alone would have repeated the same defect
    one level down - a check that measures one spelling of the thing it claims
    to measure. So this follows every form a gate can take that is written down
    in this repository: a `run:` block naming a script or a `just` recipe, in a
    workflow's own steps, in a local composite action, or in a local reusable
    workflow, transitively and cycle-safe.

    What it cannot see is stated rather than silently skipped: a third-party
    action, and a `run:` block whose gate is bespoke inline shell. See the
    module docstring.
    """

    def walk(document: object, source: str, seen: frozenset[Path]) -> list[Gate]:
        gates: list[Gate] = []
        for job_id, step in _steps_of(document):
            if not isinstance(step, dict):
                continue
            where = f"{source}:{job_id}" if job_id else source
            if isinstance(step.get("run"), str):
                gates.extend(_run_gates(step["run"], where, recipes))
            uses = step.get("uses")
            if not isinstance(uses, str):
                continue
            called = _resolve_local_uses(uses, repo_root)
            if called is None or called in seen:
                continue
            called_document = yaml.safe_load(called.read_text())
            gates.extend(walk(called_document, f"{where} -> {uses}", seen | {called}))
        return gates

    return walk(document, source, frozenset())


def gate_problems(
    workflows: dict[str, dict[str, object]], justfile: str, repo_root: Path = REPO_ROOT
) -> list[str]:
    """Gates CI runs that nothing reachable from `just qa-ci` runs.

    Gates inside a job that is already excluded at the job level are skipped:
    that job's reason is recorded once, and repeating it per step would be the
    same decision maintained in two places.
    """
    reachable = qa_ci_dependencies(justfile)
    bodies = "\n".join(
        match.group(0)
        for target in reachable
        for match in [
            re.search(
                rf"^{re.escape(target)}:.*?(?=\n[a-z0-9_-]+\s*:|\Z)",
                justfile,
                re.MULTILINE | re.DOTALL,
            )
        ]
        if match
    )
    excluded = set(unmapped_reasons())
    problems: list[str] = []
    for filename, document in sorted(workflows.items()):
        accounted = {job for job in job_ids(document) if f"{filename}:{job}" in excluded}
        for gate in workflow_gates(document, filename, repo_root, just_targets(justfile)):
            if gate.source.split(" -> ")[0].removeprefix(f"{filename}:") in accounted:
                continue
            if gate.token in STEPS_WITHOUT_A_LOCAL_TARGET:
                continue
            run_locally = (
                f"scripts/{gate.name}" in bodies
                if gate.kind == "script"
                else gate.name in reachable
            )
            if not run_locally:
                problems.append(
                    f"{gate.source} runs `{gate.token}`, but no target reachable "
                    f"from `just {QA_CI_TARGET}` runs it. Add one, or record it "
                    f"in STEPS_WITHOUT_A_LOCAL_TARGET with a reason."
                )
    return sorted(set(problems))


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

    justfile = JUSTFILE.read_text()
    problems, covered, total = find_problems(workflows, justfile)
    problems.extend(gate_problems(workflows, justfile))

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
