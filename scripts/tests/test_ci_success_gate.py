"""'CI Success' is the one required check, so its aggregation must be an allow-list.

It used to fail only on the results it named. A cancelled Python Unit Tests run
on #1576 left 'CI Success' green during the 2026-10-05 Actions outage (#1623),
and the same deny-list also let through a failing or cancelled Default
Workspace Image, a cancelled Submodule Check, and any job that came back
``skipped``.

These tests run the exact script from ``.github/workflows/ci.yml`` (it takes its
inputs from env for this reason) against synthetic ``needs`` results.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
OPTIONAL = {"python-integration-tests", "dependency-review", "mutations-not-merged"}


def _jobs() -> Mapping[object, object]:
    loaded: object = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    assert isinstance(loaded, Mapping)
    jobs: object = loaded["jobs"]
    assert isinstance(jobs, Mapping)
    return jobs


def _gate_job() -> Mapping[object, object]:
    job: object = _jobs()["ci-success"]
    assert isinstance(job, Mapping)
    return job


def _needs() -> list[str]:
    needs = _gate_job()["needs"]
    assert isinstance(needs, list)
    return [str(n) for n in needs]


def _script() -> str:
    steps = _gate_job()["steps"]
    assert isinstance(steps, list)
    step = next(s for s in steps if isinstance(s, dict) and s.get("name") == "Check all jobs")
    run = step["run"]
    assert isinstance(run, str)
    assert "${{" not in run, "inputs must come through env so this test runs the real script"
    return run


def _gate(results: dict[str, str], event: str, ref: str = "", base_ref: str = "") -> int:
    if shutil.which("jq") is None:
        pytest.skip("jq not installed (CI runners have it)")
    needs = {job: {"result": result, "outputs": {}} for job, result in results.items()}
    env = {
        "NEEDS": json.dumps(needs),
        "EVENT": event,
        "REF": ref,
        "BASE_REF": base_ref,
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    proc = subprocess.run(
        ["bash", "-c", _script()], env=env, capture_output=True, text=True, check=False
    )
    return proc.returncode


def _all(result: str = "success") -> dict[str, str]:
    return dict.fromkeys(_needs(), result)


PR_MAIN = {"event": "pull_request", "ref": "refs/pull/1/merge", "base_ref": "main"}
PR_RELEASE = {"event": "pull_request", "ref": "refs/pull/1/merge", "base_ref": "release"}
PUSH_MAIN = {"event": "push", "ref": "refs/heads/main"}


def test_gate_needs_every_other_job() -> None:
    """A job missing from `needs` can fail without blocking anything."""
    assert set(_needs()) == {str(j) for j in _jobs()} - {"ci-success"}


def test_all_success_passes() -> None:
    assert _gate(_all(), **PR_MAIN) == 0


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "neutral", ""])
@pytest.mark.parametrize("job", sorted(set(_needs()) - OPTIONAL))
def test_required_job_must_succeed(job: str, result: str) -> None:
    results = _all()
    results[job] = result
    for ctx in (PR_MAIN, PUSH_MAIN):
        assert _gate(results, **ctx) == 1, f"{job}={result!r} passed on {ctx}"


@pytest.mark.parametrize("result", ["failure", "cancelled"])
@pytest.mark.parametrize("job", sorted(OPTIONAL))
def test_optional_job_never_fails_or_cancels(job: str, result: str) -> None:
    results = _all()
    results[job] = result
    for ctx in (PR_MAIN, PR_RELEASE, PUSH_MAIN):
        assert _gate(results, **ctx) == 1, f"{job}={result!r} passed on {ctx}"


@pytest.mark.parametrize(
    ("job", "ctx", "allowed"),
    [
        ("python-integration-tests", PR_MAIN, True),
        ("python-integration-tests", {"event": "push", "ref": "refs/heads/feature"}, True),
        ("python-integration-tests", PR_RELEASE, False),
        ("python-integration-tests", PUSH_MAIN, False),
        ("python-integration-tests", {"event": "schedule", "ref": "refs/heads/main"}, False),
        ("python-integration-tests", {"event": "workflow_dispatch", "ref": "refs/heads/x"}, False),
        ("dependency-review", PUSH_MAIN, True),
        ("dependency-review", PR_MAIN, False),
        ("dependency-review", PR_RELEASE, False),
        ("mutations-not-merged", PR_RELEASE, True),
        ("mutations-not-merged", PUSH_MAIN, True),
        ("mutations-not-merged", PR_MAIN, False),
    ],
)
def test_skip_allowed_only_where_the_jobs_own_if_skips_it(
    job: str, ctx: dict[str, str], allowed: bool
) -> None:
    results = _all()
    results[job] = "skipped"
    assert _gate(results, **ctx) == (0 if allowed else 1)


@pytest.mark.parametrize(
    "needs",
    [
        "",
        "{}",
        "[]",
        "not json",
        '{"python-qa": 1}',
        '{"python-qa": {}}',
        '{"python-qa": {"result": null}}',
        '{"python-qa": {"result": "success"}, "cli-node": 1}',
        '{"python-qa": {"result": "success"}, "cli-node": {"outputs": {}}}',
    ],
)
def test_malformed_needs_fails(needs: str) -> None:
    """A jq error must never read as "no job failed" (Codex review on #2307)."""
    if shutil.which("jq") is None:
        pytest.skip("jq not installed (CI runners have it)")
    env = {
        "NEEDS": needs,
        "EVENT": "push",
        "REF": "refs/heads/main",
        "BASE_REF": "",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    proc = subprocess.run(
        ["bash", "-c", _script()], env=env, capture_output=True, text=True, check=False
    )
    assert proc.returncode != 0, proc.stdout
