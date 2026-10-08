"""A phase that required delegation does not complete without one (#894)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    AgentYamlDefinition,
    PhaseYamlDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    FailureClassification,
)
from syn_domain.contexts.orchestration.ports import (
    DelegationAttempt,
    DelegationEvidenceUnavailableError,
    DelegationOutcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    NonZeroExitError,
    failure_account,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    _build_agent_config_from_phase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegation import (
    DelegationFailedError,
    DelegationFailureReason,
    completion_failure,
    delegation_failure,
)

pytestmark = pytest.mark.unit

_WORKSPACE = MagicMock()


class _Evidence:
    def __init__(self, attempts: tuple[DelegationAttempt, ...] | None) -> None:
        self._attempts = attempts

    async def attempts(self, workspace: object) -> tuple[DelegationAttempt, ...]:
        if self._attempts is None:
            raise DelegationEvidenceUnavailableError("journal unreadable")
        return self._attempts


def _attempt(
    outcome: DelegationOutcome | None, exit_code: int | None = None, *, target: str = "codex"
) -> DelegationAttempt:
    return DelegationAttempt(
        delegate_id="child-7", target_harness=target, outcome=outcome, exit_code=exit_code
    )


async def _reason(evidence: _Evidence | None) -> DelegationFailureReason | None:
    failure = await delegation_failure(
        evidence, _WORKSPACE, phase_id="implement", required_delegate="codex"
    )
    return None if failure is None else failure.delegation_failure.reason


@pytest.mark.asyncio
async def test_the_issue_case_no_delegate_ran_fails_the_phase() -> None:
    assert await _reason(_Evidence(())) is DelegationFailureReason.NOT_ATTEMPTED


@pytest.mark.asyncio
async def test_a_delegate_that_failed_fails_the_phase_and_is_named() -> None:
    failure = await delegation_failure(
        _Evidence((_attempt(DelegationOutcome.FAILED, exit_code=1),)),
        _WORKSPACE,
        phase_id="implement",
        required_delegate="codex",
        requires_verdict=False,
    )
    assert failure is not None
    assert failure.delegation_failure.reason is DelegationFailureReason.FAILED
    assert "delegate child-7 -> codex: failed (exit_code=1)" in str(failure)
    assert failure.delegation_failure.required_delegate == "codex"


@pytest.mark.asyncio
async def test_a_delegate_that_never_reported_is_not_a_success() -> None:
    assert await _reason(_Evidence((_attempt(None),))) is DelegationFailureReason.FAILED


@pytest.mark.asyncio
async def test_an_unreadable_record_is_not_a_success() -> None:
    assert await _reason(_Evidence(None)) is DelegationFailureReason.UNVERIFIABLE
    assert await _reason(None) is DelegationFailureReason.UNVERIFIABLE


@pytest.mark.asyncio
async def test_one_successful_delegate_completes_the_phase() -> None:
    attempts = (_attempt(DelegationOutcome.FAILED, 1), _attempt(DelegationOutcome.SUCCEEDED, 0))
    assert await _reason(_Evidence(attempts)) is None


@pytest.mark.asyncio
async def test_a_phase_that_required_no_delegation_is_never_asked() -> None:
    assert (
        await delegation_failure(None, None, phase_id="implement", required_delegate=None) is None
    )


@pytest.mark.asyncio
async def test_a_successful_delegate_to_the_wrong_harness_does_not_satisfy_the_gate() -> None:
    """Codex review of #1590: a claude phase's claude child is not its codex delegate."""
    failure = await delegation_failure(
        _Evidence((_attempt(DelegationOutcome.SUCCEEDED, 0, target="claude"),)),
        _WORKSPACE,
        phase_id="implement",
        required_delegate="codex",
        requires_verdict=False,
    )
    assert failure is not None
    assert failure.delegation_failure.reason is DelegationFailureReason.NOT_ATTEMPTED
    # The misdirected delegate is kept: it is what explains the missing one.
    assert "delegate child-7 -> claude: succeeded" in str(failure)


@pytest.mark.asyncio
async def test_a_wrong_harness_success_does_not_rescue_a_failed_required_delegate() -> None:
    attempts = (
        _attempt(DelegationOutcome.FAILED, 1),
        _attempt(DelegationOutcome.SUCCEEDED, 0, target="claude"),
    )
    assert await _reason(_Evidence(attempts)) is DelegationFailureReason.FAILED


