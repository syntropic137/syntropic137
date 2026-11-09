"""A lock record whose ``sha256-`` pin contradicts its resolved_sha is refused (#889).

#887 refuses such a record at registration, but one written before that guard
can still sit in the lock projection, and the materializers fetch by
``resolved_sha`` alone. Resolution used to copy the record through unchecked,
so the version promised one tree and the workspace received another.

Plugins and skills pin content identically, so both are covered here side by
side: divergence between them is itself the defect.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_api.services.claude_plugin_resolution_service import ClaudePluginResolutionService
from syn_api.services.skill_resolution_service import SkillResolutionService
from syn_domain.contexts.orchestration import (
    ClaudePluginLockedHashMismatch,
    ClaudePluginRef,
    SkillLockedHashMismatch,
    SkillRef,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins.projection import (
    GlobalClaudePluginsProjection,
)
from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
    ClaudePluginLockProjection,
)
from syn_domain.contexts.orchestration.slices.register_skill.projection import (
    SkillLockProjection,
)

pytestmark = pytest.mark.unit

_SOURCE = "https://github.com/example/pinned"
_PINNED = "a" * 64
_OTHER = "b" * 64
_PINNED_VERSION = f"sha256-{_PINNED}"


def _plugin_service() -> tuple[ClaudePluginResolutionService, ClaudePluginLockProjection]:
    lock = ClaudePluginLockProjection(InMemoryProjectionStore())
    service = ClaudePluginResolutionService(
        lock_projection=lock,
        global_projection=GlobalClaudePluginsProjection(InMemoryProjectionStore()),
    )
    return service, lock


def _skill_service() -> tuple[SkillResolutionService, SkillLockProjection]:
    lock = SkillLockProjection(InMemoryProjectionStore())
    return SkillResolutionService(lock_projection=lock), lock


async def _seed_plugin(
    lock: ClaudePluginLockProjection, version: str, sha: str, source_url: str = _SOURCE
) -> None:
    await lock.on_claude_plugin_registered(
        {
            "source_url": source_url,
            "version": version,
            "name": "pinned",
            "resolved_sha": sha,
            "tree_storage_prefix": f"prefix-{sha}",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


async def _seed_skill(lock: SkillLockProjection, version: str, sha: str) -> None:
    await lock.on_skill_registered(
        {
            "source_url": _SOURCE,
            "version": version,
            "skill_name": "pinned",
            "resolved_sha": sha,
            "tree_storage_prefix": f"prefix-{sha}",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


def _plugin_ref(version: str) -> ClaudePluginRef:
    return ClaudePluginRef(name="pinned", source_url=_SOURCE, version=version)


def _skill_ref(version: str) -> SkillRef:
    return SkillRef(skill_name="pinned", source_url=_SOURCE, version=version)


class TestAContradictedPinIsRefused:
    async def test_plugin_resolution_refuses(self) -> None:
        service, lock = _plugin_service()
        await _seed_plugin(lock, _PINNED_VERSION, _OTHER)

        with pytest.raises(ClaudePluginLockedHashMismatch) as exc:
            await service.resolve_for_phase([], [_plugin_ref(_PINNED_VERSION)])

        message = str(exc.value)
        for part in (_SOURCE, _PINNED_VERSION, "'pinned'", _PINNED, _OTHER):
            assert part in message, f"{part!r} missing from {message!r}"
        assert exc.value.resolved_sha == _OTHER

    async def test_skill_resolution_refuses(self) -> None:
        service, lock = _skill_service()
        await _seed_skill(lock, _PINNED_VERSION, _OTHER)

        with pytest.raises(SkillLockedHashMismatch) as exc:
            await service.resolve_for_phase([], [_skill_ref(_PINNED_VERSION)])

        message = str(exc.value)
        for part in (_SOURCE, _PINNED_VERSION, "'pinned'", _PINNED, _OTHER):
            assert part in message, f"{part!r} missing from {message!r}"
        assert exc.value.resolved_sha == _OTHER


class TestEverythingElseResolvesAsBefore:
    @pytest.mark.parametrize(
        ("version", "sha"),
        [(_PINNED_VERSION, _PINNED), ("v1.2.0", _OTHER)],
        ids=["matching-pin", "tag"],
    )
    async def test_plugin(self, version: str, sha: str) -> None:
        service, lock = _plugin_service()
        await _seed_plugin(lock, version, sha)

        (resolved,) = await service.resolve_for_phase([], [_plugin_ref(version)])

        assert (resolved.version, resolved.resolved_sha) == (version, sha)
        assert resolved.tree_storage_prefix == f"prefix-{sha}"

    @pytest.mark.parametrize(
        ("version", "sha"),
        [(_PINNED_VERSION, _PINNED), ("v1.2.0", _OTHER)],
        ids=["matching-pin", "tag"],
    )
    async def test_skill(self, version: str, sha: str) -> None:
        service, lock = _skill_service()
        await _seed_skill(lock, version, sha)

        (resolved,) = await service.resolve_for_phase([], [_skill_ref(version)])

        assert (resolved.version, resolved.resolved_sha) == (version, sha)
        assert resolved.tree_storage_prefix == f"prefix-{sha}"


class TestTheCallerSeesTheRefusal:
    async def test_skill_execute_preflight_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Execute start runs the real resolver; the refusal is a 422 naming the phase."""
        import syn_api._wiring as wiring
        from syn_api.routes.executions import commands

        service, lock = _skill_service()
        await _seed_skill(lock, _PINNED_VERSION, _OTHER)

        async def _get_service() -> SkillResolutionService:
            return service

        monkeypatch.setattr(wiring, "get_skill_resolution_service", _get_service)

        class _Phase:
            phase_id = "research"
            skills = (_skill_ref(_PINNED_VERSION),)

        class _Workflow:
            phases = [_Phase()]
            skills = ()

        with pytest.raises(HTTPException) as exc:
            await commands._reject_unresolvable_skill_refs(_Workflow())  # type: ignore[arg-type]

        assert exc.value.status_code == 422
        assert "phase 'research'" in str(exc.value.detail)
        assert _OTHER in str(exc.value.detail)

    async def test_plugin_workflow_install_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Workflow install is where a plugin ref is checked for the caller."""
        import syn_api._wiring as wiring
        yaml_content = f"""
