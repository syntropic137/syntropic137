"""EvidenceStepHandler drives the real aggregate through the port doubles (plan §A.5, PR 5b).

Every assertion is on what the STREAM holds after the handler ran (reloaded
into a fresh aggregate) or on what reached the forge double, never on the
handler's own state: the handler is meant to have none.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
    EvidenceManifest,
    EvidenceReport,
    EvidenceVerdict,
    RequestedTestResult,
    StepOutcome,
    StepRef,
    SuiteCounts,
    TestOutcome,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordEvidenceRunAdoptedCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
    FOREIGN_REPOSITORY,
    REPORT_NOT_REQUESTED,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_evidence_gate_aggregate import (
    EXECUTION,
    HEAD,
    NOW,
    REPO,
    S_PRIME,
    S,
    _attempt,
    _collect,
    _declared,
    _gate_id,
    _send,
    _started,
    _Store,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    DeclaredEvidence,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import (
    Accepted,
    Ambiguous,
    DispatchResult,
    EvidenceAttemptRef,
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


# --- Verify round 1 (PR #2001): scope, report binding, manifest, deadline, durability ---

FOREIGN = "other-owner/other-repository"


def _foreign_declared() -> DeclaredEvidence:
    request = _declared().request
    assert request is not None
    return DeclaredEvidence(request=request.model_copy(update={"repository": FOREIGN}))


@pytest.mark.asyncio
async def test_a_refused_foreign_declaration_never_authorizes_a_later_dispatch() -> None:
    """Phase 1 declares a foreign mutation (refused); phase 2 leaves that foreign head patched."""
    # The observer reports every declared branch, foreign ones included.
    foreign_head = HEAD.model_copy(update={"repository": FOREIGN})
    store = _started()
    first = _gate_id(
        _collect(store, "implement", declared=(_foreign_declared(),), head=foreign_head)
    )
    h = _Harness(store, first, InMemoryEvidenceRunner([]))
    await h.step(0)
    gate = h.gate()
    assert [s.index for s in gate.plan] == [0]
    assert gate.settled[0].reason == FOREIGN_REPOSITORY

    events = _collect(store, "review", head=foreign_head)
    assert "EvidenceRequestedEvent" not in [type(e).__name__ for e in events]
    assert "NextPhaseReadyEvent" in [type(e).__name__ for e in events]
    assert h.runner.dispatched == []
    for gate_events in [
        e for e in store.events if type(e.event).__name__ == "EvidenceRequestedEvent"
    ]:
        steps = gate_events.event.steps  # pyright: ignore[reportAttributeAccessIssue]
        assert all(s.preset is not None or s.repository == REPO for s in steps)


def _wrong(**update: object) -> EvidenceReport:
    return _report().model_copy(update=update)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [
        RunScript(Accepted(RUN), report=_wrong(kind=EvidenceKind.INTEGRATION)),
        RunScript(Accepted(RUN), report=_wrong(pr=43)),
        RunScript(
            Accepted(RUN),
            report=_wrong(
                requested=(
                    RequestedTestResult(
                        id="tests/test_y.py::test_other", outcome=TestOutcome.PASSED
                    ),
                )
            ),
        ),
        RunScript(Accepted(RUN), report=_report(), report_dispatch_id="another-attempt"),
    ],
    ids=["kind", "pr", "tests", "nonce"],
)
async def test_a_report_for_another_request_cannot_prove_this_step(script: RunScript) -> None:
    h = _one_step(InMemoryEvidenceRunner([script]))
    await h.step(0)
    settled = h.gate().settled[0]
    assert (settled.outcome, settled.reason) == (StepOutcome.VOID, REPORT_NOT_REQUESTED)
    assert h.store.load()._gates.passed() == ()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_a_matching_report_carrying_the_attempt_nonce_passes() -> None:
    runner = InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=_report())])
    h = _one_step(runner)
    await h.step(0)
    assert h.gate().settled[0].outcome is StepOutcome.PASSED
    (proven,) = h.store.load()._gates.passed()  # pyright: ignore[reportPrivateUsage]
    assert proven.tests == frozenset({"tests/test_x.py::test_kills"})


@pytest.mark.asyncio
async def test_the_filed_manifest_is_the_gate_manifest_including_reuse() -> None:
    store = _started()
    first = _gate_id(_collect(store, "implement", declared=(_declared(),)))
    runner = InMemoryEvidenceRunner([RunScript(Accepted(RUN), report=_report())])
    h = _Harness(store, first, runner)
    await h.step(0)

    second = _gate_id(_collect(store, "review", declared=(_declared(),)))
    h.gate_id = second
    await h.step(0)
    assert len(runner.dispatched) == 1  # the second gate reused, it did not run

    gate = h.gate()
    assert gate.settled[0].reused_from == StepRef(gate_id=first, step=0)
    (filed,) = [f for _, f in h.filing.filed if f.source_path.endswith(f"{second}/manifest.json")]
    assert EvidenceManifest.model_validate_json(filed.content) == gate.manifest()


def _deadline_harness(step_deadline: timedelta, scripts: list[RunScript]) -> _Harness:
    h = _one_step(InMemoryEvidenceRunner(scripts))
    h.handler.timings = EvidenceTimings(step_deadline=step_deadline)
    return h


@pytest.mark.asyncio
async def test_a_short_deadline_bounds_the_lookup_and_posts_no_retry() -> None:
    h = _deadline_harness(timedelta(seconds=5), [RunScript(Ambiguous("504"))])
    await h.step(0)
    gate = h.gate()
    assert len(h.runner.dispatched) == 1
    assert (gate.settled[0].outcome, gate.settled[0].reason) == (StepOutcome.UNAVAILABLE, "timeout")
    # The lookup stopped at the persisted deadline, not the 120s visibility window.
    assert h.clock.now <= gate.attempts[0].not_after + EvidenceTimings().poll_interval


@pytest.mark.asyncio
async def test_reentry_near_a_persisted_deadline_dispatches_nothing() -> None:
    store = _started()
    gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
    _send(store, _attempt(gate_id, 0, "d-1", not_after=NOW + timedelta(seconds=5)))
    h = _Harness(store, gate_id, InMemoryEvidenceRunner([RunScript(Ambiguous("504"))]))
    h.clock.now = NOW + timedelta(seconds=4)
    await h.step(0)
    gate = h.gate()
    assert h.runner.dispatched == []
    assert gate.attempts[0].not_after == NOW + timedelta(seconds=5)
    assert (gate.settled[0].outcome, gate.settled[0].reason) == (StepOutcome.UNAVAILABLE, "timeout")


class _DurabilityCheckingRunner(InMemoryEvidenceRunner):
    """At the moment of the POST, reloads the STREAM and records what it already holds."""

    def __init__(self, store: _Store, scripts: list[RunScript]) -> None:
        super().__init__(scripts)
        self.store, self.gate_id = store, ""
        self.persisted_at_post: list[tuple[str, int, datetime] | None] = []

    async def dispatch(self, attempt: EvidenceAttemptRef) -> DispatchResult:
        gate = self.store.load().evidence_gate(self.gate_id)
        held = gate.attempts.get(0) if gate is not None else None
        self.persisted_at_post.append(
            None if held is None else (held.dispatch_id, held.attempt, held.not_after)
        )
        return await super().dispatch(attempt)


@pytest.mark.asyncio
async def test_the_attempt_is_durable_at_the_moment_its_dispatch_is_posted() -> None:
    store = _started()
    gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
    runner = _DurabilityCheckingRunner(store, [RunScript(Accepted(RUN), report=_report())])
    runner.gate_id = gate_id
    h = _Harness(store, gate_id, runner)
    await h.step(0)
    (posted,) = runner.dispatched
    assert runner.persisted_at_post == [(posted.dispatch_id, 1, NOW + timedelta(hours=1))]


class _ForgeAfterCrash(InMemoryEvidenceRunner):
    """A fresh process's view of a forge that already holds the run for ``dispatch_id``."""

    def __init__(self, dispatch_id: str) -> None:
        super().__init__([])
        self._known = dispatch_id

    async def find_run(self, attempt: EvidenceAttemptRef) -> RunRef | None:
        return RUN if attempt.dispatch_id == self._known else None

    async def await_run(self, run: RunRef, not_after: datetime) -> RunConclusion:
        del run, not_after
        return RunConclusion.SUCCESS

    async def fetch_report(self, run: RunRef) -> EvidenceReport | None:
        del run
        return _report().model_copy(update={"dispatch_id": self._known})


