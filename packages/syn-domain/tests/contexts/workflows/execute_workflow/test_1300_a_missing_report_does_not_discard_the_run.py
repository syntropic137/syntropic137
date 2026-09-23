"""#1300: a phase that wrote no file must not discard work that is already done.

THE MEASUREMENT. Three `implement` phases, $38.62, in one window. Every one of
them at 1 of 4 phases complete, which means the change had been made and the
branch pushed; every one discarded for a missing report rather than a defect.
Prompting was tried first and was not enough - `sdlc-implement-v2` names the
output path in every phase, was verified deployed, and a v2 run failed this way
anyway.

WHY THESE DRIVE THE WHOLE PROCESSOR. The collector already had the agent's last
message in hand and simply did not consult it on this branch, so a test that
called the collector directly would have gone green the moment that one `if`
changed while proving nothing about what a run leaves behind. What #1300 costs
is paid in the STORED RECORD: whether the execution still holds something worth
reading, whether the next phase gets it, and whether anyone can find the branch.
So each test below runs `WorkflowExecutionProcessor.run()` end to end and then
reads the artifact aggregate, the phase's event, and the workspace the
downstream phase was handed.

THE DECISION THESE PIN, which was open when the work started: a salvaged phase
COMPLETES rather than failing. Failing would keep the declared contract loudly
visible and would also discard the run, which is the entire cost being measured.
The contract stays visible in the record instead - `RECOVERED_TITLE_MARKER` in
the title the API serves, the banner as the first line of what the next phase
reads - and `test_the_salvage_never_passes_for_the_real_thing` is what stops
that visibility from being quietly traded away.

The git repositories here are real, and every SHA asserted is read back out of
the ORIGIN, never copied from a value the code returned - the discipline #1200's
suite established, for the same reason: a branch report derived from a variable
rather than from a ref that exists would pass any test built on a double.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.artifact_recovery import (
    RECOVERED_SOURCE_PATH,
    RECOVERED_TITLE_MARKER,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.branch_observation import (
    PhaseStartingPoints,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _BRANCH,
    _Clone,
    _clone_repository,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor, _two_phase_workflow

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import Runner
    from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
        GitWorkspace,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

#: What the implement phase SAID, having written nothing. Deliberately unlike
#: anything any fixture writes to disk, so content carrying it can only have
#: arrived through the salvage.
SAID = (
    "Done. Replaced the hand-rolled retry with tenacity and pushed the branch; "
    "all 94 unit tests pass locally."
)

#: An agent that says nothing at all - the phase that genuinely produced
#: nothing, which must still fail.
SAID_NOTHING = None


class _RecordingAgent(FakeAgentExecutionHandler):
    """The success double, plus what each phase FOUND in its workspace.

    The salvage is only worth anything if the next phase can read it, and
    "the artifact was stored" does not imply "the handoff carried it" - those
    are two hops and #988 is the issue where they came apart. So the double
    records its own injected input tree, which is the only place that question
    can be asked from.
    """

    def __init__(self, *, says: str | None, does: Callable[[], object] | None = None) -> None:
        super().__init__(interrupt=False, exit_code=0, says=says)
        self.injected: list[dict[str, str]] = []
        #: The work the FIRST phase does before returning - in the incident,
        #: a commit and a push. It has to happen here, inside the agent's
        #: run, because #1200 reports only what THIS phase pushed and not
        #: what it inherited: a fixture that pushed before the phase started
        #: would be a phase that changed nothing, and would correctly be told
        #: there is nothing to report.
        self._does = does

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner | None = None,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        found = await workspace.collect_files(patterns=["artifacts/input/**/*"])
        self.injected.append({path: body.decode() for path, body in found})
        if self._does is not None and self.call_count == 0:
            self._does()
        return await super().handle(
            todo,
            workspace,
            agent_env,
            claude_cmd,
            session_id,
            agent_model,
            timeout_seconds,
            collector,
            *([] if runner is None else [runner]),  # type: ignore[arg-type]
            on_launch=on_launch,
        )


class _StartingPointsOn(PhaseStartingPoints):
    """Starting points taken against a REAL repository rather than the double.

    The processor records a starting point from whatever workspace it hands
    the phase, and in this suite that is the in-memory backend, which has no
    git in it. Substituting the repository - and only the repository - keeps
    the production call, the production moment and the production reading
    (`record_phase_starting_point` runs for real, before the agent is allowed
    to run) while giving it something git can actually answer about.
    """

    def __init__(self, repository: GitWorkspace) -> None:
        super().__init__()
        self._repository = repository

    async def record(self, phase_id: str, workspace: GitWorkspace) -> None:
        await super().record(phase_id, self._repository)


class _KeepingArtifacts:
    """An artifact repository that keeps what it was given, as a store does."""

    def __init__(self) -> None:
        self.saved: list[ArtifactAggregate] = []

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def get_by_id(self, aggregate_id: str) -> None:
        return None


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    """A phase's starting point: a clone on a feature branch, pushed and level."""
    return _clone_repository(tmp_path)


