"""Contract tests for ToolOperation field parity across the type stack.

The ToolOperation concept flows through three independent type definitions:

  Layer 1 — syn_adapters.projections.session_tools.ToolOperation (dataclass)
    DB row → read model; source of truth for what's stored

  Layer 2 — syn_api.types.ToolOperation (Pydantic)
    Internal API layer; mapped from Layer 1 via model_validate(from_attributes=True)

  Layer 3 — syn_api.routes.sessions.OperationInfo (Pydantic)
    HTTP API response; mapped from Layer 2 with intentional field renames

Layer 1→2 mapping is self-enforcing: model_validate(from_attributes=True) pulls
all matching fields automatically. These tests catch mismatches *before* runtime.

Layer 2→3 has intentional renames (observation_id→operation_id, duration_ms→
duration_seconds, input_preview→tool_input) plus extra message/token fields.
The tests verify the git-specific fields — the ones most likely to be dropped
silently — are present in all three layers.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC
from typing import ClassVar

import pytest

from syn_adapters.projections.session_tools import ToolOperation as AdaptersToolOperation
from syn_api.routes.sessions import OperationInfo
from syn_api.types import ToolOperation as ApiToolOperation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dataclass_field_names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def _pydantic_field_names(cls: type) -> set[str]:
    return set(cls.model_fields.keys())


# ---------------------------------------------------------------------------
# Layer 1 → Layer 2 parity (dataclass → syn_api.types.ToolOperation)
# ---------------------------------------------------------------------------


@pytest.mark.regression
class TestAdaptersToApiParity:
    """Every field on the adapters dataclass must appear in the API Pydantic model.

    This is the contract that model_validate(from_attributes=True) relies on.
    If a field is added to the dataclass but missing from ApiToolOperation, it
    will be silently dropped at the API layer.
    """

    # Intentional renames: dataclass field -> Pydantic field (via validation_alias)
    _KNOWN_RENAMES: ClassVar[dict[str, str]] = {"git_data": "git"}

    def test_all_dataclass_fields_present_in_api_model(self):
        adapters_fields = _dataclass_field_names(AdaptersToolOperation)
        api_fields = _pydantic_field_names(ApiToolOperation)

        # Account for intentional renames (dataclass name -> Pydantic alias)
        renamed = set(self._KNOWN_RENAMES.keys())
        missing = adapters_fields - api_fields - renamed
        assert missing == set(), (
            f"Fields present in syn_adapters.ToolOperation (dataclass) but missing "
            f"from syn_api.types.ToolOperation (Pydantic): {missing}\n"
            f"Add them to apps/syn-api/src/syn_api/types.py"
        )
        # Verify renamed fields have their Pydantic counterpart
        for dc_name, pydantic_name in self._KNOWN_RENAMES.items():
            assert dc_name in adapters_fields, f"Rename source {dc_name!r} not in dataclass"
            assert pydantic_name in api_fields, (
                f"Rename target {pydantic_name!r} not in Pydantic model"
            )

    def test_git_fields_present_in_api_model(self):
        git_fields = {"git_sha", "git_message", "git_branch", "git_repo"}
        api_fields = _pydantic_field_names(ApiToolOperation)
        missing = git_fields - api_fields
        assert missing == set(), f"Git fields missing from syn_api.types.ToolOperation: {missing}"

    def test_model_validate_roundtrip_preserves_git_fields(self):
        """model_validate(from_attributes=True) must not silently drop git fields."""
        from datetime import datetime

        source = AdaptersToolOperation(
            observation_id="git-abc123",
            tool_name="commit",
            tool_use_id=None,
            operation_type="git_commit",
            timestamp=datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC),
            success=True,
            input_preview=None,
            output_preview=None,
            duration_ms=None,
            git_sha="abc123def456",
            git_message="feat: add regression tests",
            git_branch="feat/github-event-integration",
            git_repo="syntropic137",
        )

        result = ApiToolOperation.model_validate(source, from_attributes=True)

        assert result.observation_id == "git-abc123"
        assert result.operation_type == "git_commit"
        assert result.git_sha == "abc123def456"
        assert result.git_message == "feat: add regression tests"
        assert result.git_branch == "feat/github-event-integration"
        assert result.git_repo == "syntropic137"

    def test_model_validate_roundtrip_preserves_tool_fields(self):
        """All core tool fields must survive the model_validate conversion."""
        from datetime import datetime

        source = AdaptersToolOperation(
            observation_id="tool-use-id-123-2026",
            tool_name="Bash",
            tool_use_id="toolu_abc",
            operation_type="tool_execution_completed",
            timestamp=datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC),
            success=True,
            input_preview='{"command": "git status"}',
            output_preview="On branch main",
            duration_ms=42,
        )

        result = ApiToolOperation.model_validate(source, from_attributes=True)

        assert result.tool_name == "Bash"
        assert result.tool_use_id == "toolu_abc"
        assert result.input_preview == '{"command": "git status"}'
        assert result.output_preview == "On branch main"
        assert result.duration_ms == 42.0  # int → float is fine
        assert result.success is True

    def test_model_validate_roundtrip_preserves_git_data(self):
        """git_data dict on the dataclass maps to git: GitEventData on the Pydantic model."""
        from datetime import datetime

        source = AdaptersToolOperation(
            observation_id="git-push-2026",
            tool_name="push",
            tool_use_id=None,
            operation_type="git_push",
            timestamp=datetime(2026, 4, 12, 12, 0, 0, tzinfo=UTC),
            success=True,
            input_preview=None,
            output_preview=None,
            duration_ms=None,
            git_sha="abc123",
            git_branch="main",
            git_repo="syntropic137",
            git_data={
                "operation": "push",
                "sha": "abc123",
                "branch": "main",
                "repo": "syntropic137",
                "remote": "origin",
            },
        )

        result = ApiToolOperation.model_validate(source, from_attributes=True)

        assert result.git is not None
        assert result.git.operation == "push"
        assert result.git.sha == "abc123"
        assert result.git.branch == "main"
        assert result.git.repo == "syntropic137"
        assert result.git.remote == "origin"
        # Flat fields still populated for backward compat
        assert result.git_sha == "abc123"
        assert result.git_branch == "main"

    def test_model_validate_roundtrip_none_git_data_gives_none_git(self):
        """When git_data is None on the dataclass, git on the Pydantic model is None."""
        from datetime import datetime

        source = AdaptersToolOperation(
            observation_id="tool-123",
            tool_name="Bash",
            tool_use_id="toolu_abc",
            operation_type="tool_execution_completed",
            timestamp=datetime(2026, 4, 12, 12, 0, 0, tzinfo=UTC),
            success=True,
            input_preview=None,
            output_preview=None,
            duration_ms=None,
        )

        result = ApiToolOperation.model_validate(source, from_attributes=True)
        assert result.git is None

    def test_model_validate_roundtrip_none_git_fields_stay_none(self):
        """Git fields that are None on the source must remain None (not vanish)."""
        from datetime import datetime

        source = AdaptersToolOperation(
            observation_id="tool-use-id-123-2026",
            tool_name="Read",
            tool_use_id="toolu_xyz",
            operation_type="tool_execution_started",
            timestamp=datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC),
            success=None,
            input_preview=None,
            output_preview=None,
            duration_ms=None,
        )

        result = ApiToolOperation.model_validate(source, from_attributes=True)

        assert result.git_sha is None
        assert result.git_message is None
        assert result.git_branch is None
        assert result.git_repo is None


# ---------------------------------------------------------------------------
# Layer 2 → Layer 3 git field parity (syn_api.types → OperationInfo)
# ---------------------------------------------------------------------------


@pytest.mark.regression
class TestApiToOperationInfoGitFields:
    """Git fields present in syn_api.types.ToolOperation must exist in OperationInfo.

    The routes mapping layer converts ToolOperation → OperationInfo.
    Missing fields here cause the HTTP API to return null for git data.
    """

    def test_git_fields_present_in_operation_info(self):
        git_fields = {"git", "git_sha", "git_message", "git_branch", "git_repo"}
        operation_info_fields = _pydantic_field_names(OperationInfo)
        missing = git_fields - operation_info_fields
        assert missing == set(), (
            f"Git fields missing from syn_api.routes.sessions.OperationInfo: {missing}\n"
            f"Add them to apps/syn-api/src/syn_api/routes/sessions.py"
        )

    def test_operation_info_can_hold_all_git_values(self):
        """Smoke test: OperationInfo can be constructed with all git fields set."""
        from datetime import datetime

        op = OperationInfo(
            operation_id="git-abc123",
            operation_type="git_commit",
            timestamp=datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC),
            git_sha="abc123def456",
            git_message="feat: add regression tests",
            git_branch="feat/github-event-integration",
            git_repo="syntropic137",
        )

        assert op.git_sha == "abc123def456"
        assert op.git_message == "feat: add regression tests"
        assert op.git_branch == "feat/github-event-integration"
        assert op.git_repo == "syntropic137"

    def test_operation_info_git_fields_default_to_none(self):
        """Unset git fields must default to None, not be omitted from serialization."""
        op = OperationInfo(
            operation_id="op-1",
            operation_type="tool_execution_started",
        )
        dumped = op.model_dump()
        assert "git_sha" in dumped
        assert "git_message" in dumped
        assert "git_branch" in dumped
        assert "git_repo" in dumped
        assert dumped["git_sha"] is None
        assert dumped["git_repo"] is None
