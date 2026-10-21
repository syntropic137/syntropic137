"""The two evidence workflows keep the contract the platform's evidence gate
reads (plan docs/plans/20261015_platform-dispatched-evidence.md §A.1, PR 3).

The gate dispatches `<kind>-evidence.yml` with `pr`, `tests` and `dispatch_id`,
finds its run by the nonce in the run name, and downloads an artifact named
`evidence` holding `evidence.json`. Each of those is a string in YAML that no
type checker sees, so each is pinned here.

PC-197: a concurrency group per PR let a second dispatch cancel the first. The
group must carry the dispatch nonce, fall back to the run id, and never cancel.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest
import yaml

pytestmark = pytest.mark.unit

WORKFLOWS: Final = Path(__file__).resolve().parents[2] / ".github" / "workflows"
KINDS: Final = ("mutation", "integration")
EVIDENCE_PATH: Final = "${{ runner.temp }}/evidence/evidence.json"
_PINNED_USES: Final = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _load(kind: str) -> dict[object, object]:
    document = yaml.safe_load((WORKFLOWS / f"{kind}-evidence.yml").read_text())
    assert isinstance(document, dict)
    return document


def _mapping(value: object) -> dict[object, object]:
    assert isinstance(value, dict), value
    return value


def _steps(document: dict[object, object]) -> list[dict[object, object]]:
    steps: list[dict[object, object]] = []
    for job in _mapping(document["jobs"]).values():
        raw = _mapping(job).get("steps", [])
        assert isinstance(raw, list)
        steps.extend(_mapping(step) for step in raw)
    return steps


@pytest.mark.parametrize("kind", KINDS)
def test_concurrency_is_per_dispatch_and_never_cancels(kind: str) -> None:
    concurrency = _mapping(_load(kind)["concurrency"])
    assert concurrency["group"] == (
        f"{kind}-evidence-pr-${{{{ inputs.pr }}}}-${{{{ inputs.dispatch_id || github.run_id }}}}"
    )
    assert concurrency["cancel-in-progress"] is False


@pytest.mark.parametrize("kind", KINDS)
def test_dispatch_only_with_the_gate_inputs(kind: str) -> None:
    document = _load(kind)
    # PyYAML reads the bare key `on` as True.
    triggers = _mapping(document[True])
    assert set(triggers) == {"workflow_dispatch"}
    inputs = _mapping(_mapping(triggers["workflow_dispatch"])["inputs"])
    assert {"pr", "tests", "dispatch_id"} <= set(inputs)
    run_name = document["run-name"]
    assert isinstance(run_name, str)
    assert "${{ inputs.pr }}" in run_name and "${{ inputs.dispatch_id }}" in run_name


@pytest.mark.parametrize("kind", KINDS)
def test_uploads_evidence_json_as_the_evidence_artifact(kind: str) -> None:
    steps = _steps(_load(kind))
    uploads = [
        _mapping(step["with"])
        for step in steps
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        and _mapping(step["with"])["name"] == "evidence"
    ]
    assert len(uploads) == 1
    assert uploads[0]["path"] == EVIDENCE_PATH
    # The runner writes the file the artifact uploads.
    runs = [str(step["run"]) for step in steps if "run" in step]
    assert any(
        f"{kind}_evidence.py run" in run
        and '--evidence "$RUNNER_TEMP/evidence/evidence.json"' in run
        for run in runs
    )


@pytest.mark.parametrize("kind", KINDS)
def test_no_expression_reaches_a_shell_directly(kind: str) -> None:
    # Script injection: an input expanded inside `run:` is shell source. Every
    # value goes through `env:` instead.
    for step in _steps(_load(kind)):
        assert "${{" not in str(step.get("run", "")), step.get("name")


@pytest.mark.parametrize("kind", KINDS)
def test_permissions_are_minimal_and_actions_pinned_by_sha(kind: str) -> None:
    document = _load(kind)
    assert document["permissions"] == {}
    for step in _steps(document):
        uses = step.get("uses")
        if uses is None or str(uses).startswith("./"):
            continue
        assert _PINNED_USES.match(str(uses)), uses


#: Exact per-job scopes. The job that runs PR code reads contents and nothing
#: else; the only write scope is the comment job's, on a fresh runner.
JOB_PERMISSIONS: Final = {
    "resolve": {"contents": "read", "pull-requests": "read"},
    "evidence": {"contents": "read"},
    "comment": {"pull-requests": "write"},
}


def _job(document: dict[object, object], job_id: str) -> dict[object, object]:
    return _mapping(_mapping(document["jobs"])[job_id])


def _job_steps(document: dict[object, object], job_id: str) -> list[dict[object, object]]:
    raw = _job(document, job_id).get("steps", [])
    assert isinstance(raw, list)
    return [_mapping(step) for step in raw]


@pytest.mark.parametrize("kind", KINDS)
def test_each_job_has_exactly_its_permissions(kind: str) -> None:
    jobs = _mapping(_load(kind)["jobs"])
    assert set(jobs) == set(JOB_PERMISSIONS)
    for job_id, expected in JOB_PERMISSIONS.items():
        assert _mapping(jobs[job_id])["permissions"] == expected, job_id
    writers = [
        job_id
        for job_id, job in jobs.items()
        if "write" in _mapping(_mapping(job)["permissions"]).values()
    ]
    assert writers == ["comment"]


@pytest.mark.parametrize("kind", KINDS)
def test_fork_prs_are_refused_before_pr_code_is_checked_out(kind: str) -> None:
    document = _load(kind)
    resolve = next(s for s in _job_steps(document, "resolve") if s.get("id") == "head")
    script = str(resolve["run"])
    assert 'head_repo="$(jq -r .head.repo.full_name <<<"$pr_json")"' in script
    refusal = script.split('if [ "$head_repo" != "$REPO" ]; then', 1)[1].split("fi", 1)[0]
    assert "fork PRs are refused" in refusal and "exit 1" in refusal
    # The PR-code job checks out only the head that refusal let through.
    assert _job(document, "evidence")["needs"] == "resolve"


@pytest.mark.parametrize("kind", KINDS)
def test_caches_are_disabled(kind: str) -> None:
    document = _load(kind)
    assert document["cache-mode"] == "none"
    env_steps = [
        _mapping(s["with"])
        for s in _job_steps(document, "evidence")
        if s.get("uses") == "./trusted/.github/actions/python-integration-env"
    ]
    assert len(env_steps) == 1
    assert env_steps[0]["enable-cache"] == "false"
    for step in _steps(document):
        uses = str(step.get("uses", ""))
        assert not uses.startswith("actions/cache"), uses
        assert "cache" not in _mapping(step.get("with", {})), step.get("name")


@pytest.mark.parametrize("kind", KINDS)
def test_checkouts_never_persist_credentials(kind: str) -> None:
    checkouts = [
        _mapping(s.get("with", {}))
        for s in _steps(_load(kind))
        if str(s.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    for checkout in checkouts:
        assert checkout.get("persist-credentials") is False, checkout
    pr_head = [c for c in checkouts if c.get("path") == "pr"]
    assert len(pr_head) == 1
    assert pr_head[0]["ref"] == "${{ needs.resolve.outputs.sha }}"