class _Run:
    """One finished execution, and the record it left behind."""

    def __init__(
        self,
        result: object,
        agent: _RecordingAgent,
        artifacts: _KeepingArtifacts,
    ) -> None:
        self.result = result
        self.agent = agent
        self.artifacts = artifacts

    @property
    def stored(self) -> list[tuple[str, str]]:
        """(title, content) of every artifact that actually reached the store.

        Read off the aggregate rather than the arguments it was built from, so
        a value dropped at the command would be visible here.
        """
        return [(a.title or "", a.content or "") for a in self.artifacts.saved]


async def _run_writing_nothing(clone: _Clone, *, says: str | None):
    """Run a two-phase workflow whose first phase declares output and writes none.

    The phase commits and pushes DURING its run, then writes no file: the
    incident exactly - the work is finished and durable on a remote, and only
    the report is missing.
    """

    def do_the_work() -> None:
        clone.commit("implementation.py", "the work the phase actually did\n")
        clone.git("push", "origin", _BRANCH)

    agent = _RecordingAgent(says=says, does=do_the_work)
    artifacts = _KeepingArtifacts()
    processor = _make_processor(agent)
    processor._artifact_repo = artifacts  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
    processor._runtime._starting_points = _StartingPointsOn(  # pyright: ignore[reportPrivateUsage]
        cast("GitWorkspace", clone.workspace)
    )

    result = await processor.run(
        workflow_id="wf-1300",
        workflow_name="Fix Issue",
        phases=_two_phase_workflow(first_declares=("markdown",)),
        inputs={},
        execution_id="exec-1300",
    )
    return _Run(result, agent, artifacts)


class TestTheRunIsNotDiscarded:
    """The measured cost: a finished phase thrown away over a missing report."""

    async def test_the_execution_completes_and_the_next_phase_runs(self, clone: _Clone) -> None:
        run = await _run_writing_nothing(clone, says=SAID)

        assert run.result.status == "completed", (  # type: ignore[attr-defined]
            f"got {run.result.status!r} ({run.result.error_message!r}). "  # type: ignore[attr-defined]
            "The phase made its change, pushed its branch and said so; only "
            "the report was missing. Failing here is #1300."
        )
        assert run.agent.call_count == 2, (
            f"the downstream phase never ran ({run.agent.call_count} agent "
            "calls) - the run was discarded, which is the whole cost"
        )

    async def test_the_stored_artifact_is_what_the_phase_said(self, clone: _Clone) -> None:
        """A usable artifact, in the store, not merely an execution that passed."""
        run = await _run_writing_nothing(clone, says=SAID)

        titles_and_contents = run.stored
        assert len(titles_and_contents) == 1, f"expected one artifact, got {titles_and_contents}"
        ((title, content),) = titles_and_contents
        assert SAID in content, f"the phase's conclusion must be the content, got {content!r}"
        assert RECOVERED_TITLE_MARKER in title, (
            f"an artifact that arrived by salvage must say so in the title an "
            f"API listing shows, got {title!r}"
        )
        assert "#1300" in content, "the content must name the incident it came from"


class TestTheBranchIsNotLost:
    """Where the surviving work is, named in the record a reader actually gets.

    THE CONSEQUENCE OF COMPLETING RATHER THAN FAILING, and the reason this
    class exists. #1200 appends the branch report to a FAILURE, and a salvaged
    phase does not fail - so choosing to complete would have silently removed
    the one place the branch was named. The report moves into the artifact.
    """

    async def test_the_artifact_names_the_branch_and_the_commit_that_survived(
        self, clone: _Clone
    ) -> None:
        """Read back out of the origin, so the SHA is one a reader can fetch."""
        run = await _run_writing_nothing(clone, says=SAID)

        on_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
        ((_, content),) = run.stored
        assert _BRANCH in content, (
            f"the salvaged artifact must name the surviving branch, got {content!r}"
        )
        assert on_remote in content, (
            f"and the commit it is at ({on_remote}), so the work can be picked "
            f"up instead of redone, got {content!r}"
        )

    async def test_it_is_named_even_when_the_agent_never_mentioned_it(self, clone: _Clone) -> None:
        """The message is the agent's claim; the branch report is git's reading.

        A conclusion that never mentions the branch is a real and common last
        message. If the branch were only ever named because the agent happened
        to name it, this feature would be a coincidence rather than a
        guarantee.

        The message here is deliberately a usable conclusion that is silent
        about WHERE the work went - not a bare sign-off, which since #1300's
        review reports nothing and correctly fails the phase instead of being
        salvaged (`is_usable_conclusion`).
        """
        run = await _run_writing_nothing(
            clone,
            says=(
                "Replaced the hand-rolled retry with tenacity and the unit "
                "suite is green; I left the integration suite alone because "
                "it needs the test stack."
            ),
        )

        on_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
        ((_, content),) = run.stored
        assert _BRANCH in content and on_remote in content, (
            f"the branch report must come from the workspace, not from what "
            f"the agent said, got {content!r}"
        )


