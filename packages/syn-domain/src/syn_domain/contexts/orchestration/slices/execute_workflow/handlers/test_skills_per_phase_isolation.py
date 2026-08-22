"""Per-phase skill isolation regression test (issue #772).

Every existing skills test provisions a single phase, so nothing pinned the
claim that actually matters operationally: a skill declared on phase A must
NOT reach phase B's workspace.

This test provisions two phases from one workflow through the real
``WorkspaceProvisionHandler`` and asserts the negative for phase B:

- phase A (workflow-scope skill + phase-scope skill) injects BOTH skill trees
  and issues one ``skills add`` per skill;
- phase B (workflow-scope skill only) injects ONLY the workflow-scope tree and
  never mentions the phase-A-only skill in any injected path or CLI argument.

Asserting on the install PATH and the ``skills add`` argv is deliberate:
``skills list --agent <key>`` does not filter by agent, so it cannot
distinguish "installed for the right harness" from "installed for the wrong
one", and a staged file under ``.syn-skills/`` is not the same claim as
installed-for-the-agent.

Live-container evidence for the same claim is recorded in
``docs/testing/evidence/2026-08-22-skills-e2e-proof.md``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.in_memory_skill_repositories import (
    InMemorySkillRegistrationRepository,
)
from syn_adapters.storage.skill_storage.factory import get_test_skill_storage
from syn_api.services.skill_materializer import SkillMaterializer
from syn_api.services.skill_resolution_service import SkillResolutionService
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.ports.SkillStoragePort import SkillFile
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.register_skill.projection import (
    SkillLockProjection,
)
from syn_domain.contexts.orchestration.slices.register_skill.RegisterSkillHandler import (
    RegisterSkillHandler,
)

# Mirrors the starter plugin: a workflow-scope skill every phase gets, and a
# phase-scope skill only the first phase gets.
_SHARED_SKILL_MD = b"""---
name: repo-conventions
description: House conventions for this repository.
---

Use conventional commits.
"""

_PHASE_ONLY_SKILL_MD = b"""---
name: doc-coauthoring
description: Guide users through co-authoring documentation.
---

Draft the doc.
"""

_WORKFLOW_YAML = """
id: per-phase-isolation-workflow
name: Per Phase Isolation Workflow
skills:
  - "example/shared-repo/repo-conventions@1.0.0"
phases:
  - id: investigate
    name: Investigate
    order: 1
    prompt_template: "Investigate."
    skills:
      - "example/docs-repo/doc-coauthoring@2.0.0"
  - id: summarize
    name: Summarize
    order: 2
    prompt_template: "Summarize."
