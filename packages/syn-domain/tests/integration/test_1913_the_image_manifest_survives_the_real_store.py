"""A phase's image manifest reading, read back from the REAL event store (#1913).

The manifest is provenance: what the workspace image said about itself when the
phase ran. The live `WorkspaceAggregate` that also sees it is never saved, so
the only durable copy is the one on `WorkspaceProvisionedForPhase`.

Each case drives `WorkspaceProvisionHandler` against a workspace holding the
reading, so the command saved is the one provisioning produced, saves the
execution through the ESP server, and loads it again in a separate Python
process with its own client, as a restarted API does. Nothing the writing
process holds in memory can answer the read.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.ImageManifestValueObjects import (
    ImageManifestContent,
    ImageManifestReading,
    ImageManifestState,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    ProvisionResult,
    WorkspaceProvisionHandler,
)

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository, GrpcEventStoreClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.may_skip(reason="skips when no event store answers", issue="#1984"),
]

PHASE = "build"

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

#: Run in a fresh interpreter: connect a new client and print the phase's reading.
_LOAD_IN_A_FRESH_PROCESS = """
import asyncio, sys
from event_sourcing import GrpcEventStoreClient, RepositoryFactory
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

async def main(address, tenant_id, execution_id, phase_id):
    client = GrpcEventStoreClient(address=address, tenant_id=tenant_id)
    await client.connect()
    try:
        repository = RepositoryFactory(client).create_repository(
            WorkflowExecutionAggregate, "WorkflowExecution"
        )
        loaded = await repository.load(execution_id)
    finally:
        await client.disconnect()
    reading = None if loaded is None else loaded.image_manifest_for(phase_id)
    print("null" if reading is None else reading.model_dump_json())

asyncio.run(main(*sys.argv[1:]))
"""


async def _provisioned_with(reading: ImageManifestReading, execution_id: str) -> ProvisionResult:
    """What `WorkspaceProvisionHandler` produces for a workspace holding ``reading``."""
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1913"
    workspace.image_manifest = reading
    workspace.run_setup_phase = AsyncMock(
        return_value=ExecutionResult(exit_code=0, success=True, duration_ms=1.0)
    )
    workspace.execute = AsyncMock(
        return_value=ExecutionResult(exit_code=0, success=True, duration_ms=1.0)
    )
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_cm.__aexit__ = AsyncMock(return_value=False)
    service = MagicMock()
    service.create_workspace.return_value = workspace_cm

    handler = WorkspaceProvisionHandler(
        workspace_service=service,
        prompt_builder=AsyncMock(return_value="Do the task"),
        command_builder=MagicMock(return_value=["claude", "--print", "Do the task"]),
    )
    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as secrets:
        secrets.create = AsyncMock(return_value=MagicMock())
        return await handler.handle(
            todo=TodoItem(
                execution_id=execution_id, action=TodoAction.PROVISION_WORKSPACE, phase_id=PHASE
            ),
            phase=ExecutablePhase(
                phase_id=PHASE,
                name="Build",
                order=1,
                agent_config=AgentConfiguration(),
                prompt_template="Do the task",
                output_artifact_types=(),
            ),
            workflow_id="wf-1913",
            session_id="sess-1913",
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
    grpc_client: GrpcEventStoreClient,
    workflow_execution_repository: EventStoreRepository[WorkflowExecutionAggregate],
    unique_execution_id: str,
    reading: ImageManifestReading,
) -> None:
    result = await _provisioned_with(reading, unique_execution_id)
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
            phase_id=PHASE,
            phase_name="Build",
            phase_order=1,
        )
    )
    execution.provision_workspace_completed(result.command)
    await workflow_execution_repository.save(execution)

    restarted = subprocess.run(
        [
            sys.executable,
            "-c",
            _LOAD_IN_A_FRESH_PROCESS,
            grpc_client.address,
            grpc_client.tenant_id,
            unique_execution_id,
            PHASE,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )

    stdout_lines = restarted.stdout.strip().splitlines()
    assert stdout_lines, restarted.stderr
    assert ImageManifestReading.model_validate_json(stdout_lines[-1]) == reading