class TestTheNextPhaseCanUseIt:
    """Stored is not delivered. #988 is the issue where those came apart."""

    async def test_the_downstream_phase_is_handed_the_salvage(self, clone: _Clone) -> None:
        run = await _run_writing_nothing(clone, says=SAID)

        assert len(run.agent.injected) == 2, "expected two phases to have run"
        downstream = run.agent.injected[1]
        assert downstream, (
            "the second phase started with an empty input tree - the salvage "
            "was stored and never delivered, so the work still has to be redone"
        )
        delivered = "\n".join(downstream.values())
        assert SAID in delivered, (
            f"the phase's conclusion did not reach the next phase, got {downstream!r}"
        )
        assert any(RECOVERED_SOURCE_PATH.rsplit("/", 1)[-1] in path for path in downstream), (
            f"the salvage must arrive under a name that says what it is, got {sorted(downstream)}"
        )


class TestTheSalvageIsNotAFreePass:
    """What must stay true, or this fix is worse than the bug it replaces."""

    async def test_a_phase_that_said_nothing_either_still_fails(self, clone: _Clone) -> None:
        """Both routes empty is a phase that really did produce nothing (#1167)."""
        run = await _run_writing_nothing(clone, says=SAID_NOTHING)

        assert run.result.status == "failed", (  # type: ignore[attr-defined]
            f"got {run.result.status!r}. A phase that wrote no file AND said "  # type: ignore[attr-defined]
            "nothing reached no conclusion anywhere; completing it is #1167, "
            "which this fix is not allowed to undo."
        )
        assert run.agent.call_count == 1, "the downstream phase must not run"
        assert run.stored == [], "nothing may be invented for a phase that said nothing"

    async def test_the_failure_still_names_the_branch(self, clone: _Clone) -> None:
        """#1200's report on the path that still fails."""
        run = await _run_writing_nothing(clone, says=SAID_NOTHING)

        message = run.result.error_message or ""  # type: ignore[attr-defined]
        on_remote = clone.origin_refs()[f"refs/heads/{_BRANCH}"]
        assert _BRANCH in message and on_remote in message, (
            f"a failing phase must still say where its branch stands: {message!r}"
        )

    async def test_the_salvage_never_passes_for_the_real_thing(self, clone: _Clone) -> None:
        """The contract was violated and the record must not read as if it wasn't.

        This is the assertion that makes "complete rather than fail" honest. A
        future change that dropped the marker or the banner would make a
        salvaged phase indistinguishable from one that wrote its deliverable,
        which is the outcome the decision explicitly rules out.
        """
        run = await _run_writing_nothing(clone, says=SAID)

        ((title, content),) = run.stored
        assert RECOVERED_TITLE_MARKER in title
        assert content.startswith(">"), (
            f"the content must lead with its provenance banner, got {content[:80]!r}"
        )
        assert "not the deliverable it owed" in content, (
            f"the banner must say the declared output was never written, got {content[:400]!r}"
        )

    async def test_a_phase_that_wrote_its_deliverable_is_untouched(self, clone: _Clone) -> None:
        """The regression guard. A salvage that fired on healthy runs would be
        a worse bug than the one being fixed: it would rewrite the deliverables
        of every run that was working."""
        agent = _RecordingAgent(says=SAID)
        agent._produces = (("artifacts/output/deliverable.md", b"# The real report"),)  # pyright: ignore[reportPrivateUsage]
        artifacts = _KeepingArtifacts()
        processor = _make_processor(agent)
        processor._artifact_repo = artifacts  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]

        result = await processor.run(
            workflow_id="wf-1300-healthy",
            workflow_name="Healthy Workflow",
            phases=_two_phase_workflow(first_declares=("markdown",)),
            inputs={},
            execution_id="exec-1300-healthy",
        )

        assert result.status == "completed"
        (title, content), *_ = [(a.title or "", a.content or "") for a in artifacts.saved]
        assert content == "# The real report", f"the written file must be stored as-is: {content!r}"
        assert SAID not in content, "a healthy run must never enter the fallback"
        assert RECOVERED_TITLE_MARKER not in title
