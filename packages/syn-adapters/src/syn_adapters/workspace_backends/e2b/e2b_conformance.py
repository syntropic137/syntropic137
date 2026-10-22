"""The E2B backend conformance suite (#1915, plan step E), backend-agnostic.

Each check drives a WorkspaceService's isolation port, so it runs unchanged
against a sandbox double (``test_e2b_backend.py``, in CI) and against real
E2B (``test_e2b_live.py``, marker ``e2b``, never in CI).
"""

from __future__ import annotations

import uuid

from agentic_isolation.providers.capabilities import SupportsOwnership

from syn_adapters.workspace_backends.agentic import AgenticIsolationAdapter
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationBackendType,
    IsolationConfig,
    IsolationHandle,
    SecurityPolicy,
)

#: Writes to stdout and stderr in a known order, then fails with a known code.
MERGED_COMMAND = ["sh", "-c", "echo out-1; echo err-1 >&2; echo out-2; exit 3"]
MERGED_OUTPUT = "out-1\nerr-1\nout-2\n"
#: Every byte value, so a text-mode transfer anywhere on the path corrupts it.
BINARY = bytes(range(256)) * 4


def run_labels(config: IsolationConfig) -> dict[str, str]:
    """The labels that select exactly this run's workspaces in the E2B list."""
    return {"syn.execution_id": config.execution_id}


def isolation_config(template: str, *, cpu: float = 1.0, memory_mb: int = 1024) -> IsolationConfig:
    """A workspace on ``template``, which the E2B kit carries as its one approved image."""
    run = uuid.uuid4().hex[:12]
    return IsolationConfig(
        execution_id=f"e2b-conf-{run}",
        workspace_id=f"ws-{run}",
        workflow_id="wf-e2b-conformance",
        backend=IsolationBackendType.DOCKER_HARDENED,
        image=template,
        security_policy=SecurityPolicy(cpu_limit_cores=cpu, memory_limit_mb=memory_mb),
    )


async def check_create(
    adapter: AgenticIsolationAdapter, config: IsolationConfig
) -> IsolationHandle:
    handle = await adapter.create(config)
    assert handle.isolation_type == "e2b"
    assert adapter.workspace(handle.isolation_id) is not None
    return handle


async def check_merged_stream_and_outcome(
    adapter: AgenticIsolationAdapter, handle: IsolationHandle
) -> None:
    result = await adapter.execute(handle, MERGED_COMMAND)
    assert result.exit_code == 3
    assert not result.success
    assert result.stdout == MERGED_OUTPUT  # stderr merged, in write order
    assert result.stderr == ""


async def check_binary_round_trip(
    adapter: AgenticIsolationAdapter, handle: IsolationHandle
) -> None:
    await adapter.copy_to(handle, [("conformance/blob.bin", BINARY)])
    got = await adapter.copy_from(handle, ["conformance/blob.bin"])
    assert [content for _, content in got] == [BINARY]


async def check_list_and_attach(
    ownership: SupportsOwnership, handle: IsolationHandle, labels: dict[str, str]
) -> None:
    owned = await ownership.list_owned(labels)
    assert [o.workspace_id for o in owned] == [handle.isolation_id]
    attached = await ownership.attach(handle.isolation_id, expect_labels=labels)
    assert attached.id == handle.isolation_id


async def check_cleanup(
    adapter: AgenticIsolationAdapter,
    ownership: SupportsOwnership,
    handle: IsolationHandle,
    labels: dict[str, str],
) -> None:
    """Destroyed means E2B lists nothing left for this run, not that destroy returned."""
    await adapter.destroy(handle)
    assert await ownership.list_owned(labels) == []
