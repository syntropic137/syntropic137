"""#1321: a phase that fails must not take its finished work down with it.

THE INCIDENT, verbatim from the issue::

    exec-76a6d3b22b23 wrote artifacts/output/research.md - 1322 lines - then
    closed with TASK_RESULT: followed by PROSE instead of the JSON block. The
    verdict was UNREADABLE, the phase was refused, and the artifact was
    discarded with the workspace. artifact_ids: [], cost $9.80, delivered
    nothing.

REFUSING THE PHASE IS CORRECT AND IS NOT WHAT CHANGES. #1256 established that
an unreadable report may be a failure report, and every test here asserts the
run still ends ``failed``. What changes is that "this phase did not complete"
stopped implying "throw away what it produced": those are two decisions and
only the first one was ever made deliberately.

The asymmetry that made this a bug rather than a policy: #1300 already
SALVAGES a deliverable out of the TRANSCRIPT when a phase declares an output
and writes no file at all. So the system recovered work that existed only as
chat and destroyed work that existed as a file.

These drive the whole ``run()`` loop, because the claim is about what an
execution RECORDS - its status, its artifact_ids, and what the repository
holds afterwards - and not about what any one helper returns. The artifact
repository is real enough to assert on for the same reason: a run that
"collected" an artifact nothing stored is the bug wearing a different hat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts import ArtifactAggregate

pytestmark = pytest.mark.unit

#: What the phase in the issue actually wrote to close itself out: the marker,
#: and then prose where the JSON belongs. Read by the REAL verdict reader, so
#: what makes it unreadable here is what made it unreadable there.
PROSE_WHERE_THE_JSON_GOES = (
    "I have completed the research and written it to artifacts/output/research.md.\n"
    "TASK_RESULT: the research is complete and the recommendation is option B\n"
    "TASK_RESULT_END"
)

#: The deliverable itself - a real file in the workspace, written before the
#: phase botched its report, exactly as the 1322-line research.md was.
RESEARCH = ("artifacts/output/research.md", b"# Research\n\nThe recommendation is option B.\n")


class RecordingArtifactRepository:
    """An artifact repository that keeps what it is given, so a test can look."""

    def __init__(self) -> None:
        self.saved: list[ArtifactAggregate] = []

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def get_by_id(self, aggregate_id: str) -> None:
        return None


def _phase_that_declares_an_output() -> list[ExecutablePhase]:
    """One phase that DECLARES a deliverable, which is the whole precondition.

    #1300's salvage and this keep both hang off the phase having promised an
    output; a phase that declares none has nothing to lose and is covered by
    the smoke tests instead.
    """
    return [
        ExecutablePhase(
            phase_id="research",
            name="Research",
            order=1,
            description="Phase that writes its deliverable and then fails",
            agent_config=AgentConfiguration(),
            prompt_template="research it",
            output_artifact_types=("markdown",),
            timeout_seconds=30,
        )
    ]


def _kept(repo: RecordingArtifactRepository) -> list[ArtifactAggregate]:
    return repo.saved


class TestAnUnreadableReportStillRefusesThePhase:
    """The half of #1256 that must not move."""

    async def test_the_execution_still_fails(self) -> None:
        repo = RecordingArtifactRepository()
        processor = _make_processor(
            FakeAgentExecutionHandler.success(
                produces=[RESEARCH], says=PROSE_WHERE_THE_JSON_GOES
            ),
            artifact_repository=repo,
        )

        result = await processor.run(
            workflow_id="wf-1321",
            workflow_name="Keep what it wrote",
            phases=_phase_that_declares_an_output(),
            inputs={},
            execution_id="exec-1321-still-fails",
        )

        assert result.status == "failed", (
            f"Expected 'failed' but got '{result.status}'. Keeping the artifact "
            "must not rescue the phase - an unreadable report is still a "
            "refusal (#1256)."
        )

    async def test_the_phase_is_recorded_as_failed_not_completed(self) -> None:
        """The record, not just the return value: a phase whose artifact is
        kept must still read as FAILED to everything downstream."""
        processor = _make_processor(
            FakeAgentExecutionHandler.success(
                produces=[RESEARCH], says=PROSE_WHERE_THE_JSON_GOES
            ),
            artifact_repository=RecordingArtifactRepository(),
        )

        result = await processor.run(
            workflow_id="wf-1321",
            workflow_name="Keep what it wrote",
            phases=_phase_that_declares_an_output(),
            inputs={},
            execution_id="exec-1321-phase-failed",
        )

        assert [p.status.value for p in result.phase_results] == ["failed"]