id: pinned-plugin-wf
name: Pinned plugin workflow
type: research
classification: simple
claude_plugins:
  - source: {_SOURCE}
    version: {_PINNED_VERSION}
    name: pinned
phases:
  - id: think
    name: Think
    order: 1
    prompt_template: "Think."
"""
        # The lock key is the ref as the YAML parser normalises it, not as written.
        (ref,) = WorkflowDefinition.from_yaml(yaml_content).claude_plugins
        service, lock = _plugin_service()
        await _seed_plugin(lock, ref.version, _OTHER, source_url=ref.source_url)

        async def _get_service() -> ClaudePluginResolutionService:
            return service

        monkeypatch.setattr(wiring, "get_claude_plugin_resolution_service", _get_service)

        from starlette.requests import Request

        from syn_api.routes.workflows.commands import create_workflow_from_yaml_endpoint

        async def _receive() -> dict[str, object]:
            return {"type": "http.request", "body": yaml_content.encode(), "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/workflows/from-yaml",
                "headers": [(b"content-type", b"application/yaml")],
                "query_string": b"",
            },
            _receive,  # type: ignore[arg-type]
        )

        with pytest.raises(HTTPException) as exc:
            await create_workflow_from_yaml_endpoint(request)

        assert exc.value.status_code == 422
        assert exc.value.detail["error_code"] == "claude_plugin_locked_hash_mismatch"  # type: ignore[index]
        assert _OTHER in exc.value.detail["message"]  # type: ignore[index]
