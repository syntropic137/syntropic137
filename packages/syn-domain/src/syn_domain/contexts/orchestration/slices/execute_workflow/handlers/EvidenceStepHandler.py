"""Drives one step of an evidence gate (plan §A.5, B3; PR 5b).

Reads ONLY the rehydrated aggregate, never state it held earlier: every action
is a command, saved before the next side effect, so a crash anywhere leaves a
stream the next process continues from. Idempotent: a to-do item for a step
that has already settled is a no-op, and an attempt already recorded is found
by its `dispatch_id` rather than dispatched again. Decides nothing the
aggregate decides: a step the aggregate has predetermined is settled exactly
as decided.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.artifacts import PhaseOutputFile
from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceStepKind,
    EvidenceVerdict,
    StepOutcome,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordEvidenceRunAdoptedCommand,
    RecordMutationPatchesRemovedCommand,
    SettleEvidenceStepCommand,
    StartEvidenceAttemptCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
    HEAD_MOVED,
    MAX_ATTEMPTS,
    build_manifest,
    report_mismatch,
)
from syn_domain.contexts.orchestration.ports.EvidenceFilingPort import EvidenceFile
from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import (
    Accepted,
    EvidenceAttemptRef,
    Refused,
    RunConclusion,
    RunRef,
)
from syn_domain.contexts.orchestration.ports.RemoteBranchWriterPort import HeadMoved

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
        EvidenceAttempt,
        EvidenceGate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        EvidencePlanStep,
        InheritedAttempt,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.ports.EvidenceFilingPort import EvidenceFilingPort
    from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import EvidenceRunnerPort
    from syn_domain.contexts.orchestration.ports.RemoteBranchWriterPort import (
        RemoteBranchWriterPort,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        PhaseOutputCache,
    )

REPORT_DISAGREES: Final = "report disagrees with run"

_CHECK_OUTCOME: Final = {
    RunConclusion.SUCCESS: (StepOutcome.PASSED, None),
    RunConclusion.FAILURE: (StepOutcome.FAILED, None),
    RunConclusion.CANCELLED: (StepOutcome.UNAVAILABLE, "superseded"),
    RunConclusion.TIMED_OUT: (StepOutcome.UNAVAILABLE, "timeout"),
}

Save = Callable[["WorkflowExecutionAggregate"], Awaitable[None]]
_VERDICT_OUTCOME = {
    EvidenceVerdict.PASSED: StepOutcome.PASSED,
    EvidenceVerdict.FAILED: StepOutcome.FAILED,
    EvidenceVerdict.VOID: StepOutcome.VOID,
}


@dataclass(frozen=True)
class EvidenceTimings:
    step_deadline: timedelta = timedelta(hours=1)
    dispatch_visibility: timedelta = timedelta(seconds=120)
    poll_interval: timedelta = timedelta(seconds=10)
    #: `SYN_EVIDENCE_REQUIRED_CHECK`.
    required_check: str = "CI Success"


@dataclass
class EvidenceStepHandler:
    """Stateless across executions: the processor shares one; each call gets a `_StepRun`."""

    runner: EvidenceRunnerPort
    writer: RemoteBranchWriterPort
    filing: EvidenceFilingPort
    timings: EvidenceTimings = field(default_factory=EvidenceTimings)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def handle(
        self,
        todo: TodoItem,
        aggregate: WorkflowExecutionAggregate,
        save: Save,
        outputs: PhaseOutputCache,
    ) -> None:
        gate = aggregate.evidence_gate(todo.evidence_gate_id or "")
        step = gate.current if gate is not None else None
        if gate is None or step is None or step.index != todo.evidence_step:
            return  # already settled: idempotent re-delivery
        await _StepRun(self, todo.execution_id, aggregate, gate, step, save, outputs).go()


@dataclass
class _StepRun:
    """One call's worth of context. The gate is the aggregate's own, so it is always current."""

    h: EvidenceStepHandler
    execution_id: str
    aggregate: WorkflowExecutionAggregate
    gate: EvidenceGate
    step: EvidencePlanStep
    save: Save
    outputs: PhaseOutputCache

    async def go(self) -> None:
        decided = self.gate.predetermined(self.step)
        if decided is not None:
            await self._settle(decided.outcome, decided.reason)
        elif self.step.kind is EvidenceStepKind.REMOVE_MUTATION_PATCHES:
            await self._remove()
        elif self.step.kind is EvidenceStepKind.REQUIRED_CHECK:
            await self._required_check()
        else:
            await self._run()

    async def _remove(self) -> None:
        step = self.step
        assert step.repository and step.branch and step.head_sha  # planned with a head
        result = await self.h.writer.remove_paths(
            step.repository, step.branch, step.head_sha, (".mutations",)
        )
        if isinstance(result, HeadMoved):
            await self._settle(StepOutcome.VOID, HEAD_MOVED)
            return
        self.aggregate.record_mutation_patches_removed(
            RecordMutationPatchesRemovedCommand(
                self.execution_id, self.gate.gate_id, step.index, result.after_sha, result.author
            )
        )
        await self.save(self.aggregate)

    async def _required_check(self) -> None:
        """Wait for the required check on S' (§A.3 5). Read-only, so no attempt is recorded."""
        head = self.gate.head_for(self.step)
        assert self.step.repository and head  # predetermined void unless S' exists
        not_after = self.h.clock() + self.h.timings.step_deadline
        conclusion = await self.h.runner.await_check(
            self.step.repository, head, self.h.timings.required_check, not_after
        )
        outcome, reason = _CHECK_OUTCOME[conclusion]
        await self._settle(outcome, reason, head_sha=head)

    async def _run(self) -> None:
        index = self.step.index
        attempt = self.gate.attempts.get(index) or await self._first_attempt()
        while attempt is not None:
            if self.h.clock() >= attempt.not_after:
                await self._settle(StepOutcome.UNAVAILABLE, "timeout")
                return
            if attempt.run_id is None or attempt.run_url is None:
                run = await self._find(attempt)
                if run is None:
                    attempt = await self._retry("dispatch_lost")
                    continue
                attempt = await self._adopt(attempt, run)
            run = RunRef(run_id=attempt.run_id or 0, run_url=attempt.run_url or "")
            why = await self._conclude(run, attempt)
            if why is None:
                return
            attempt = await self._retry(why)

    async def _attempt(self) -> EvidenceAttempt | None:
        """Record an attempt, THEN post it. None when the forge refused and the step settled."""
        attempt = await self._start()
        if self.h.clock() >= attempt.not_after:
            # The save can outlast the deadline (§A.5 4): nothing is posted after it.
            await self._settle(StepOutcome.UNAVAILABLE, "timeout")
            return None
        result = await self.h.runner.dispatch(self._ref(attempt))
        if isinstance(result, Refused):
            await self._settle(StepOutcome.UNAVAILABLE, result.reason.value)
            return None
        if isinstance(result, Accepted) and result.run is not None:
            return await self._adopt(attempt, result.run)
        # Ambiguous, or accepted with no run named: look for it, never re-POST.
        return attempt

    async def _conclude(self, run: RunRef, attempt: EvidenceAttempt) -> str | None:
        """Settle from the adopted run; or why it needs another attempt."""
        conclusion = await self.h.runner.await_run(run, attempt.not_after)
        if conclusion is RunConclusion.TIMED_OUT:
            await self._settle(StepOutcome.UNAVAILABLE, "timeout", run)
            return None
        report = await self.h.runner.fetch_report(run)
        if report is None:
            return "superseded" if conclusion is RunConclusion.CANCELLED else "runner"
        outcome, reason = _VERDICT_OUTCOME[report.verdict], None
        mismatch = report_mismatch(
            self.step, self.gate.head_for(self.step), attempt.dispatch_id, report
        )
        if mismatch is not None:
            outcome, reason = StepOutcome.VOID, mismatch
        elif outcome is StepOutcome.PASSED and conclusion is RunConclusion.FAILURE:
            outcome, reason = StepOutcome.VOID, REPORT_DISAGREES
        elif outcome is StepOutcome.VOID:
            reason = report.summary or "evidence run voided"
        stem = f"{self.step.index}-{self.step.kind.value}"
        files = [
            (f"{stem}.json", report.model_dump_json(by_alias=True)),
            (f"{stem}.md", report.report_md),
        ]
        await self._settle(outcome, reason, run, report.head_sha, files)
        return None

    async def _retry(self, why: str) -> EvidenceAttempt | None:
        """Attempt n+1 if one is left; otherwise settle `unavailable: why` and return None."""
        attempt = self.gate.attempts.get(self.step.index)
        if attempt is not None and self.h.clock() >= attempt.not_after:
            # Retries share the step's deadline (§A.5 4): nothing is posted after it.
            await self._settle(StepOutcome.UNAVAILABLE, "timeout")
            return None
        if attempt is not None and attempt.attempt >= MAX_ATTEMPTS:
            await self._settle(StepOutcome.UNAVAILABLE, why)
            return None
        return await self._attempt()

    async def _first_attempt(self) -> EvidenceAttempt | None:
        """The parent's attempt when this is a resume that inherited one, else a new one."""
        parent = self.gate.inherited_attempts.get(self.step.index)
        return await (self._attempt() if parent is None else self._resume_parent_attempt(parent))

    async def _resume_parent_attempt(self, parent: InheritedAttempt) -> EvidenceAttempt:
        """Take over the parent's attempt before posting anything (§A.7 3).

        Recorded under the parent's nonce and post time, so the look-up finds
        the parent's run, but with a fresh deadline: a person-started resume is
        a new decision. Nothing is posted here; a run the look-up cannot find
        costs this step one attempt, then a fresh one is posted.
        """
        attempt = await self._start(parent.dispatch_id, parent.started_at)
        if parent.run_id is not None and parent.run_url is not None:
            return await self._adopt(attempt, RunRef(run_id=parent.run_id, run_url=parent.run_url))
        return attempt

    async def _start(
        self, dispatch_id: str | None = None, started_at: datetime | None = None
    ) -> EvidenceAttempt:
        now = self.h.clock()
        self.aggregate.start_evidence_attempt(
            StartEvidenceAttemptCommand(
                self.execution_id,
                self.gate.gate_id,
                self.step.index,
                dispatch_id or str(uuid.uuid4()),
                started_at or now,
                now + self.h.timings.step_deadline,
            )
        )
        await self.save(self.aggregate)  # recorded BEFORE the POST (B3)
        return self.gate.attempts[self.step.index]

    async def _adopt(self, attempt: EvidenceAttempt, run: RunRef) -> EvidenceAttempt:
        self.aggregate.record_evidence_run_adopted(
            RecordEvidenceRunAdoptedCommand(
                self.execution_id,
                self.gate.gate_id,
                self.step.index,
                attempt.attempt,
                run.run_id,
                run.run_url,
            )
        )
        await self.save(self.aggregate)
        return self.gate.attempts[self.step.index]

    async def _find(self, attempt: EvidenceAttempt) -> RunRef | None:
        """Look for the attempt's run until it should have become visible (§A.5 2).

        Never past the step's own deadline, which may be the sooner of the two.
        """
        deadline = min(attempt.started_at + self.h.timings.dispatch_visibility, attempt.not_after)
        while True:
            run = await self.h.runner.find_run(self._ref(attempt))
            if run is not None or self.h.clock() >= deadline:
                return run
            await self.h.sleep(self.h.timings.poll_interval.total_seconds())

    def _ref(self, attempt: EvidenceAttempt) -> EvidenceAttemptRef:
        return EvidenceAttemptRef(
            repository=self.step.repository or "",
            kind=self.step.kind,
            pr=self.step.pr,
            head_sha=self.gate.head_for(self.step),
            tests=self.step.tests,
            dispatch_id=attempt.dispatch_id,
            started_at=attempt.started_at,
        )

    async def _settle(
        self,
        outcome: StepOutcome,
        reason: str | None,
        run: RunRef | None = None,
        head_sha: str | None = None,
        files: list[tuple[str, str]] | None = None,
    ) -> None:
        step, gate = self.step, self.gate
        files = list(files or [])

        def command(report_ids: list[str], manifest_id: str | None) -> SettleEvidenceStepCommand:
            return SettleEvidenceStepCommand(
                self.execution_id,
                gate.gate_id,
                step.index,
                outcome,
                reason=reason,
                run_id=run.run_id if run else None,
                run_url=run.run_url if run else None,
                head_sha_evidenced=head_sha,
                report_artifact_ids=report_ids,
                manifest_artifact_id=manifest_id,
            )

        if step.index == len(gate.plan) - 1:
            # The settlement the aggregate WILL record, by its own rule, added to
            # the events BEFORE it is recorded (§A.6): one rule, not a second copy.
            this = self.aggregate.preview_evidence_settlement(command([], None))
            settled = [*gate.settled.values(), this]
            manifest = build_manifest(gate.gate_id, gate.plan, settled, gate.removed)
            files.append(("manifest.json", manifest.model_dump_json(by_alias=True, indent=2)))
        filed = await self.h.filing.file(
            self.execution_id,
            gate.after_phase_id,
            [EvidenceFile(gate_id=gate.gate_id, name=n, content=c) for n, c in files],
        )
        by_name = {f.name: f.artifact_id for f in filed}
        # Live path: the next workspace is built from the cache, which wins over the projection.
        self.outputs.append(
            gate.after_phase_id,
            [PhaseOutputFile(source_path=f.source_path, content=f.content) for f in filed],
        )
        self.aggregate.settle_evidence_step(
            command(
                [i for n, i in by_name.items() if n != "manifest.json"],
                # Absent when it could not be stored: prompts read that as "not proven".
                by_name.get("manifest.json"),
            )
        )
        await self.save(self.aggregate)