@pytest.mark.asyncio
@pytest.mark.parametrize("adopted", [False, True], ids=["started-unadopted", "adopted"])
async def test_a_fresh_process_resumes_a_persisted_attempt_without_dispatching(
    adopted: bool,
) -> None:
    store = _started()
    gate_id = _gate_id(_collect(store, "implement", declared=(_declared(),)))
    _send(store, _attempt(gate_id, 0, "d-1", not_after=NOW + timedelta(hours=1)))
    if adopted:
        _send(
            store,
            RecordEvidenceRunAdoptedCommand(EXECUTION, gate_id, 0, 1, RUN.run_id, RUN.run_url),
        )
    runner = _ForgeAfterCrash("d-1")
    h = _Harness(store, gate_id, runner)
    await h.step(0)
    gate = h.gate()
    assert runner.dispatched == []
    assert (gate.attempts[0].attempt, gate.attempts[0].run_id) == (1, RUN.run_id)
    assert gate.settled[0].outcome is StepOutcome.PASSED


def _slow_attempt_save(h: _Harness, on_attempt: int, by: timedelta) -> None:
    """The save recording attempt `on_attempt` takes `by` of wall-clock time."""
    save, seen = h._save, [0]

    async def slow(aggregate: object) -> None:
        await save(aggregate)
        if h.saves[-1].count("EvidenceAttemptStartedEvent"):
            seen[0] += 1
            if seen[0] == on_attempt:
                h.clock.now += by

    h._save = slow  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_a_save_that_outlasts_the_deadline_posts_nothing() -> None:
    h = _deadline_harness(timedelta(seconds=5), [RunScript(Accepted(RUN), report=_report())])
    _slow_attempt_save(h, on_attempt=1, by=timedelta(seconds=6))
    await h.step(0)
    gate = h.gate()
    assert h.runner.dispatched == []
    assert 0 in gate.attempts  # still saved before any POST could happen
    assert (gate.settled[0].outcome, gate.settled[0].reason) == (StepOutcome.UNAVAILABLE, "timeout")


@pytest.mark.asyncio
async def test_a_retry_save_that_outlasts_the_deadline_posts_nothing() -> None:
    h = _deadline_harness(
        timedelta(seconds=200), [RunScript(Ambiguous("504")), RunScript(Accepted(RUN))]
    )
    _slow_attempt_save(h, on_attempt=2, by=timedelta(seconds=400))
    await h.step(0)
    gate = h.gate()
    assert len(h.runner.dispatched) == 1  # the first attempt only
    assert gate.attempts[0].attempt == 2  # the retry was recorded, then not posted
    assert (gate.settled[0].outcome, gate.settled[0].reason) == (StepOutcome.UNAVAILABLE, "timeout")