class TestTheDeliverableSurvivesTheRefusal:
    """The half of #1321 that is new."""

    async def test_the_file_it_wrote_is_stored(self) -> None:
        """The workspace is abandoned moments later. If nothing stored this
        file before then, it is gone - which is what cost $9.80 and delivered
        nothing."""
        repo = RecordingArtifactRepository()
        processor = _make_processor(
            FakeAgentExecutionHandler.success(
                produces=[RESEARCH], says=PROSE_WHERE_THE_JSON_GOES
            ),
            artifact_repository=repo,
        )

        await processor.run(
            workflow_id="wf-1321",
            workflow_name="Keep what it wrote",
            phases=_phase_that_declares_an_output(),
            inputs={},
            execution_id="exec-1321-stored",
        )

        contents = [a.content for a in _kept(repo)]
        assert contents == [RESEARCH[1].decode()], (
            "The phase's deliverable was discarded with the workspace. "
            "Collection happens after the verdict in the to-do list, and the "
            "verdict never lets the run get that far."
        )

    async def test_the_failed_execution_reports_the_artifact_it_kept(self) -> None:
        """Stored and unreachable is not kept. ``artifact_ids: []`` is the
        line in the issue: an operator reading the execution has to be able to
        find the file from the failure."""
        repo = RecordingArtifactRepository()
        processor = _make_processor(
            FakeAgentExecutionHandler.success(
                produces=[RESEARCH], says=PROSE_WHERE_THE_JSON_GOES
            ),
            artifact_repository=repo,
        )

        result = await processor.run(
            workflow_id="wf-1321",
            workflow_name="Keep what it wrote",
            phases=_phase_that_declares_an_output(),
            inputs={},
            execution_id="exec-1321-reported",
        )

        assert result.artifact_ids == [a.id for a in _kept(repo)]
        assert result.phase_results[0].artifact_id == _kept(repo)[0].id, (
            "The failed phase's own record must name it too - artifact_id on a "
            "failed phase was unconditionally None before #1321."
        )

    async def test_the_kept_artifact_says_it_came_from_a_failed_phase(self) -> None:
        """A listing shows the title and nothing else. Work that is whole but
        belongs to a run that failed must not read as a clean deliverable, and
        must not read as an interrupted fragment either."""
        repo = RecordingArtifactRepository()
        processor = _make_processor(
            FakeAgentExecutionHandler.success(
                produces=[RESEARCH], says=PROSE_WHERE_THE_JSON_GOES
            ),
            artifact_repository=repo,
        )

        await processor.run(
            workflow_id="wf-1321",
            workflow_name="Keep what it wrote",
            phases=_phase_that_declares_an_output(),
            inputs={},
            execution_id="exec-1321-marked",
        )

        title = _kept(repo)[0].title or ""
        assert "(kept from a failed phase)" in title, (
            f"Title was {title!r}. An unmarked artifact from a refused phase "
            "reads as a delivered one."
        )
        assert "(partial)" not in title, "A refusal is not an interrupt."

    async def test_a_non_zero_exit_keeps_its_output_too(self) -> None:
        """The same door. A refused report and a dead process both unwind to
        ``_fail_execution`` through the same frames, and fixing one of them
        would leave the other losing files for exactly the same reason."""
        repo = RecordingArtifactRepository()
        processor = _make_processor(
            FakeAgentExecutionHandler.failed(exit_code=1, produces=[RESEARCH]),
            artifact_repository=repo,
        )

        result = await processor.run(
            workflow_id="wf-1321",
            workflow_name="Keep what it wrote",
            phases=_phase_that_declares_an_output(),
            inputs={},
            execution_id="exec-1321-exit-code",
        )

        assert result.status == "failed"
        assert [a.content for a in _kept(repo)] == [RESEARCH[1].decode()]
        assert result.artifact_ids == [a.id for a in _kept(repo)]


class TestNothingElseChanged:
    """Guards on the shapes that were already right."""

    async def test_a_failing_phase_that_wrote_nothing_keeps_nothing(self) -> None:
        """No file, no artifact, and no invented one. The keep reads the disk
        and never the transcript: substituting a deliverable here would make
        every failed phase look like it produced something."""
        repo = RecordingArtifactRepository()
        processor = _make_processor(
            FakeAgentExecutionHandler.success(says=PROSE_WHERE_THE_JSON_GOES),
            artifact_repository=repo,
        )

        result = await processor.run(
            workflow_id="wf-1321",
            workflow_name="Keep what it wrote",
            phases=_phase_that_declares_an_output(),
            inputs={},
            execution_id="exec-1321-empty",
        )

        assert result.status == "failed"
        assert _kept(repo) == []
        assert result.artifact_ids == []

    async def test_a_clean_run_still_completes_and_stores_once(self) -> None:
        """The happy path goes nowhere near the keep. If it did, a healthy
        phase would store its deliverable twice and label it a failure."""
        repo = RecordingArtifactRepository()
        processor = _make_processor(
            FakeAgentExecutionHandler.success(
                produces=[RESEARCH],
                says='TASK_RESULT: {"success": true, "comments": "done"}\nTASK_RESULT_END',
            ),
            artifact_repository=repo,
        )

        result = await processor.run(
            workflow_id="wf-1321",
            workflow_name="Keep what it wrote",
            phases=_phase_that_declares_an_output(),
            inputs={},
            execution_id="exec-1321-clean",
        )

        assert result.status == "completed"
        assert len(_kept(repo)) == 1
        assert "(kept from a failed phase)" not in (_kept(repo)[0].title or "")
