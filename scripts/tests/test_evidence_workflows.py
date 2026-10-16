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
    for job_id, job in _mapping(document["jobs"]).items():
        assert "permissions" in _mapping(job), job_id
    for step in _steps(document):
        uses = step.get("uses")
        if uses is None or str(uses).startswith("./"):
            continue
        assert _PINNED_USES.match(str(uses)), uses
