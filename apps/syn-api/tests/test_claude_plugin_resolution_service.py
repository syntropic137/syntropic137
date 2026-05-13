# See ADR-066: tests cover the validate-only ``ensure_registered`` and the
# unchanged ``resolve_for_phase``; the service no longer fetches and the test
# wiring no longer references a fetcher.
"""Tests for ClaudePluginResolutionService (issue #726, Phase A redesign)."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_api.services.claude_plugin_resolution_service import (
    ClaudePluginResolutionService,
)
from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginNotRegistered,
)
from syn_domain.contexts.orchestration._shared.claude_plugin_ref import ClaudePluginRef
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    PhaseYamlDefinition,
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins.projection import (
    GlobalClaudePluginsProjection,
)
from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
    ClaudePluginLockProjection,
)


def _make_service() -> tuple[
    ClaudePluginResolutionService,
    ClaudePluginLockProjection,
    GlobalClaudePluginsProjection,
]:
    lock_projection = ClaudePluginLockProjection(InMemoryProjectionStore())
    global_projection = GlobalClaudePluginsProjection(InMemoryProjectionStore())
    service = ClaudePluginResolutionService(
        lock_projection=lock_projection,
        global_projection=global_projection,
    )
    return service, lock_projection, global_projection


async def _seed_lock(
    lock: ClaudePluginLockProjection, name: str, source_url: str, version: str, sha: str
) -> None:
    await lock.on_claude_plugin_registered(
        {
            "source_url": source_url,
            "version": version,
            "name": name,
            "resolved_sha": sha,
            "tree_storage_prefix": f"prefix-{sha}",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


def _workflow_with_refs(
    workflow_refs: list[ClaudePluginRef],
    phase_refs: list[ClaudePluginRef],
) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf-test",
        name="test workflow",
        type="ad-hoc",
        claude_plugins=workflow_refs,
        phases=[
            PhaseYamlDefinition(
                id="p1",
                name="phase 1",
                order=1,
                execution_type="sequential",
                prompt_template="hi",
                claude_plugins=phase_refs,
            ),
        ],
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_registered_passes_when_all_refs_in_lock() -> None:
    service, lock, _global = _make_service()
    await _seed_lock(lock, "wf", "https://github.com/example/wf-plugin", "1.0.0", "shaWf")
    await _seed_lock(lock, "ph", "https://github.com/example/ph-plugin", "2.0.0", "shaPh")

    workflow_def = _workflow_with_refs(
        workflow_refs=[
            ClaudePluginRef(
                name="wf",
                source_url="https://github.com/example/wf-plugin",
                version="1.0.0",
            )
        ],
        phase_refs=[
            ClaudePluginRef(
                name="ph",
                source_url="https://github.com/example/ph-plugin",
                version="2.0.0",
            )
        ],
    )

    # Validation only -- no exception raised when every ref is in the lock.
    await service.ensure_registered(workflow_def)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_registered_raises_when_workflow_ref_missing() -> None:
    service, _lock, _global = _make_service()

    workflow_def = _workflow_with_refs(
        workflow_refs=[
            ClaudePluginRef(
                name="ghost",
                source_url="https://github.com/example/ghost",
                version="1.0.0",
            )
        ],
        phase_refs=[],
    )

    with pytest.raises(ClaudePluginNotRegistered):
        await service.ensure_registered(workflow_def)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_registered_includes_global_plugins() -> None:
    service, lock, global_proj = _make_service()
    await global_proj.on_global_claude_plugin_added(
        {
            "name": "glob",
            "source_url": "https://github.com/example/glob",
            "version": "1.0.0",
            "resolved_sha": "g",
            "added_at": datetime.now(UTC).isoformat(),
        }
    )

    # Workflow declares no plugins of its own; the only ref comes from global.
    # If the global plugin is in the lock, validation passes.
    await _seed_lock(lock, "glob", "https://github.com/example/glob", "1.0.0", "g")
    await service.ensure_registered(_workflow_with_refs([], []))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_registered_raises_when_global_plugin_missing_from_lock() -> None:
    service, _lock, global_proj = _make_service()
    await global_proj.on_global_claude_plugin_added(
        {
            "name": "glob",
            "source_url": "https://github.com/example/glob",
            "version": "1.0.0",
            "resolved_sha": "g",
            "added_at": datetime.now(UTC).isoformat(),
        }
    )

    with pytest.raises(ClaudePluginNotRegistered):
        await service.ensure_registered(_workflow_with_refs([], []))


# ---------------------------------------------------------------------------
# resolve_for_phase (PR2 surface, issue #726) -- unchanged by Phase A
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_returns_empty_when_nothing_declared() -> None:
    service, _lock, _global = _make_service()
    out = await service.resolve_for_phase([], [])
    assert out == ()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_returns_global_only() -> None:
    service, lock, global_proj = _make_service()
    await global_proj.on_global_claude_plugin_added(
        {
            "name": "g",
            "source_url": "https://github.com/example/g",
            "version": "1.0.0",
            "resolved_sha": "shaG",
            "added_at": datetime.now(UTC).isoformat(),
        }
    )
    await _seed_lock(lock, "g", "https://github.com/example/g", "1.0.0", "shaG")

    out = await service.resolve_for_phase([], [])
    assert len(out) == 1
    assert out[0].name == "g"
    assert out[0].version == "1.0.0"
    assert out[0].resolved_sha == "shaG"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_workflow_overrides_global() -> None:
    service, lock, global_proj = _make_service()
    await global_proj.on_global_claude_plugin_added(
        {
            "name": "shared",
            "source_url": "https://github.com/example/shared",
            "version": "1.0.0",
            "resolved_sha": "shaOld",
            "added_at": datetime.now(UTC).isoformat(),
        }
    )
    await _seed_lock(lock, "shared", "https://github.com/example/shared", "1.0.0", "shaOld")
    await _seed_lock(lock, "shared", "https://github.com/example/shared", "2.0.0", "shaNew")

    workflow_ref = ClaudePluginRef(
        name="shared",
        source_url="https://github.com/example/shared",
        version="2.0.0",
    )
    out = await service.resolve_for_phase([workflow_ref], [])
    assert len(out) == 1
    assert out[0].version == "2.0.0"
    assert out[0].resolved_sha == "shaNew"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_phase_overrides_workflow() -> None:
    service, lock, _global = _make_service()
    await _seed_lock(lock, "x", "https://github.com/example/x", "1.0.0", "v1")
    await _seed_lock(lock, "x", "https://github.com/example/x", "2.0.0", "v2")

    workflow_ref = ClaudePluginRef(
        name="x", source_url="https://github.com/example/x", version="1.0.0"
    )
    phase_ref = ClaudePluginRef(
        name="x", source_url="https://github.com/example/x", version="2.0.0"
    )
    out = await service.resolve_for_phase([workflow_ref], [phase_ref])
    assert len(out) == 1
    assert out[0].version == "2.0.0"
    assert out[0].resolved_sha == "v2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_returns_deterministic_order() -> None:
    service, lock, global_proj = _make_service()
    await global_proj.on_global_claude_plugin_added(
        {
            "name": "a",
            "source_url": "https://github.com/example/a",
            "version": "1.0.0",
            "resolved_sha": "sa",
            "added_at": datetime.now(UTC).isoformat(),
        }
    )
    await _seed_lock(lock, "a", "https://github.com/example/a", "1.0.0", "sa")
    await _seed_lock(lock, "b", "https://github.com/example/b", "1.0.0", "sb")
    await _seed_lock(lock, "c", "https://github.com/example/c", "1.0.0", "sc")

    workflow_ref = ClaudePluginRef(
        name="b", source_url="https://github.com/example/b", version="1.0.0"
    )
    phase_ref = ClaudePluginRef(
        name="c", source_url="https://github.com/example/c", version="1.0.0"
    )
    out = await service.resolve_for_phase([workflow_ref], [phase_ref])
    # Insertion order is global -> workflow -> phase.
    assert [p.name for p in out] == ["a", "b", "c"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_raises_when_lock_missing() -> None:
    service, _lock, _global = _make_service()
    workflow_ref = ClaudePluginRef(
        name="ghost", source_url="https://github.com/example/ghost", version="1.0.0"
    )
    with pytest.raises(LookupError):
        await service.resolve_for_phase([workflow_ref], [])
