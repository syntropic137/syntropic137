"""The evidence contract parses what ADR-014 §10 allows and refuses the rest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    SCHEMA_FILES,
    EvidenceManifest,
    EvidenceReport,
    EvidenceRequest,
    StepOutcome,
    render_schema,
)

_REPO_ROOT = Path(__file__).resolve().parents[7]
_SCHEMA_DIR = _REPO_ROOT / "schemas" / "evidence"

_SHA = "a" * 40
_SHA2 = "b" * 40
_TEST = "packages/x/test_y.py::TestZ::test_w[case-1]"


def _request(**overrides: object) -> str:
    entry = {
        "kind": "integration",
        "repository": "syntropic137/syntropic137",
        "branch": "feat/x",
        "pr": 123,
        "head_sha": _SHA,
        "tests": [_TEST],
    }
    return json.dumps({**entry, **overrides})


def _report(**overrides: object) -> str:
    report = {
        "schema": 1,
        "kind": "integration",
        "pr": 123,
        "head_sha": _SHA,
        "dispatch_id": "0b7d6c1e-2f4a-4c39-9d1a-5e8f3b2a1c00",
        "verdict": "passed",
        "requested": [{"id": _TEST, "outcome": "passed"}],
        "suite": {"collected": 10, "passed": 9, "failed": 0, "skipped": 1},
        "summary": "all green",
        "report_md": "# Integration evidence\n",
    }
    return json.dumps({**report, **overrides})


def _step(index: int, kind: str, outcome: str, **extra: object):
    return {"index": index, "kind": kind, "outcome": outcome, **extra}


def _manifest(**overrides: object) -> str:
    manifest = {
        "schema": 1,
        "gate_id": "gate-1",
        "steps": [
            _step(0, "mutation", "passed", run_url="https://github.com/o/r/actions/runs/1"),
            _step(1, "remove_mutation_patches", "passed", head_sha=_SHA2),
            _step(2, "integration", "unavailable", reason="workflow_absent"),
        ],
        "patch_removal": {"before_sha": _SHA, "after_sha": _SHA2, "author": "syn-app[bot]"},
        "complete": True,
    }
    return json.dumps({**manifest, **overrides})


def _round_trips(model: type[BaseModel], text: str) -> None:
    parsed = model.model_validate_json(text)
    dumped = parsed.model_dump_json(by_alias=True, exclude_none=True)
    # An explicit null and an absent optional are the same document.
    sent = {key: value for key, value in json.loads(text).items() if value is not None}
    assert json.loads(dumped) == sent
    assert model.model_validate_json(dumped) == parsed


@pytest.mark.unit
class TestRoundTrips:
    def test_request(self) -> None:
        _round_trips(EvidenceRequest, _request(kind="mutation"))

    def test_report_keeps_the_wire_name_schema(self) -> None:
        _round_trips(EvidenceReport, _report())

    def test_void_report_with_skipped_requested_test(self) -> None:
        _round_trips(
            EvidenceReport,
            _report(verdict="void", requested=[{"id": _TEST, "outcome": "skipped"}]),
        )

    def test_manifest(self) -> None:
        _round_trips(EvidenceManifest, _manifest())

    def test_manifest_with_a_reused_step_and_no_removal(self) -> None:
        steps = [_step(0, "mutation", "passed", reused_from={"gate_id": "gate-0", "step": 0})]
        _round_trips(EvidenceManifest, _manifest(steps=steps, patch_removal=None))


@pytest.mark.unit
class TestUnknownFieldsAreRefused:
    def test_request(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            EvidenceRequest.model_validate_json(_request(docker=True))

    def test_report(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            EvidenceReport.model_validate_json(_report(killed=3))

    def test_nested_requested_entry(self) -> None:
        requested = [{"id": _TEST, "outcome": "passed", "duration": 1.0}]
        with pytest.raises(ValidationError, match="extra"):
            EvidenceReport.model_validate_json(_report(requested=requested))

    def test_manifest_step(self) -> None:
        steps = [_step(0, "integration", "passed", note="x")]
        with pytest.raises(ValidationError, match="extra"):
            EvidenceManifest.model_validate_json(_manifest(steps=steps, patch_removal=None))


@pytest.mark.unit
class TestInvalidRequests:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            pytest.param("tests", [], id="no-tests"),
            pytest.param("tests", ["test_y.py; rm -rf /"], id="malformed-node-id"),
            pytest.param("tests", ["packages/x/test_y"], id="node-id-without-py"),
            pytest.param("tests", [_TEST] * 51, id="over-the-limit"),
            pytest.param("kind", "docker", id="unknown-kind"),
            pytest.param("head_sha", "A" * 40, id="uppercase-sha"),
            pytest.param("head_sha", _SHA[:39], id="short-sha"),
            pytest.param("pr", 0, id="pr-zero"),
            pytest.param("repository", "not-a-slug", id="repository-not-owner-name"),
            pytest.param("branch", "", id="empty-branch"),
        ],
    )
    def test_refused(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError):
            EvidenceRequest.model_validate_json(_request(**{field: value}))


@pytest.mark.unit
class TestInvalidReports:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            pytest.param("schema", 2, id="unknown-schema-version"),
            pytest.param("verdict", "killed", id="unknown-verdict"),
            pytest.param("requested", [], id="no-requested-tests"),
            pytest.param("requested", [{"id": _TEST, "outcome": "survived"}], id="unknown-outcome"),
            pytest.param("dispatch_id", "has space", id="malformed-dispatch-id"),
            pytest.param(
                "suite",
                {"collected": -1, "passed": 0, "failed": 0, "skipped": 0},
                id="negative-count",
            ),
        ],
    )
    def test_refused(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError):
            EvidenceReport.model_validate_json(_report(**{field: value}))

    @pytest.mark.parametrize("outcome", ["failed", "skipped", "xfail", "not_collected"])
    def test_passed_with_a_requested_test_that_did_not_pass(self, outcome: str) -> None:
        requested = [{"id": _TEST, "outcome": outcome}]
        with pytest.raises(ValidationError, match="requested tests did not pass"):
            EvidenceReport.model_validate_json(_report(requested=requested))

    def test_integration_passed_with_a_failing_suite(self) -> None:
        suite = {"collected": 10, "passed": 9, "failed": 1, "skipped": 0}
        with pytest.raises(ValidationError, match="no failures"):
            EvidenceReport.model_validate_json(_report(suite=suite))

    def test_failed_with_a_failing_suite_is_a_report(self) -> None:
        suite = {"collected": 10, "passed": 9, "failed": 1, "skipped": 0}
        report = EvidenceReport.model_validate_json(_report(verdict="failed", suite=suite))
        assert report.suite.failed == 1

    def test_a_requested_id_named_twice(self) -> None:
        requested = [{"id": _TEST, "outcome": "passed"}] * 2
        with pytest.raises(ValidationError, match="twice"):
            EvidenceReport.model_validate_json(_report(requested=requested))


@pytest.mark.unit
class TestInvalidManifests:
    @pytest.mark.parametrize("outcome", [StepOutcome.VOID, StepOutcome.UNAVAILABLE])
    @pytest.mark.parametrize("reason", [None, "   "])
    def test_no_evidence_without_a_reason(self, outcome: StepOutcome, reason: str | None) -> None:
        steps = [_step(0, "integration", outcome.value, reason=reason)]
        with pytest.raises(ValidationError):
            EvidenceManifest.model_validate_json(_manifest(steps=steps, patch_removal=None))

    def test_incomplete_manifest(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceManifest.model_validate_json(_manifest(complete=False))

    def test_a_missing_step(self) -> None:
        steps = [_step(0, "mutation", "passed"), _step(2, "integration", "passed")]
        with pytest.raises(ValidationError, match="none missing"):
            EvidenceManifest.model_validate_json(_manifest(steps=steps, patch_removal=None))

    def test_no_steps(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceManifest.model_validate_json(_manifest(steps=[], patch_removal=None))

    def test_passed_removal_without_provenance(self) -> None:
        with pytest.raises(ValidationError, match="patch_removal"):
            EvidenceManifest.model_validate_json(_manifest(patch_removal=None))

    def test_provenance_without_a_passed_removal(self) -> None:
        steps = [_step(0, "remove_mutation_patches", "void", reason="head moved")]
        with pytest.raises(ValidationError, match="patch_removal"):
            EvidenceManifest.model_validate_json(_manifest(steps=steps))

    def test_a_removal_that_did_not_move_the_head(self) -> None:
        removal = {"before_sha": _SHA, "after_sha": _SHA, "author": "syn-app[bot]"}
        with pytest.raises(ValidationError, match="move the head"):
            EvidenceManifest.model_validate_json(_manifest(patch_removal=removal))


@pytest.mark.unit
class TestCheckedInSchemas:
    @pytest.mark.parametrize(("name", "model"), SCHEMA_FILES, ids=[n for n, _ in SCHEMA_FILES])
    def test_matches_the_model(self, name: str, model: type[BaseModel]) -> None:
        path = _SCHEMA_DIR / name
        assert path.exists(), f"{path} is missing"
        assert path.read_text() == render_schema(model), (
            f"{name} has drifted from {model.__name__}. "
            "Run: uv run python scripts/export_evidence_schemas.py"
        )

    def test_the_wire_name_is_schema(self) -> None:
        # A consumer validating evidence.json in another repository reads
        # these files, not the model, so the alias must reach them.
        document = json.loads((_SCHEMA_DIR / "evidence-report.schema.json").read_text())
        assert "schema" in document["required"]
        assert "schema_version" not in document["properties"]
        assert document["additionalProperties"] is False
