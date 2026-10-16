"""EvidenceStepHandler drives the real aggregate through the port doubles (plan §A.5, PR 5b).

Every assertion is on what the STREAM holds after the handler ran (reloaded
into a fresh aggregate) or on what reached the forge double, never on the
handler's own state: the handler is meant to have none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from syn_adapters.evidence.memory import (
    InMemoryEvidenceFiling,
    InMemoryEvidenceRunner,
    InMemoryRemoteBranchWriter,
    RunScript,
)
from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceReport,
    EvidenceVerdict,
    RequestedTestResult,
    StepOutcome,
    SuiteCounts,
    TestOutcome,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_evidence_gate_aggregate import (
    EXECUTION,
    S_PRIME,
    S,
    _collect,
    _declared,
    _gate_id,
    _started,
    _Store,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import (
    Accepted,
    Ambiguous,
    RefusalReason,
    Refused,
    RunConclusion,
    RunRef,
)
from syn_domain.contexts.orchestration.ports.RemoteBranchWriterPort import HeadMoved, Removed
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.EvidenceStepHandler import (
    REPORT_DISAGREES,
    EvidenceStepHandler,
    EvidenceTimings,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
        EvidenceGate,
    )

pytestmark = pytest.mark.unit

RUN = RunRef(run_id=7, run_url="https://github.com/o/r/actions/runs/7")
NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)


def _report(verdict: EvidenceVerdict = EvidenceVerdict.PASSED, head: str = S) -> EvidenceReport:
    return EvidenceReport(
        schema=1,
        kind=EvidenceKind.MUTATION,
        pr=42,
        head_sha=head,
        dispatch_id="d",
        verdict=verdict,
        requested=(
            RequestedTestResult(id="tests/test_x.py::test_kills", outcome=TestOutcome.PASSED),
        ),
        suite=SuiteCounts(collected=1, passed=1, failed=0, skipped=0),
        summary="all patches killed",
        report_md="# Mutation evidence\nkilled",
    )


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _Harness:
    def __init__(
        self, store: _Store, gate_id: str, runner: InMemoryEvidenceRunner, **kw: object
    ) -> None:
        self.store, self.gate_id, self.runner = store, gate_id, runner
        self.clock = _Clock()
        self.filing = kw.get("filing") or InMemoryEvidenceFiling()
        writer = kw.get("writer") or InMemoryRemoteBranchWriter(Removed(S_PRIME, "syn-app[bot]"))
        self.handler = EvidenceStepHandler(
            runner=runner,
            writer=writer,  # type: ignore[arg-type]
            filing=self.filing,  # type: ignore[arg-type]
            timings=EvidenceTimings(),
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        self.outputs = PhaseOutputCache()
        self.saves: list[list[str]] = []

    async def _save(self, aggregate: object) -> None:
        self.saves.append([type(e).__name__ for e in self.store.save(aggregate)])  # type: ignore[arg-type]

    async def step(self, index: int) -> None:
        todo = TodoItem(
            execution_id=EXECUTION,
            action=TodoAction.RUN_EVIDENCE_STEP,
            phase_id="implement",
            evidence_gate_id=self.gate_id,
            evidence_step=index,
        )
        await self.handler.handle(todo, self.store.load(), self._save, self.outputs)

    def gate(self) -> EvidenceGate:
        gate = self.store.load().evidence_gate(self.gate_id)
        assert gate is not None
        return gate


def _one_step(runner: InMemoryEvidenceRunner, **kw: object) -> _Harness:
    store = _started()
    gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
    return _Harness(store, gate_id, runner, **kw)


@pytest.mark.asyncio
async def test_a_passing_run_settles_files_its_reports_and_releases_the_phase() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=_report())])
    h = _one_step(runner)
    await h.step(0)

    gate = h.gate()
    assert gate.current is None
    settled = gate.settled[0]
    assert (settled.outcome, settled.run_url, settled.head_sha_evidenced) == (
        StepOutcome.PASSED,
        RUN.run_url,
        S,
    )
    assert h.saves[-1] == ["EvidenceStepSettledEvent", "NextPhaseReadyEvent"]
    names = sorted(f.name for _, f in h.filing.filed)
    assert names == ["0-mutation.json", "0-mutation.md", "manifest.json"]
    assert all(phase == "implement" for phase, _ in h.filing.filed)
    paths = {f.source_path for f in h.outputs.files["implement"]}
    assert f"artifacts/output/platform-evidence/{h.gate_id}/manifest.json" in paths


@pytest.mark.asyncio
async def test_the_attempt_is_saved_before_the_dispatch_is_posted() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=_report())])
    h = _one_step(runner)
    await h.step(0)
    assert h.saves[0] == ["EvidenceAttemptStartedEvent"]
    (posted,) = runner.dispatched
    assert posted.dispatch_id == h.gate().attempts[0].dispatch_id


@pytest.mark.asyncio
async def test_an_ambiguous_dispatch_is_found_by_its_id_and_never_reposted() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Ambiguous("504"), found=RUN, report=_report())])
    h = _one_step(runner)
    await h.step(0)
    assert len(runner.dispatched) == 1
    assert h.gate().attempts[0].run_id == RUN.run_id
    assert h.gate().settled[0].outcome is StepOutcome.PASSED


@pytest.mark.asyncio
async def test_a_dispatch_never_seen_twice_settles_dispatch_lost() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Ambiguous("504")), RunScript(Ambiguous("504"))])
    h = _one_step(runner)
    await h.step(0)
    assert len(runner.dispatched) == 2
    settled = h.gate().settled[0]
    assert (settled.outcome, settled.reason) == (StepOutcome.UNAVAILABLE, "dispatch_lost")


@pytest.mark.asyncio
async def test_a_refused_dispatch_settles_unavailable_with_the_reason() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Refused(RefusalReason.WORKFLOW_ABSENT))])
    h = _one_step(runner)
    await h.step(0)
    settled = h.gate().settled[0]
    assert (settled.outcome, settled.reason) == (StepOutcome.UNAVAILABLE, "workflow_absent")


@pytest.mark.asyncio
async def test_a_report_for_another_head_is_void() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=_report(head="f" * 40))])
    h = _one_step(runner)
    await h.step(0)
    settled = h.gate().settled[0]
    assert (settled.outcome, settled.reason) == (StepOutcome.VOID, "head moved")


@pytest.mark.asyncio
async def test_a_passed_report_from_a_failed_run_is_void() -> None:
    script = RunScript(Accepted(RUN), conclusion=RunConclusion.FAILURE, report=_report())
    h = _one_step(InMemoryEvidenceRunner([script]))
    await h.step(0)
    settled = h.gate().settled[0]
    assert (settled.outcome, settled.reason) == (StepOutcome.VOID, REPORT_DISAGREES)


@pytest.mark.asyncio
async def test_a_run_with_no_report_is_retried_once_then_unavailable() -> None:
    runner = InMemoryEvidenceRunner(
        [
            RunScript(Accepted(RUN), conclusion=RunConclusion.FAILURE),
            RunScript(Accepted(RunRef(run_id=8, run_url="u8")), conclusion=RunConclusion.FAILURE),
        ]
    )
    h = _one_step(runner)
    await h.step(0)
    assert len(runner.dispatched) == 2
    settled = h.gate().settled[0]
    assert (settled.outcome, settled.reason) == (StepOutcome.UNAVAILABLE, "runner")


@pytest.mark.asyncio
async def test_redelivering_a_settled_step_does_nothing() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=_report())])
    h = _one_step(runner)
    await h.step(0)
    saves = len(h.saves)
    await h.step(0)
    assert len(h.saves) == saves
    assert len(runner.dispatched) == 1


@pytest.mark.asyncio
async def test_an_unavailable_store_leaves_no_manifest_id() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=_report())])
    h = _one_step(runner, filing=InMemoryEvidenceFiling(available=False))
    await h.step(0)
    (settled,) = [e for e in h.store.events if type(e.event).__name__ == "EvidenceStepSettledEvent"]
    assert settled.event.manifest_artifact_id is None  # pyright: ignore[reportAttributeAccessIssue]
    assert h.gate().current is None


def _cleanup_gate(
    writer: InMemoryRemoteBranchWriter, check: RunConclusion = RunConclusion.SUCCESS
) -> _Harness:
    store = _started()
    _collect(store, "implement", policy=None)
    events = _collect(store, "review", declared=(_declared(),), verdict=ReviewVerdict.CERTIFIED)
    runner = InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=_report())], check=check)
    return _Harness(store, _gate_id(events), runner, writer=writer)


@pytest.mark.asyncio
async def test_removal_then_the_required_check_runs_on_s_prime() -> None:
    writer = InMemoryRemoteBranchWriter(Removed(S_PRIME, "syn-app[bot]"))
    h = _cleanup_gate(writer)
    for index in range(3):
        await h.step(index)
    assert writer.calls == [("syntropic137/syntropic137", "feat/x", S, (".mutations",))]
    assert h.runner.checked == [("syntropic137/syntropic137", S_PRIME, "CI Success")]
    gate = h.gate()
    assert gate.current is None
    assert gate.manifest().patch_removal is not None


@pytest.mark.asyncio
async def test_a_moved_head_settles_the_removal_void_and_skips_the_check() -> None:
    writer = InMemoryRemoteBranchWriter(HeadMoved(head_sha="e" * 40))
    h = _cleanup_gate(writer)
    for index in range(3):
        await h.step(index)
    gate = h.gate()
    assert gate.settled[1].reason == "head moved"
    assert gate.settled[2].outcome is StepOutcome.VOID
    assert h.runner.checked == []
