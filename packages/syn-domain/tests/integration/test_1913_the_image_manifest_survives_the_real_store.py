"""A phase's image manifest reading, read back from the REAL event store (#1913).

The manifest is provenance: what the workspace image said about itself when the
phase ran. The live `WorkspaceAggregate` that also sees it is never saved, so
the only durable copy is the one on `WorkspaceProvisionedForPhase`. This saves
an execution through the ESP server and loads it again, as a restarted process
does, for each of the three states a reading can be in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    ProvisionWorkspaceCompletedCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.ImageManifestValueObjects import (
    ImageManifestContent,
    ImageManifestReading,
    ImageManifestState,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.may_skip(reason="skips when no event store answers", issue="#1984"),
]

_READ = ImageManifestReading(
    state=ImageManifestState.READ,
    manifest=ImageManifestContent(
        provider="claude-cli",
        provider_version="1.1.0",
        components={"claude_cli": "2.1.76"},
        build_commit="e63b4458332a",
        built_at="2026-10-01T00:00:00+00:00",
        manifest_digest="d55e27a49de81850",
    ),
)


@pytest.mark.parametrize(
    "reading",
    [
        _READ,
        ImageManifestReading.absent(),
        ImageManifestReading.unreadable("RuntimeError: sandbox gone"),
    ],
    ids=["read", "absent", "unreadable"],
)
async def test_the_reading_is_found_on_the_execution_after_a_restart(
    workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
    unique_execution_id: str,
    reading: ImageManifestReading,
) -> None:
    execution = WorkflowExecutionAggregate()
    execution._handle_command(
        StartExecutionCommand(
            execution_id=unique_execution_id,
            workflow_id="wf-1913",
            workflow_name="Image provenance",
            total_phases=1,
            inputs={},
        )
    )
    execution.start_phase(
        StartPhaseCommand(
            execution_id=unique_execution_id,
            workflow_id="wf-1913",
            phase_id="build",
            phase_name="Build",
            phase_order=1,
        )
    )
    execution.provision_workspace_completed(
        ProvisionWorkspaceCompletedCommand(
            execution_id=unique_execution_id,
            phase_id="build",
            workspace_id="ws-1913",
            image_manifest=reading,
        )
    )
    await workflow_execution_repository.save(execution)

    loaded = await workflow_execution_repository.load(unique_execution_id)

    assert loaded is not None
    assert loaded.image_manifest_for("build") == reading
