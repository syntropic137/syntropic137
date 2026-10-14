"""An OOM-killed workspace is recognisable from GET /metrics/phase-profiles (#1716).

The exit-137 class: a phase whose workspace the kernel killed for memory must
reach the API as ``oom_killed: true`` with its peak memory, not as a bare
exit code. Every hop is the real one except the database: agentic-workspace's
own ``WorkspaceDockerProvider`` and ``TeardownReport``, syn's
``usage_from_report``, the Lane 2 row in the shape ``record_workspace_usage``
writes it, the profile query's row reader, and the API response model.
``test_phase_profiles_reach_the_api.py`` pins the Postgres read separately.

Needs Docker. It skips without it, so a green run without Docker proves
nothing: read the pass and skip counts. Run with:

    uv run pytest -m integration -q \
        apps/syn-api/tests/integration/test_oom_killed_phase_reaches_the_api.py
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime

import pytest
from agentic_isolation import (
    ResourceLimits,
    SecurityConfig,
    WorkspaceConfig,
    WorkspaceDockerProvider,
)

from syn_adapters.workspace_backends.agentic.teardown_usage import usage_from_report
from syn_api.types import PhaseProfilesResponse
from syn_domain.contexts.orchestration.slices.phase_profiles import PhaseProfiles
from syn_domain.contexts.orchestration.slices.phase_profiles.query_service import (
    _resource_profiles,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not WorkspaceDockerProvider.is_available(), reason="Docker not available"),
]

IMAGE = "python:3.12-slim"


async def _usage_row_after(command: str, memory: str) -> str:
    """Run ``command`` in a real workspace and return its Lane 2 usage row."""
    provider = WorkspaceDockerProvider(default_image=IMAGE, security=SecurityConfig.development())
    workspace = await provider.create(
        WorkspaceConfig(provider="docker", image=IMAGE, limits=ResourceLimits(memory=memory))
    )
    try:
        result = await provider.execute(workspace, command, timeout=120)
    finally:
        report = await provider.destroy(workspace)
    usage = usage_from_report(report.usage)
    assert usage is not None, (result, report)
    return json.dumps({**dataclasses.asdict(usage), "workspace_lifetime_seconds": 1.0})


async def test_an_oom_killed_workspace_reaches_the_api_as_one() -> None:
    # `tail` buffers an endless line, so it grows until the kernel kills it.
    killed = await _usage_row_after("tail /dev/zero", "32m")
    quiet = await _usage_row_after("true", "256m")
    rows = [
        {"execution_id": "exec-oom", "phase_id": "build", "usage": killed},
        {"execution_id": "exec-quiet", "phase_id": "build", "usage": quiet},
    ]
    now = datetime.now(UTC)
    profiles = PhaseProfiles(
        workflow_id="wf",
        since=now,
        until=now,
        executions=2,
        resources=_resource_profiles(rows),  # type: ignore[arg-type]  # Record stand-ins
    )

    (build,) = PhaseProfilesResponse.from_profiles(profiles, window_days=7).resources

    assert (build.oom.killed, build.oom.not_killed, build.oom.unknown) == (1, 1, 0)
    (oom,) = build.oom_killed_phases
    assert oom.execution_id == "exec-oom"
    assert oom.oom_killed is True
    assert oom.memory_peak_bytes is not None
    assert oom.memory_peak_bytes >= 16 * 1024 * 1024