@pytest.mark.parametrize(("provider", "required"), [("claude", "codex"), ("codex", "claude")])
def test_the_required_delegate_is_the_other_harness_of_the_phase_provider(
    provider: str, required: str
) -> None:
    config = AgentConfiguration(provider=provider, allow_delegation=True, require_delegation=True)
    assert config.required_delegate == required


def test_permission_alone_requires_no_delegate() -> None:
    """Codex review of #1590: ``allow_delegation`` means MAY, never MUST."""
    assert AgentConfiguration(provider="claude", allow_delegation=True).required_delegate is None


def _run(exit_code: int) -> MagicMock:
    """An agent run as `phase_failure` reads it: exited `exit_code`, said nothing against itself."""
    result = MagicMock()
    result.command.exit_code = exit_code
    result.stream_result.error_reason = None
    result.stream_result.interrupt_requested = False
    result.stream_result.verdict.refuses_completion = False
    return result


@pytest.mark.asyncio
async def test_the_issue_case_end_to_end_a_clean_green_run_is_failed_as_platform() -> None:
    """What the processor calls, and what the failure is then counted as.

    Exit 0 and no refusal is a run `phase_failure` completes; that is the #894
    phase. The delegation gate must turn it into a failure that the phase's
    `error_message` names and `failure_account` counts as `platform` - the
    two things the execution API shows.
    """
    failure = await completion_failure(
        _run(0),
        phase_id="implement",
        evidence=_Evidence((_attempt(DelegationOutcome.FAILED, exit_code=3),)),
        workspace=_WORKSPACE,
        required_delegate="codex",
        requires_verdict=False,
    )
    assert isinstance(failure, DelegationFailedError)
    assert "delegate child-7 -> codex: failed (exit_code=3)" in str(failure)
    assert failure_account(failure).classification is FailureClassification.PLATFORM


@pytest.mark.asyncio
async def test_a_run_that_already_failed_keeps_its_own_failure() -> None:
    failure = await completion_failure(
        _run(1),
        phase_id="implement",
        evidence=_Evidence(()),
        workspace=_WORKSPACE,
        required_delegate="codex",
        requires_verdict=False,
    )
    assert isinstance(failure, NonZeroExitError)


@pytest.mark.asyncio
async def test_a_phase_permitted_to_delegate_that_did_the_work_itself_completes() -> None:
    """Codex review of #1590: the permission is not gated.

    Driven through the phase's own `AgentConfiguration`, the value the
    processor passes, with an evidence source that has NOTHING in it - the
    shape the pre-fix gate failed as `not_attempted`.
    """
    config = AgentConfiguration(provider="claude", allow_delegation=True)
    assert (
        await completion_failure(
            _run(0),
            phase_id="implement",
            evidence=_Evidence(()),
            workspace=_WORKSPACE,
            required_delegate=config.required_delegate,
            requires_verdict=False,
        )
        is None
    )


@pytest.mark.asyncio
async def test_a_phase_required_to_delegate_that_did_the_work_itself_fails() -> None:
    config = AgentConfiguration(provider="claude", allow_delegation=True, require_delegation=True)
    failure = await completion_failure(
        _run(0),
        phase_id="implement",
        evidence=_Evidence(()),
        workspace=_WORKSPACE,
        required_delegate=config.required_delegate,
        requires_verdict=False,
    )
    assert isinstance(failure, DelegationFailedError)
    assert failure.delegation_failure.reason is DelegationFailureReason.NOT_ATTEMPTED


def test_require_delegation_reaches_the_gate_from_the_workflow_yaml() -> None:
    """Every hop between the author's YAML and the value the processor gates on.

    A constructor that dropped `require_delegation` would leave the phase
    permitted and not required, one hop before the gate (#1039's shape). The
    YAML also declares the permission, which the validator insists on; the
    stored-template branch below proves the execution boundary derives it.
    """
    phase = PhaseYamlDefinition(
        id="implement",
        name="Implement",
        order=1,
        prompt_template="go",
        agent=AgentYamlDefinition(provider="codex", allow_delegation=True, require_delegation=True),
    ).to_domain()
    assert _build_agent_config_from_phase(phase).required_delegate == "claude"

    stored = phase.model_copy(update={"allow_delegation": False, "provider": None})
    config = _build_agent_config_from_phase(stored)
    assert config.allow_delegation is True
    assert config.required_delegate == "codex"


def test_a_requirement_without_the_permission_is_refused_at_authoring() -> None:
    with pytest.raises(ValueError, match=r"require_delegation needs agent\.allow_delegation"):
        AgentYamlDefinition(require_delegation=True)
