"""Tests for syn_api.types — Result type and Pydantic models."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from syn_api.types import (
    ArtifactError,
    ArtifactSummary,
    Err,
    ExecutionDetail,
    ExecutionSummary,
    GitHubError,
    ObservabilityError,
    Ok,
    SessionError,
    SessionSummary,
    WorkflowDetail,
    WorkflowError,
    WorkflowSummary,
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class TestOk:
    def test_ok_holds_value(self):
        result = Ok(42)
        assert result.value == 42

    def test_ok_is_frozen(self):
        result = Ok("hello")
        with pytest.raises(AttributeError):
            result.value = "world"  # type: ignore[misc]

    def test_ok_with_list(self):
        result = Ok([1, 2, 3])
        assert result.value == [1, 2, 3]

    def test_ok_with_none(self):
        result = Ok(None)
        assert result.value is None


class TestErr:
    def test_err_holds_error(self):
        result = Err(WorkflowError.NOT_FOUND)
        assert result.error == WorkflowError.NOT_FOUND
        assert result.message is None

    def test_err_with_message(self):
        result = Err(WorkflowError.NOT_FOUND, message="Workflow xyz not found")
        assert result.error == WorkflowError.NOT_FOUND
        assert result.message == "Workflow xyz not found"

    def test_err_is_frozen(self):
        result = Err(WorkflowError.NOT_FOUND)
        with pytest.raises(AttributeError):
            result.error = WorkflowError.ALREADY_EXISTS  # type: ignore[misc]


class TestResultMatching:
    def test_match_ok(self):
        result: Ok[int] | Err[WorkflowError] = Ok(42)
        match result:
            case Ok(value):
                assert value == 42
            case Err():
                pytest.fail("Should not match Err")

    def test_match_err(self):
        result: Ok[int] | Err[WorkflowError] = Err(WorkflowError.NOT_FOUND, message="gone")
        match result:
            case Ok():
                pytest.fail("Should not match Ok")
            case Err(error, message):
                assert error == WorkflowError.NOT_FOUND
                assert message == "gone"

    def test_isinstance_check(self):
        ok_result: Ok[int] | Err[WorkflowError] = Ok(1)
        err_result: Ok[int] | Err[WorkflowError] = Err(WorkflowError.NOT_FOUND)

        assert isinstance(ok_result, Ok)
        assert not isinstance(ok_result, Err)
        assert isinstance(err_result, Err)
        assert not isinstance(err_result, Ok)


# ---------------------------------------------------------------------------
# Error enums
# ---------------------------------------------------------------------------


class TestErrorEnums:
    def test_workflow_error_values(self):
        assert WorkflowError.NOT_FOUND == "not_found"
        assert WorkflowError.ALREADY_EXISTS == "already_exists"
        assert WorkflowError.INVALID_INPUT == "invalid_input"
        assert WorkflowError.EXECUTION_FAILED == "execution_failed"
        assert WorkflowError.NOT_IMPLEMENTED == "not_implemented"

    def test_session_error_values(self):
        assert SessionError.NOT_FOUND == "not_found"
        assert SessionError.ALREADY_COMPLETED == "already_completed"

    def test_artifact_error_values(self):
        assert ArtifactError.NOT_IMPLEMENTED == "not_implemented"

    def test_github_error_values(self):
        assert GitHubError.NOT_IMPLEMENTED == "not_implemented"
        assert GitHubError.AUTH_REQUIRED == "auth_required"

    def test_observability_error_values(self):
        assert ObservabilityError.QUERY_FAILED == "query_failed"


# ---------------------------------------------------------------------------
# Pydantic models serialization
# ---------------------------------------------------------------------------


class TestWorkflowSummary:
    def test_create_from_dict(self):
        wf = WorkflowSummary(
            id="wf-123",
            name="Research Workflow",
            workflow_type="research",
            classification="standard",
            phase_count=3,
        )
        assert wf.id == "wf-123"
        assert wf.name == "Research Workflow"
        assert wf.phase_count == 3
        assert wf.runs_count == 0

    def test_serialization_round_trip(self):
        wf = WorkflowSummary(
            id="wf-123",
            name="Test",
            workflow_type="custom",
            classification="standard",
            phase_count=1,
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            runs_count=5,
        )
        data = wf.model_dump()
        wf2 = WorkflowSummary.model_validate(data)
        assert wf == wf2


class TestWorkflowDetail:
    def test_create_with_phases(self):
        detail = WorkflowDetail(
            id="wf-123",
            name="Multi-Phase",
            workflow_type="implementation",
            classification="advanced",
            phases=[],
        )
        assert detail.id == "wf-123"
        assert detail.phases == []


class TestExecutionSummary:
    def test_create_with_cost(self):
        ex = ExecutionSummary(
            workflow_execution_id="exec-1",
            workflow_id="wf-1",
            workflow_name="Test",
            status="completed",
            total_cost_usd=Decimal("1.50"),
            total_tokens=10000,
            repos=["https://github.com/org/repo"],
        )
        assert ex.total_cost_usd == Decimal("1.50")
        assert ex.total_tokens == 10000


class TestExecutionDetail:
    def test_default_values(self):
        detail = ExecutionDetail(
            workflow_execution_id="exec-1",
            workflow_id="wf-1",
            workflow_name="Test",
            status="pending",
            repos=[],
        )
        assert detail.total_input_tokens == 0
        assert detail.artifact_ids == []


class TestSessionSummary:
    def test_create_minimal(self):
        session = SessionSummary(id="sess-1")
        assert session.id == "sess-1"
        assert session.total_tokens == 0
        assert session.total_cost_usd == Decimal("0")


class TestArtifactSummary:
    def test_create_minimal(self):
        artifact = ArtifactSummary(id="art-1")
        assert artifact.id == "art-1"
        assert artifact.size_bytes == 0
