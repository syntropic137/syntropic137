"""Every execution entry point refuses a stored ``claude-interactive`` template.

The domain guard is covered in
``syn_domain/.../execute_workflow/test_removed_provider_execution.py``. This
file covers the two API-side entry points that load PERSISTED templates rather
than parsing YAML, plus the command builder that used to fall through:

- the GitHub-trigger dispatch path (``BackgroundWorkflowDispatcher``);
- the ``POST /workflows/{id}/execute`` request validation;
- ``_build_agent_command``, which must be exhaustive.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import HTTPException

from syn_api._wiring import BackgroundWorkflowDispatcher, _build_agent_command
from syn_api.routes.executions.commands import _check_phase_providers
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_removed_provider_execution import (
    WORKFLOW_ID,
    _make_handler,
    _rehydrate,
)
from syn_shared.agents import (
    REMOVED_INTERACTIVE_PROVIDER,
    AgentProvider,
    UnsupportedAgentProviderError,
)


def _phase(provider: str) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="p1",
        name="Phase 1",
        order=1,
        agent_config=AgentConfiguration(provider=provider),
    )


@pytest.mark.unit
def test_agent_command_raises_for_the_removed_provider() -> None:
    """The fall-through is gone: a removed provider cannot become ``claude -p``."""
    with pytest.raises(UnsupportedAgentProviderError) as exc_info:
        _build_agent_command(_phase(REMOVED_INTERACTIVE_PROVIDER), "do the thing")

    assert REMOVED_INTERACTIVE_PROVIDER in str(exc_info.value)


@pytest.mark.unit
def test_agent_command_raises_for_an_unknown_provider() -> None:
    """Exhaustive means exhaustive - not "everything that is not codex is claude"."""
    with pytest.raises(UnsupportedAgentProviderError):
        _build_agent_command(_phase("gemini"), "do the thing")


@pytest.mark.unit
def test_agent_command_still_builds_both_headless_providers() -> None:
    assert _build_agent_command(_phase(AgentProvider.CLAUDE), "x")[0] == "claude"
    assert _build_agent_command(_phase(AgentProvider.CODEX), "x")[0] == "codex"


@pytest.mark.unit
def test_execute_request_validation_rejects_a_stored_interactive_template() -> None:
    """The API answers 422 up front instead of 200-then-BackgroundTask-failure."""
    with pytest.raises(HTTPException) as exc_info:
        _check_phase_providers(_rehydrate())

    assert exc_info.value.status_code == 422
    assert REMOVED_INTERACTIVE_PROVIDER in str(exc_info.value.detail)


@pytest.mark.unit
def test_execute_request_validation_accepts_a_stored_claude_template() -> None:
    _check_phase_providers(_rehydrate(provider=AgentProvider.CLAUDE))


@pytest.mark.unit
async def test_trigger_dispatch_of_a_stored_interactive_template_runs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A GitHub trigger loads the persisted template, so it needs the same refusal.

    The dispatcher deliberately swallows exceptions (a failed background
    execution must not kill the projection loop), so the assertion that matters
    is the infrastructure one: no workspace, no agent command, no execution.
    """
    handler, spies = _make_handler(_rehydrate())
    dispatcher = BackgroundWorkflowDispatcher(handler, max_concurrent=1)

    with caplog.at_level(logging.ERROR):
        await dispatcher.run_workflow(WORKFLOW_ID, inputs={}, execution_id="exec-trigger")
        await asyncio.gather(*list(dispatcher._tasks))

    spies.workspace_service.create_workspace.assert_not_called()
    spies.command_builder.assert_not_called()
    spies.execution_repository.save.assert_not_awaited()
    assert REMOVED_INTERACTIVE_PROVIDER in caplog.text
