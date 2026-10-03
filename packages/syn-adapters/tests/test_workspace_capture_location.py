"""A replayed session fact finds the same spool without container metadata."""

import pytest

from syn_adapters.session_inventory.workspace_location import workspace_capture_location
from syn_adapters.workspace_backends.service.workspace_lifecycle import build_isolation_config
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_domain.contexts.agent_sessions import RunIdentity

pytestmark = pytest.mark.unit


def test_capture_session_identity_is_carried_separately_from_phase_environment() -> None:
    config = build_isolation_config(
        config=WorkspaceServiceConfig(),
        workspace_id="transient-workspace",
        execution_id="run",
        workflow_id="workflow",
        phase_id="phase",
        capture_session_id="persisted-session",
        extra_environment={"capture_session_id": "phase-controlled-value"},
    )
    assert config.capture_session_id == "persisted-session"
    assert config.workspace_id == "transient-workspace"


def test_storage_identity_reconstructs_and_separates_installations_runs_and_sessions() -> None:
    first = RunIdentity(source_instance_id="installation", execution_id="run")
    location = workspace_capture_location(first, "session/../opaque")
    assert location == workspace_capture_location(
        RunIdentity.model_validate_json(first.model_dump_json()), "session/../opaque"
    )
    alternatives = [
        workspace_capture_location(
            RunIdentity(source_instance_id="other", execution_id="run"), "session/../opaque"
        ),
        workspace_capture_location(
            RunIdentity(source_instance_id="installation", execution_id="other"),
            "session/../opaque",
        ),
        workspace_capture_location(first, "other"),
    ]
    assert len({location.volume_name, *(item.volume_name for item in alternatives)}) == 4
    assert "/" not in location.volume_name
    assert ".." not in location.partition
    assert location.envelope_dir.endswith(f"/{location.partition}/envelopes")
