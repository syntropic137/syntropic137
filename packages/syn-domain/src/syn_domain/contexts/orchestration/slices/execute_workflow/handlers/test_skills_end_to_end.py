"""End-to-end integration test for the skills pipeline (issue #772, Task 11).

Exercises the whole registration-to-install chain in one test, wiring only
in-memory/fake adapters at the infrastructure boundary:

1. ``RegisterSkillHandler`` registers a skill tree against in-memory skill
   storage and an in-memory registration repository.
2. The registration result is fed into ``SkillLockProjection`` the same way
   the register-skill route's background projector would (mirrors the
   seeding pattern in ``test_skill_resolution_service.py``).
3. A workflow YAML string with a phase-scoped ``skills:`` entry (three-
   segment shorthand) and an ``agent:`` block selecting ``agent_id: codex``
   is parsed via ``WorkflowDefinition.from_yaml`` into a ``PhaseDefinition``.
4. ``SkillResolutionService`` resolves the phase's declared ``SkillRef``
   against the lock projection into a ``ResolvedSkill``.
5. ``WorkspaceProvisionHandler.handle`` runs with a real ``SkillMaterializer``
   over the same in-memory storage and a fake ``ManagedWorkspace``, proving
   the resolved skill is materialized into the workspace and installed via
   the skills CLI for the phase's selected agent.
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
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
)
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

_SKILL_MD = b"""---
name: code-review
description: Reviews a diff for correctness bugs.
---

Do the review.
"""

_WORKFLOW_YAML = """
id: e2e-skills-workflow
name: E2E Skills Workflow
phases:
  - id: review
    name: Review
    order: 1
    prompt_template: "Review this."
    agent:
      agent_id: codex
    skills:
      - "example/code-review-repo/code-review@1.0.0"
"""


async def _register_and_lock_skill() -> tuple[object, SkillLockProjection]:
    """Register one skill through the real handler and feed the lock projection.

    Returns (storage, lock_projection) so callers can build a materializer
    over the same storage instance the registration used.
    """
    storage = get_test_skill_storage()
    repo = InMemorySkillRegistrationRepository()
    handler = RegisterSkillHandler(storage=storage, repo=repo)

    result = await handler.handle(
        source_url="https://github.com/example/code-review-repo",
        version="1.0.0",
        skill_name=None,
        files=[SkillFile(rel_path="SKILL.md", content=_SKILL_MD)],
    )
    assert result.skill_name == "code-review"

    lock = SkillLockProjection(InMemoryProjectionStore())
    await lock.on_skill_registered(
        {
            "source_url": result.source_url,
            "version": result.version,
            "skill_name": result.skill_name,
            "resolved_sha": result.resolved_sha,
            "tree_storage_prefix": result.tree_storage_prefix,
            "registered_at": "2026-07-04T00:00:00+00:00",
        }
    )
    return storage, lock


def _fake_workspace() -> AsyncMock:
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
    workspace.inject_files = AsyncMock()
    workspace.workspace_id = "ws-e2e"
    workspace.execute = AsyncMock(
        return_value=ExecutionResult(exit_code=0, success=True, duration_ms=1.0)
    )
    return workspace


@pytest.mark.unit
@pytest.mark.anyio
async def test_skills_pipeline_end_to_end_registration_to_install() -> None:
    """Register -> lock -> YAML resolve -> materialize -> install, one flow."""
    storage, lock = await _register_and_lock_skill()

    workflow = WorkflowDefinition.from_yaml(_WORKFLOW_YAML)
    phase_yaml = workflow.phases[0]
    phase_def = phase_yaml.to_domain()
    assert phase_def.agent_id == "codex"
    assert len(phase_def.skills) == 1

    resolution_service = SkillResolutionService(lock_projection=lock)
    resolved_skills = await resolution_service.resolve_for_phase(
        list(workflow.skills),
        list(phase_def.skills),
    )
    assert len(resolved_skills) == 1
    assert resolved_skills[0].skill_name == "code-review"

    phase = ExecutablePhase(
        phase_id="phase-1",
        name="Review",
        order=1,
        description="",
        # Headless codex phase: skills-cli agent key derives from provider.
        agent_config=AgentConfiguration(provider=phase_def.provider or "codex"),
        prompt_template="Review this.",
        output_artifact_type="text",
        skills=resolved_skills,
    )

    workspace = _fake_workspace()
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm

    async def fake_prompt_builder(*_args: object, **_kwargs: object) -> str:
        return "Review this."

    def fake_command_builder(_phase: object, prompt: str) -> list[str]:
        return ["claude", "--print", prompt]

    materializer = SkillMaterializer(storage=storage)  # type: ignore[arg-type]

    handler = WorkspaceProvisionHandler(
        workspace_service=workspace_service,
        prompt_builder=fake_prompt_builder,
        command_builder=fake_command_builder,
        skill_materializer=materializer,
    )

    todo = TodoItem(
        execution_id="exec-1",
        action=TodoAction.PROVISION_WORKSPACE,
        phase_id="phase-1",
    )

    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as MockSecrets:
        MockSecrets.create = AsyncMock(return_value=MagicMock())
        await handler.handle(
            todo=todo,
            phase=phase,
            workflow_id="wf-1",
            session_id="sess-1",
            repos=[],
        )

    inject_calls = workspace.inject_files.call_args_list
    skill_inject_call = next(
        (
            call
            for call in inject_calls
            if any(rel_path == ".syn-skills/code-review/SKILL.md" for rel_path, _ in call.args[0])
        ),
        None,
    )
    assert skill_inject_call is not None, "expected SKILL.md to be injected into the workspace"
    injected_files = dict(skill_inject_call.args[0])
    assert injected_files[".syn-skills/code-review/SKILL.md"] == _SKILL_MD

    workspace.execute.assert_awaited_with(
        ["skills", "add", "/workspace/.syn-skills/code-review", "--agent", "codex", "-y"],
        timeout_seconds=120,
        working_directory="/workspace",
    )
