"""An execution must fail when the capability it validated is broken (#1085).

`exec-eca6f017c58f` ran `selfhost-github-ops-v1`, reported

    ISSUE: 1084
    COMMENT: FAILED
    CLOSE: FAILED
    TOKEN_SCOPE: GraphQL: Resource not accessible by integration

and finished `completed`, green, at $0.22. Nothing was wrong with the agent:
it did what it was asked, found the App's token could not comment or close,
and said so. Execution status answered a different question - "did the agent
finish" - so the one workflow whose entire job is to detect a broken
deployment could not report one.

WHY THE TEST IS AT `processor.run()` AND NOT ON THE MATCHER. The matcher is
twelve lines and would pass whether or not anything called it; the field it
reads has five hops between the YAML and the phase, and #1039 is the standing
proof that a phase field can be validated, persisted, projected, re-exported
and still arrive as its default. What has to be measured is the STATUS the
operator sees, which is what these drive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import (
    FakeArtifactRepository,
    FakeExecutionRepository,
    FakeSessionRepository,
    _noop_command_builder,
    _noop_prompt_builder,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        WorkflowExecutionResult,
    )

pytestmark = pytest.mark.unit

#: The report `exec-eca6f017c58f` actually produced, verbatim.
_BROKEN_TOKEN_REPORT = (
    "ISSUE: 1084\n"
    "COMMENT: FAILED\n"
    "CLOSE: FAILED\n"
    "TOKEN_SCOPE: GraphQL: Resource not accessible by integration\n"
)

_WORKING_TOKEN_REPORT = "ISSUE: 1084\nCOMMENT: ok\nCLOSE: ok\nTOKEN_SCOPE: none\n"

#: The assertions `workflows/validation/workflows/github-ops/workflow.yaml`
#: declares. Copied rather than loaded so this test states the behaviour it
#: expects instead of agreeing with whatever the YAML currently says.
_GITHUB_OPS_ASSERTS = (
    r"^ISSUE: [0-9]+$",
    r"^COMMENT: ok$",
    r"^CLOSE: ok$",
    r"^TOKEN_SCOPE: none$",
)


def _make_processor(agent_handler: FakeAgentExecutionHandler) -> WorkflowExecutionProcessor:
    return WorkflowExecutionProcessor(
        execution_repository=FakeExecutionRepository(),
        session_repository=FakeSessionRepository(),
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=FakeArtifactRepository(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=_noop_prompt_builder,
        command_builder=_noop_command_builder,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=agent_handler,
        session_capture=None,  # type: ignore[arg-type]
    )


def _phase(asserts: tuple[str, ...]) -> list[ExecutablePhase]:
    return [
        ExecutablePhase(
            phase_id="exercise",
            name="Open, comment, close",
            order=1,
            agent_config=AgentConfiguration(),
            prompt_template="do the thing",
            output_artifact_type="text",
            timeout_seconds=30,
            asserts=asserts,
        )
    ]


async def _run(
    handler: FakeAgentExecutionHandler, asserts: tuple[str, ...]
) -> WorkflowExecutionResult:
    return await _make_processor(handler).run(
        workflow_id="selfhost-github-ops-v1",
        workflow_name="Validation: GitHub write access",
        phases=_phase(asserts),
        inputs={},
        execution_id="exec-eca6f017c58f",
    )


class TestAnAgentThatFinishesIsNotAPass:
    async def test_a_report_contradicting_the_assertion_fails_the_execution(self) -> None:
        """THE regression. Exit code 0, a real report, a broken capability."""
        handler = FakeAgentExecutionHandler.success(
            output_files={"report.md": _BROKEN_TOKEN_REPORT}
        )

        result = await _run(handler, _GITHUB_OPS_ASSERTS)

        assert result.status == "failed", (
            f"Expected 'failed' but got '{result.status}'. The phase reported "
            "COMMENT: FAILED and CLOSE: FAILED - the App's token cannot write - "
            "and the agent exited 0. If status still says completed, the "
            "declared assertion is not being applied and #1085 is back."
        )

    async def test_the_failure_names_the_unmet_assertion(self) -> None:
        """An operator reads this message to learn WHICH capability broke.

        `failed` alone sends them back to the transcript, which is the cost
        #1085 was raised about in the first place.
        """
        handler = FakeAgentExecutionHandler.success(
            output_files={"report.md": _BROKEN_TOKEN_REPORT}
        )

        result = await _run(handler, _GITHUB_OPS_ASSERTS)

        assert result.error_message is not None
        assert "^CLOSE: ok$" in result.error_message
        assert "^COMMENT: ok$" in result.error_message
        # ISSUE: 1084 DID match, so naming it would misdirect the reader.
        assert "^ISSUE: " not in result.error_message

    async def test_a_report_satisfying_every_assertion_completes(self) -> None:
        """The other half of the pair.

        Without it, a matcher that refused everything would satisfy the test
        above, and every validation run would fail forever.
        """
        handler = FakeAgentExecutionHandler.success(
            output_files={"report.md": _WORKING_TOKEN_REPORT}
        )

        result = await _run(handler, _GITHUB_OPS_ASSERTS)

        assert result.status == "completed", f"Expected 'completed', got '{result.status}'."

    async def test_a_phase_writing_no_report_at_all_fails(self) -> None:
        """Silence is not a pass.

        The failure mode that worried me most: assertions match collected
        artifacts, so a phase that prints its report instead of writing it has
        nothing to match. That must fail rather than vacuously succeed.
        """
        handler = FakeAgentExecutionHandler.success()

        result = await _run(handler, _GITHUB_OPS_ASSERTS)

        assert result.status == "failed", f"Expected 'failed', got '{result.status}'."


class TestPhasesThatDeclareNothingAreUnaffected:
    async def test_the_same_broken_report_still_completes_without_asserts(self) -> None:
        """Every workflow written before #1085 declares no assertions, and must
        keep being judged on the agent's exit code alone.

        This is also the control that proves the test above measures the
        DECLARATION and not the report text: same agent, same file, opposite
        status."""
        handler = FakeAgentExecutionHandler.success(
            output_files={"report.md": _BROKEN_TOKEN_REPORT}
        )

        result = await _run(handler, ())

        assert result.status == "completed", (
            f"Expected 'completed' but got '{result.status}'. A phase that "
            "declares no assertions must behave exactly as it did before."
        )
