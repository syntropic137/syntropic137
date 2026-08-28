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


# ---------------------------------------------------------------------------
# Merge semantics (issue #772)
#
# The merge key is the IDENTITY TRIPLE (source_url, version, skill_name), NOT
# skill_name. Two refs collapse into one only when all three fields match.
# What that actually means:
#
#   1. Same name, DIFFERENT version, across scopes -> BOTH survive. Phase
#      scope does NOT override a workflow-scope version by name. The
#      resulting conflict is caught downstream at provisioning, by
#      ``_check_no_conflicting_skill_versions`` in WorkspaceProvisionHandler,
#      which aborts the phase rather than letting one tree clobber the other.
#   2. Same name, DIFFERENT source_url, across scopes -> BOTH survive, for
#      the same reason: the shared name is not the key.
#   3. Same source_url + version, DIFFERENT names -> BOTH survive (one repo
#      publishing several skills).
#   4. Exact triple match -> deduped to one entry, held in the workflow-scope
#      position.
#
# So "phase scope wins on collision" must be read narrowly: it wins on an
# EXACT identity collision, where the two refs are interchangeable and
# winning is unobservable. There is no by-name override mechanism here.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_name_different_version_across_scopes_both_survive_merge() -> None:
    """Phase scope does NOT override a workflow-scope version by skill name.

    This is the assertion the identical-refs "phase wins" test could not
    make: the two refs differ here, so the output distinguishes merged-both
    from phase-won from workflow-won.
    """
    service, lock = _make_service()
    await _seed_lock(lock, "dup", "https://github.com/example/dup", "1.0.0", "shaOld")
    await _seed_lock(lock, "dup", "https://github.com/example/dup", "2.0.0", "shaNew")

    workflow_ref = _ref("dup", "https://github.com/example/dup", "1.0.0")
    phase_ref = _ref("dup", "https://github.com/example/dup", "2.0.0")
    out = await service.resolve_for_phase([workflow_ref], [phase_ref])

    assert len(out) == 2, "identity is the triple, so differing versions are two skills"
    assert [r.version for r in out] == ["1.0.0", "2.0.0"]
    assert [r.resolved_sha for r in out] == ["shaOld", "shaNew"]
    assert {r.skill_name for r in out} == {"dup"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_name_different_version_conflict_is_caught_at_provisioning() -> None:
    """The merge is permissive; the downstream guard is what makes it safe.

    Pins the second half of the contract: a same-name/different-version pair
    survives resolution but must abort the phase, because both trees
    materialize to the same ``.syn-skills/<skill_name>/`` path.
    """
    from syn_domain.contexts.orchestration._shared.skill_errors import SkillInstallFailed
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        _check_no_conflicting_skill_versions,
    )

    service, lock = _make_service()
    await _seed_lock(lock, "dup", "https://github.com/example/dup", "1.0.0", "shaOld")
    await _seed_lock(lock, "dup", "https://github.com/example/dup", "2.0.0", "shaNew")
    out = await service.resolve_for_phase(
        [_ref("dup", "https://github.com/example/dup", "1.0.0")],
        [_ref("dup", "https://github.com/example/dup", "2.0.0")],
    )

    with pytest.raises(SkillInstallFailed) as excinfo:
        _check_no_conflicting_skill_versions(out)
    assert "conflicting versions" in str(excinfo.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_name_different_source_across_scopes_both_survive_merge() -> None:
    """Two forks publishing the same skill name are two identities, not one."""
    service, lock = _make_service()
    await _seed_lock(lock, "same", "https://github.com/upstream/pack", "1.0.0", "shaUp")
    await _seed_lock(lock, "same", "https://github.com/fork/pack", "1.0.0", "shaFork")

    out = await service.resolve_for_phase(
        [_ref("same", "https://github.com/upstream/pack", "1.0.0")],
        [_ref("same", "https://github.com/fork/pack", "1.0.0")],
    )

    assert len(out) == 2
    assert [r.source_url for r in out] == [
        "https://github.com/upstream/pack",
        "https://github.com/fork/pack",
    ]
    assert [r.resolved_sha for r in out] == ["shaUp", "shaFork"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_source_and_version_different_names_both_survive_merge() -> None:
    """One repo+tag publishing two skills yields two entries, not one.

    The third element of the key earns its place here: keying on
    ``(source_url, version)`` alone would silently drop one of these.
    """
    service, lock = _make_service()
    await _seed_lock(lock, "alpha", "https://github.com/example/pack", "1.0.0", "shaA")
    await _seed_lock(lock, "beta", "https://github.com/example/pack", "1.0.0", "shaB")

    out = await service.resolve_for_phase(
        [_ref("alpha", "https://github.com/example/pack", "1.0.0")],
        [_ref("beta", "https://github.com/example/pack", "1.0.0")],
    )

    assert [r.skill_name for r in out] == ["alpha", "beta"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_is_additive_and_preserves_workflow_then_phase_order() -> None:
    """Genuinely different skills all survive, workflow refs first."""
    service, lock = _make_service()
    for name in ("w1", "w2", "p1", "p2"):
        await _seed_lock(lock, name, f"https://github.com/example/{name}", "1.0.0", f"sha-{name}")

    out = await service.resolve_for_phase(
        [
            _ref("w1", "https://github.com/example/w1", "1.0.0"),
            _ref("w2", "https://github.com/example/w2", "1.0.0"),
        ],
        [
            _ref("p1", "https://github.com/example/p1", "1.0.0"),
            _ref("p2", "https://github.com/example/p2", "1.0.0"),
        ],
    )

    assert [r.skill_name for r in out] == ["w1", "w2", "p1", "p2"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exact_triple_match_dedupes_into_the_workflow_scope_position() -> None:
    """Dedup on the exact triple keeps ONE entry, in the workflow-scope slot.

    Distinct from the existing identical-ref test: the surrounding refs make
    the position observable, so this pins ordering rather than just count.
    """
    service, lock = _make_service()
    for name in ("first", "shared", "last"):
        await _seed_lock(lock, name, f"https://github.com/example/{name}", "1.0.0", f"sha-{name}")

    shared = _ref("shared", "https://github.com/example/shared", "1.0.0")
    out = await service.resolve_for_phase(
        [_ref("first", "https://github.com/example/first", "1.0.0"), shared],
        [shared, _ref("last", "https://github.com/example/last", "1.0.0")],
    )

    assert [r.skill_name for r in out] == ["first", "shared", "last"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_phase_only_refs_resolve_without_any_workflow_scope() -> None:
    """Phase scope alone is a complete declaration; workflow scope is optional."""
    service, lock = _make_service()
    await _seed_lock(lock, "ph", "https://github.com/example/ph", "3.0.0", "shaPh")

    out = await service.resolve_for_phase(
        [], [_ref("ph", "https://github.com/example/ph", "3.0.0")]
    )

    assert len(out) == 1
    assert out[0].resolved_sha == "shaPh"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unregistered_phase_scope_ref_fails_even_when_workflow_scope_resolves() -> None:
    """A miss anywhere in the merged set fails the whole resolution."""
    service, lock = _make_service()
    await _seed_lock(lock, "ok", "https://github.com/example/ok", "1.0.0", "shaOk")

    with pytest.raises(SkillNotRegistered) as excinfo:
        await service.resolve_for_phase(
            [_ref("ok", "https://github.com/example/ok", "1.0.0")],
            [_ref("ghost", "https://github.com/example/ghost", "1.0.0")],
        )
    assert excinfo.value.skill_name == "ghost"