"""

_SHARED_SKILL = "repo-conventions"
_PHASE_ONLY_SKILL = "doc-coauthoring"


async def _register_two_skills() -> tuple[object, SkillLockProjection]:
    """Register both skills and feed the lock projection, as the route does."""
    storage = get_test_skill_storage()
    repo = InMemorySkillRegistrationRepository()
    handler = RegisterSkillHandler(storage=storage, repo=repo)
    lock = SkillLockProjection(InMemoryProjectionStore())

    for source_url, version, content in (
        ("https://github.com/example/shared-repo", "1.0.0", _SHARED_SKILL_MD),
        ("https://github.com/example/docs-repo", "2.0.0", _PHASE_ONLY_SKILL_MD),
    ):
        result = await handler.handle(
            source_url=source_url,
            version=version,
            skill_name=None,
            files=[SkillFile(rel_path="SKILL.md", content=content)],
        )
        await lock.on_skill_registered(
            {
                "source_url": result.source_url,
                "version": result.version,
                "skill_name": result.skill_name,
                "resolved_sha": result.resolved_sha,
                "tree_storage_prefix": result.tree_storage_prefix,
                "registered_at": "2026-08-22T00:00:00+00:00",
            }
        )

    return storage, lock


def _fake_workspace() -> AsyncMock:
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
    workspace.inject_files = AsyncMock()
    workspace.workspace_id = "ws-isolation"
    workspace.execute = AsyncMock(
        return_value=ExecutionResult(exit_code=0, success=True, duration_ms=1.0)
    )
    return workspace


def _injected_paths(workspace: AsyncMock) -> list[str]:
    """Every relative path handed to inject_files across all calls."""
    return [
        rel_path for call in workspace.inject_files.call_args_list for rel_path, _ in call.args[0]
    ]


def _skills_add_argv(workspace: AsyncMock) -> list[list[str]]:
    """Every `skills add ...` argv issued against the workspace."""
    return [
        call.args[0]
        for call in workspace.execute.call_args_list
        if isinstance(call.args[0], list) and call.args[0][:2] == ["skills", "add"]
    ]


async def _provision(phase: ExecutablePhase, storage: object) -> AsyncMock:
    """Run the real provision handler for one phase, return its fake workspace."""
    workspace = _fake_workspace()
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm

    async def fake_prompt_builder(*_args: object, **_kwargs: object) -> str:
        return "Go."

    def fake_command_builder(_phase: object, prompt: str) -> list[str]:
        return ["claude", "--print", prompt]

    handler = WorkspaceProvisionHandler(
        workspace_service=workspace_service,
        prompt_builder=fake_prompt_builder,
        command_builder=fake_command_builder,
        skill_materializer=SkillMaterializer(storage=storage),  # type: ignore[arg-type]
    )

    todo = TodoItem(
        execution_id="exec-isolation",
        action=TodoAction.PROVISION_WORKSPACE,
        phase_id=phase.phase_id,
    )

    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
        MockSecrets.create = AsyncMock(return_value=MagicMock())
        await handler.handle(
            todo=todo,
            phase=phase,
            workflow_id="wf-isolation",
            session_id=f"sess-{phase.phase_id}",
            repos=[],
        )

    return workspace


@pytest.mark.unit
@pytest.mark.anyio
async def test_phase_scoped_skill_is_absent_from_a_phase_that_does_not_declare_it() -> None:
    """A phase-scope skill on phase A must not reach phase B's workspace."""
    storage, lock = await _register_two_skills()

    workflow = WorkflowDefinition.from_yaml(_WORKFLOW_YAML)
    resolution_service = SkillResolutionService(lock_projection=lock)

    workspaces: dict[str, AsyncMock] = {}
    for phase_yaml in workflow.phases:
        phase_def = phase_yaml.to_domain()
        resolved = await resolution_service.resolve_for_phase(
            list(workflow.skills),
            list(phase_def.skills),
        )
        phase = ExecutablePhase(
            phase_id=phase_def.phase_id,
            name=phase_def.name,
            order=phase_def.order,
            description="",
            agent_config=AgentConfiguration(provider="claude"),
            prompt_template="Go.",
            output_artifact_type="text",
            skills=resolved,
        )
        workspaces[phase_def.phase_id] = await _provision(phase, storage)

    investigate = workspaces["investigate"]
    summarize = workspaces["summarize"]

    # Phase A: both skills materialized and installed.
    investigate_paths = _injected_paths(investigate)
    assert f".syn-skills/{_SHARED_SKILL}/SKILL.md" in investigate_paths
    assert f".syn-skills/{_PHASE_ONLY_SKILL}/SKILL.md" in investigate_paths
    assert _skills_add_argv(investigate) == [
        [
            "skills",
            "add",
            f"/workspace/.syn-skills/{_SHARED_SKILL}",
            "--agent",
            "claude-code",
            "-y",
        ],
        [
            "skills",
            "add",
            f"/workspace/.syn-skills/{_PHASE_ONLY_SKILL}",
            "--agent",
            "claude-code",
            "-y",
        ],
    ]

    # Phase B: workflow-scope skill only. This is the assertion that was missing.
    summarize_paths = _injected_paths(summarize)
    assert f".syn-skills/{_SHARED_SKILL}/SKILL.md" in summarize_paths
    assert not any(_PHASE_ONLY_SKILL in path for path in summarize_paths), (
        f"phase-scope skill {_PHASE_ONLY_SKILL!r} leaked into a phase that does not "
        f"declare it: {summarize_paths}"
    )
    assert _skills_add_argv(summarize) == [
        [
            "skills",
            "add",
            f"/workspace/.syn-skills/{_SHARED_SKILL}",
            "--agent",
            "claude-code",
            "-y",
        ],
    ]
