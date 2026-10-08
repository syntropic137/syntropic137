"""PC-116: a phase that declares ``requires_verdict`` fails when it reports none.

No verdict advances by order, on purpose (`ReviewVerdict`), so a verify phase
that forgot ``review_verdict`` read exactly like one that found something to
fix. The declaration turns that silence into a failed phase for the phases
that are reviews, and leaves every other phase as it was.

These drive the whole production path - authored YAML -> template aggregate ->
`ExecuteWorkflowHandler` -> `processor.run()` - and assert on the RECORDED
outcome, because the claim is about what the execution does, not about what a
helper returns. A declaration dropped at any hop on the way leaves the
declared-and-silent case completing, which is the case below that would go red.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _run_authored

pytestmark = pytest.mark.unit


def _workflow(*, requires_verdict: bool) -> str:
    declaration = "    requires_verdict: true\n" if requires_verdict else ""
    return (
        "id: wf-pc116\n"
        "name: Review then finish\n"
        "requires_repos: false\n"
        "phases:\n"
        "  - id: verify\n"
        "    name: Verify\n"
        "    order: 1\n"
        "    prompt_template: review the change\n"
        f"{declaration}"
        "  - id: finalize\n"
        "    name: Finalize\n"
        "    order: 2\n"
        "    prompt_template: act on the review\n"
    )


def _reports(extra: str = "") -> str:
    return (
        "The review is written up above.\n\n"
        f'TASK_RESULT: {{"success": true{extra}, "comments": "reviewed"}}\n'
        "TASK_RESULT_END"
    )


class TestADeclaredReviewMustReportItsVerdict:
    async def test_a_reported_verdict_completes(self) -> None:
        fake = FakeAgentExecutionHandler.success(says=_reports(', "review_verdict": "blocked"'))

        result = await _run_authored(_workflow(requires_verdict=True), fake)

        assert result.status == "completed", result.error_message
        assert fake.call_count == 2

    async def test_no_verdict_fails_the_phase_and_says_why(self) -> None:
        fake = FakeAgentExecutionHandler.success(says=_reports())

        result = await _run_authored(_workflow(requires_verdict=True), fake)

        assert result.status == "failed", (
            f"Expected 'failed' but got '{result.status}'. The phase declares "
            "requires_verdict and named none; a pass here means the declaration "
            "was dropped between the YAML and `completion_failure`."
        )
        assert result.error_message is not None
        assert "verify produced no verdict" in result.error_message
        assert "phase verify" in result.error_message
        # The agent claimed success, so this is not its own refusal: the
        # platform detected the gap, and it is counted as the platform's.
        assert result.failure_classification is FailureClassification.PLATFORM
        assert fake.call_count == 1, "The next phase ran on a review that said nothing."

    async def test_a_misspelled_verdict_is_no_verdict(self) -> None:
        fake = FakeAgentExecutionHandler.success(says=_reports(', "review_verdict": "approved"'))

        result = await _run_authored(_workflow(requires_verdict=True), fake)

        assert result.status == "failed"
        assert result.error_message is not None
        assert "verify produced no verdict" in result.error_message

    async def test_a_reported_refusal_keeps_its_own_failure(self) -> None:
        """The run's own outcome outranks the declaration: a refusal is not relabelled."""
        fake = FakeAgentExecutionHandler.success(
            says='TASK_RESULT: {"success": false, "comments": "no input"}\nTASK_RESULT_END'
        )

        result = await _run_authored(_workflow(requires_verdict=True), fake)

        assert result.status == "failed"
        assert result.error_message is not None
        assert "verify produced no verdict" not in result.error_message
        assert result.failure_classification is FailureClassification.CORRECT_REFUSAL


class TestAnUndeclaredPhaseIsUnchanged:
    async def test_no_verdict_still_advances_by_order(self) -> None:
        """The "None advances by order" rule stands for every phase that did not declare."""
        fake = FakeAgentExecutionHandler.success(says=_reports())

        result = await _run_authored(_workflow(requires_verdict=False), fake)

        assert result.status == "completed", result.error_message
        assert fake.call_count == 2
