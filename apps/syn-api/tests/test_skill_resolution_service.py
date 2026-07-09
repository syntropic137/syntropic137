# See ADR-066: mirrors test_claude_plugin_resolution_service.py (issue #726)
# but for skills, which have no global scope in this plan (issue #772).
"""Tests for SkillResolutionService (issue #772)."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_api.services.skill_resolution_service import SkillResolutionService
from syn_domain.contexts.orchestration._shared.skill_errors import SkillNotRegistered
from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef
from syn_domain.contexts.orchestration.slices.register_skill.projection import (
    SkillLockProjection,
)


def _make_service() -> tuple[SkillResolutionService, SkillLockProjection]:
    lock_projection = SkillLockProjection(InMemoryProjectionStore())
    service = SkillResolutionService(lock_projection=lock_projection)
    return service, lock_projection


async def _seed_lock(
    lock: SkillLockProjection,
    skill_name: str,
    source_url: str,
    version: str,
    sha: str,
) -> None:
    await lock.on_skill_registered(
        {
            "source_url": source_url,
            "version": version,
            "skill_name": skill_name,
            "resolved_sha": sha,
            "tree_storage_prefix": f"prefix-{sha}",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


def _ref(skill_name: str, source_url: str, version: str) -> SkillRef:
    return SkillRef(skill_name=skill_name, source_url=source_url, version=version)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_returns_empty_when_nothing_declared() -> None:
    service, _lock = _make_service()
    out = await service.resolve_for_phase([], [])
    assert out == ()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_returns_workflow_only() -> None:
    service, lock = _make_service()
    await _seed_lock(lock, "wf", "https://github.com/example/wf-skill", "1.0.0", "shaWf")

    workflow_ref = _ref("wf", "https://github.com/example/wf-skill", "1.0.0")
    out = await service.resolve_for_phase([workflow_ref], [])
    assert len(out) == 1
    assert out[0].skill_name == "wf"
    assert out[0].version == "1.0.0"
    assert out[0].resolved_sha == "shaWf"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_is_additive_across_scopes() -> None:
    service, lock = _make_service()
    await _seed_lock(lock, "wf", "https://github.com/example/wf-skill", "1.0.0", "shaWf")
    await _seed_lock(lock, "ph", "https://github.com/example/ph-skill", "2.0.0", "shaPh")

    workflow_ref = _ref("wf", "https://github.com/example/wf-skill", "1.0.0")
    phase_ref = _ref("ph", "https://github.com/example/ph-skill", "2.0.0")
    out = await service.resolve_for_phase([workflow_ref], [phase_ref])
    assert {r.skill_name for r in out} == {"wf", "ph"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_dedupes_identical_ref_in_both_scopes() -> None:
    service, lock = _make_service()
    await _seed_lock(lock, "shared", "https://github.com/example/shared", "1.0.0", "sha1")

    ref = _ref("shared", "https://github.com/example/shared", "1.0.0")
    out = await service.resolve_for_phase([ref], [ref])
    assert len(out) == 1
    assert out[0].skill_name == "shared"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_phase_scope_wins_on_identity_collision() -> None:
    # WHY: same (source_url, version, skill_name) triple declared at both
    # scopes is one identity; the phase-scope instance is kept.
    service, lock = _make_service()
    await _seed_lock(lock, "x", "https://github.com/example/x", "1.0.0", "sha1")

    workflow_ref = _ref("x", "https://github.com/example/x", "1.0.0")
    phase_ref = _ref("x", "https://github.com/example/x", "1.0.0")
    out = await service.resolve_for_phase([workflow_ref], [phase_ref])
    assert len(out) == 1
    assert out[0].resolved_sha == "sha1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_raises_skill_not_registered_on_miss() -> None:
    service, _lock = _make_service()
    ghost = _ref("ghost", "https://github.com/example/ghost", "1.0.0")

    with pytest.raises(SkillNotRegistered) as excinfo:
        await service.resolve_for_phase([ghost], [])

    # Structured attributes must be present so the API-tier error mapping can
    # surface them without re-parsing the human-readable message.
    assert excinfo.value.source_url == "https://github.com/example/ghost"
    assert excinfo.value.version == "1.0.0"
    assert excinfo.value.skill_name == "ghost"


@pytest.mark.unit
def test_skill_not_registered_maps_to_422_with_structured_context() -> None:
    from syn_api.services.skill_error_mapping import http_exception_for_skill_error

    exc = SkillNotRegistered("https://github.com/example/ghost", "1.0.0", "ghost")
    http_exc = http_exception_for_skill_error(exc)

    assert http_exc.status_code == 422
    assert http_exc.detail == {
        "error_code": "skill_not_registered",
        "message": str(exc),
        "source_url": "https://github.com/example/ghost",
        "version": "1.0.0",
        "skill_name": "ghost",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_for_phase_preserves_declaration_order() -> None:
    service, lock = _make_service()
    await _seed_lock(lock, "a", "https://github.com/example/a", "1.0.0", "sa")
    await _seed_lock(lock, "b", "https://github.com/example/b", "1.0.0", "sb")

    workflow_ref = _ref("a", "https://github.com/example/a", "1.0.0")
    phase_ref = _ref("b", "https://github.com/example/b", "1.0.0")
    out = await service.resolve_for_phase([workflow_ref], [phase_ref])
    assert [r.skill_name for r in out] == ["a", "b"]
