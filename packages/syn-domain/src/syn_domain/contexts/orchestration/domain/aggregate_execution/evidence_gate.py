"""When an evidence gate opens, what it plans, and what its manifest says (PR 5b).

docs/plans/20261015_platform-dispatched-evidence.md §A.3 and §A.6. The same
split as `review_rounds`: pure functions of replayed state, so every rule is
testable without building an aggregate, and the aggregate is the only caller.

A gate sits on the transition from a collected phase P to the phase
`next_phase` already chose. It is planned ONCE, when it opens, from what P
declared (`DeclaredEvidence`) and what the forge showed at collection
(`ObservedHead`), both recorded by PR 5a. A declaration the platform cannot
act on is not dropped: it becomes a step that settles at plan time with its
reason, so it reaches the manifest and can never read as "no proof needed".

Two steps cannot be fully decided at plan time, because they depend on how
earlier steps settled: `remove_mutation_patches` (only once every mutation
step for its head passed) and anything planned on the cleaned head S'.
`removal_blocked` and `target_head` answer those when the step is reached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    MAX_TESTS,
    EvidenceKind,
    EvidenceManifest,
    EvidenceStepKind,
    ManifestStep,
    PatchRemoval,
    StepOutcome,
    StepRef,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syn_domain.contexts.orchestration._shared.evidence_contract import (
        EvidenceReport,
        EvidenceRequest,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        DeclaredEvidence,
        ObservedHead,
    )

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    EvidencePlanStep,
    EvidencePreset,
)

UNREADABLE: Final = "unreadable evidence request"
FOREIGN_REPOSITORY: Final = "repository not in this execution"
FORGE_UNREADABLE: Final = "forge_unreadable"
HEAD_MOVED: Final = "head moved"
PR_MISMATCH: Final = "pr mismatch"
NO_TESTS_DECLARED: Final = "patches present, no tests declared"
TOO_MANY_TESTS: Final = f"more than {MAX_TESTS} tests requested for one head"
MUTATION_NOT_PASSED: Final = "mutation evidence for this head did not pass"
PATCHES_NOT_REMOVED: Final = "mutation patches were not removed"
REPORT_NOT_REQUESTED: Final = "report does not answer this request"

_KIND_TO_STEP: Final = {
    EvidenceKind.MUTATION: EvidenceStepKind.MUTATION,
    EvidenceKind.INTEGRATION: EvidenceStepKind.INTEGRATION,
}
_STEP_TO_KIND: Final = {step: kind for kind, step in _KIND_TO_STEP.items()}


@dataclass(frozen=True)
class PassedEvidence:
    """A step that already settled `passed` in this execution, inherited ones included."""

    ref: StepRef
    kind: EvidenceStepKind
    repository: str
    head_sha: str
    tests: frozenset[str]


@dataclass(frozen=True)
class GateInputs:
    """Everything a gate's opening and plan depend on, read from replayed state."""

    declared: tuple[DeclaredEvidence, ...]
    observed: tuple[ObservedHead, ...]
    #: The execution's repositories, `owner/name`.
    repositories: frozenset[str]
    #: The held next phase is the workflow's final phase.
    next_is_final: bool
    #: P's verdict is CERTIFIED.
    certified: bool
    passed: tuple[PassedEvidence, ...] = ()
    #: Per repository, the latest mutation test selection declared earlier in
    #: this execution, for patches P left without declaring tests (I4).
    earlier_mutation_tests: dict[str, tuple[str, ...]] = field(default_factory=dict)


def gate_opens(*, enabled: bool, has_next_phase: bool, inputs: GateInputs) -> bool:
    """Whether P's transition is held for evidence (§A.3). Off unless ``enabled``.

    ``has_next_phase`` is False after the final phase: a gate never sits there.
    """
    if not enabled or not has_next_phase:
        return False
    if inputs.declared:
        return True
    patched = _patched_heads(inputs)
    if any(not _mutation_passed_for(inputs.passed, h.repository, sha) for h, sha in patched):
        return True
    return inputs.next_is_final and inputs.certified and bool(patched)


def plan_steps(inputs: GateInputs) -> tuple[EvidencePlanStep, ...]:
    """The ordered plan: mutation, removal, integration, required check (§A.3)."""
    declared = _DeclaredPlan.of(inputs)
    steps: list[EvidencePlanStep] = [group.step() for group in declared.mutation.values()]
    steps += [
        _undeclared_mutation(head, sha, inputs)
        for head, sha in _patched_heads(inputs)
        if (head.repository, sha) not in declared.mutation
        and not _mutation_passed_for(inputs.passed, head.repository, sha)
    ]
    steps += declared.unplannable
    steps += _around_cleanup(_cleanup_head(inputs), declared.integration)
    return tuple(
        _reuse(s.model_copy(update={"index": i}), inputs.passed) for i, s in enumerate(steps)
    )


@dataclass
class _DeclaredPlan:
    """What P's declarations plan, before undeclared patches and cleanup are added."""

    mutation: dict[tuple[str, str], _MutationGroup] = field(default_factory=dict)
    integration: list[EvidencePlanStep] = field(default_factory=list)
    unplannable: list[EvidencePlanStep] = field(default_factory=list)

    @classmethod
    def of(cls, inputs: GateInputs) -> _DeclaredPlan:
        plan = cls()
        for declared in inputs.declared:
            refused = _refusal(declared, inputs)
            if refused is not None:
                plan.unplannable.append(refused)
                continue
            request = declared.request
            assert request is not None  # `_refusal` returned None, so it is a request
            if request.kind is EvidenceKind.MUTATION:
                key = (request.repository, request.head_sha)
                plan.mutation.setdefault(key, _MutationGroup(request)).tests.update(request.tests)
            else:
                plan.integration.append(
                    _step_for(request, EvidenceStepKind.INTEGRATION, request.tests)
                )
        return plan


def _around_cleanup(
    cleanup: tuple[ObservedHead, str] | None, integration: Sequence[EvidencePlanStep]
) -> list[EvidencePlanStep]:
    """Removal, integration (moved onto S' when it targets S), then the required check."""
    if cleanup is None:
        return list(integration)
    head, sha = cleanup
    removal = EvidencePlanStep(
        index=0,
        kind=EvidenceStepKind.REMOVE_MUTATION_PATCHES,
        repository=head.repository,
        branch=head.branch,
        pr=head.open_pr_number,
        head_sha=sha,
    )
    steps = [removal]
    steps += [
        step.model_copy(update={"head_sha": None, "on_cleaned_head": True})
        if (step.repository, step.head_sha) == (head.repository, sha)
        else step
        for step in integration
    ]
    steps.append(
        removal.model_copy(
            update={
                "kind": EvidenceStepKind.REQUIRED_CHECK,
                "head_sha": None,
                "on_cleaned_head": True,
            }
        )
    )
    return steps


# --- Decisions taken when a step is reached -------------------------------------


@dataclass(frozen=True)
class SettledStep:
    """How one planned step settled, as `EvidenceStepSettled` records it."""

    index: int
    outcome: StepOutcome
    reason: str | None = None
    run_url: str | None = None
    head_sha_evidenced: str | None = None
    reused_from: StepRef | None = None


def removal_blocked(
    plan: Sequence[EvidencePlanStep], settled: Iterable[SettledStep], removal: EvidencePlanStep
) -> str | None:
    """Why the removal step must not write, or None: every mutation step for its head passed."""
    outcomes = {s.index: s.outcome for s in settled}
    for step in plan:
        if (
            step.kind is EvidenceStepKind.MUTATION
            and (step.repository, step.head_sha) == (removal.repository, removal.head_sha)
            and outcomes.get(step.index) is not StepOutcome.PASSED
        ):
            return MUTATION_NOT_PASSED
    return None


def report_mismatch(
    step: EvidencePlanStep, head: str | None, dispatch_id: str, report: EvidenceReport
) -> str | None:
    """Why ``report`` cannot settle ``step``'s attempt ``dispatch_id``, or None (§A.5).

    A report proves only what was asked: this step's kind, PR and exact test
    selection on its head, produced by this attempt. Anything else voids the
    step, because a pass is reused later as proof of the PLANNED tests.
    """
    if report.head_sha != head:
        return HEAD_MOVED
    if (
        report.kind is not _STEP_TO_KIND.get(step.kind)
        or report.pr != step.pr
        or report.dispatch_id != dispatch_id
        or {r.id for r in report.requested} != set(step.tests)
    ):
        return REPORT_NOT_REQUESTED
    return None


def target_head(
    step: EvidencePlanStep, removal_before: str | None, removed: PatchRemoval | None
) -> str | None:
    """The SHA a step runs against. A step planned on S' runs on S when nothing was removed.

    ``removal_before`` is the removal step's planned head S.
    """
    if not step.on_cleaned_head:
        return step.head_sha
    return removed.after_sha if removed is not None else removal_before


def build_manifest(
    gate_id: str,
    plan: Sequence[EvidencePlanStep],
    settled: Iterable[SettledStep],
    removed: PatchRemoval | None,
) -> EvidenceManifest:
    """`manifest.json`, from the events alone (§A.6). Raises unless every step settled."""
    by_index = {s.index: s for s in settled}
    missing = [step.index for step in plan if step.index not in by_index]
    if missing:
        raise ValueError(f"gate {gate_id}: steps {missing} have not settled")
    return EvidenceManifest(
        schema=1,
        gate_id=gate_id,
        steps=tuple(
            ManifestStep(
                index=step.index,
                kind=step.kind,
                outcome=by_index[step.index].outcome,
                reason=by_index[step.index].reason,
                run_url=by_index[step.index].run_url,
                head_sha=by_index[step.index].head_sha_evidenced,
                reused_from=by_index[step.index].reused_from,
            )
            for step in plan
        ),
        patch_removal=removed,
        complete=True,
    )


# --- Planning helpers -----------------------------------------------------------


@dataclass
class _MutationGroup:
    """Every mutation request for one (repository, head) collapses into one step (I4)."""

    first: EvidenceRequest
    tests: set[str] = field(default_factory=set)

    def step(self) -> EvidencePlanStep:
        planned = _step_for(self.first, EvidenceStepKind.MUTATION, tuple(sorted(self.tests)))
        if len(self.tests) > MAX_TESTS:
            return planned.model_copy(update={"preset": _preset(StepOutcome.VOID, TOO_MANY_TESTS)})
        return planned


def _step_for(
    request: EvidenceRequest, kind: EvidenceStepKind, tests: Iterable[str]
) -> EvidencePlanStep:
    return EvidencePlanStep(
        index=0,
        kind=kind,
        repository=request.repository,
        branch=request.branch,
        pr=request.pr,
        head_sha=request.head_sha,
        tests=tuple(tests),
    )


def _refusal(declared: DeclaredEvidence, inputs: GateInputs) -> EvidencePlanStep | None:
    """A step that settles at plan time for a declaration the platform cannot act on."""
    request = declared.request
    if request is None:
        # `EvidenceStepKind` has no member for an entry whose kind could not be
        # read; it is planned as the stricter kind so the manifest shows a
        # void mutation step rather than nothing.
        return EvidencePlanStep(
            index=0,
            kind=EvidenceStepKind.MUTATION,
            preset=_preset(StepOutcome.VOID, f"{UNREADABLE}: {declared.unreadable}"),
        )
    kind = _KIND_TO_STEP[request.kind]
    if request.repository not in inputs.repositories:
        reason, outcome = FOREIGN_REPOSITORY, StepOutcome.VOID
    else:
        head = _observed(inputs.observed, request.repository, request.branch)
        if head is None or not head.readable:
            reason, outcome = FORGE_UNREADABLE, StepOutcome.UNAVAILABLE
        elif head.head_sha != request.head_sha:
            reason, outcome = HEAD_MOVED, StepOutcome.VOID
        elif head.open_pr_number != request.pr:
            reason, outcome = PR_MISMATCH, StepOutcome.VOID
        else:
            return None
    return _step_for(request, kind, request.tests).model_copy(
        update={"preset": _preset(outcome, reason)}
    )


def _undeclared_mutation(head: ObservedHead, sha: str, inputs: GateInputs) -> EvidencePlanStep:
    tests = inputs.earlier_mutation_tests.get(head.repository, ())
    return EvidencePlanStep(
        index=0,
        kind=EvidenceStepKind.MUTATION,
        repository=head.repository,
        branch=head.branch,
        pr=head.open_pr_number,
        head_sha=sha,
        tests=tests,
        preset=None if tests else _preset(StepOutcome.VOID, NO_TESTS_DECLARED),
    )


def _cleanup_head(inputs: GateInputs) -> tuple[ObservedHead, str] | None:
    """The head whose patches the gate removes: only in front of the final phase, certified."""
    if not (inputs.next_is_final and inputs.certified):
        return None
    patched = _patched_heads(inputs)
    return patched[0] if patched else None


def _reuse(step: EvidencePlanStep, passed: Sequence[PassedEvidence]) -> EvidencePlanStep:
    if step.preset is not None or step.head_sha is None or not step.tests:
        return step
    for earlier in passed:
        if (
            earlier.kind is step.kind
            and earlier.repository == step.repository
            and earlier.head_sha == step.head_sha
            and set(step.tests) <= earlier.tests
        ):
            return step.model_copy(
                update={
                    "preset": EvidencePreset(outcome=StepOutcome.PASSED, reused_from=earlier.ref)
                }
            )
    return step


def _patched_heads(inputs: GateInputs) -> list[tuple[ObservedHead, str]]:
    """Readable heads carrying patches, in the execution's repositories only (§A.1).

    The observer also reports branches a phase declared in other repositories;
    those were refused as declarations and must not come back as steps.
    """
    return [
        (head, head.head_sha)
        for head in inputs.observed
        if head.readable
        and head.mutation_patches_present
        and head.head_sha is not None
        and head.repository in inputs.repositories
    ]


def _mutation_passed_for(passed: Iterable[PassedEvidence], repository: str, sha: str) -> bool:
    return any(
        p.kind is EvidenceStepKind.MUTATION and p.repository == repository and p.head_sha == sha
        for p in passed
    )


def _observed(
    observed: Iterable[ObservedHead], repository: str, branch: str
) -> ObservedHead | None:
    return next((h for h in observed if (h.repository, h.branch) == (repository, branch)), None)


def _preset(outcome: StepOutcome, reason: str) -> EvidencePreset:
    return EvidencePreset(outcome=outcome, reason=reason)


# --- Replayed state -------------------------------------------------------------

#: Attempts per step before it settles `unavailable` (§A.5).
MAX_ATTEMPTS: Final = 2


@dataclass(frozen=True)
class EvidenceAttempt:
    """The latest attempt at one step, as its events recorded it."""

    attempt: int
    dispatch_id: str
    started_at: datetime
    not_after: datetime
    run_id: int | None = None
    run_url: str | None = None


@dataclass
class EvidenceGate:
    """One gate, rebuilt from its events."""

    gate_id: str
    after_phase_id: str
    next_phase_id: str
    next_phase_order: int
    skipped_phase_ids: tuple[str, ...]
    plan: tuple[EvidencePlanStep, ...]
    attempts: dict[int, EvidenceAttempt] = field(default_factory=dict)
    settled: dict[int, SettledStep] = field(default_factory=dict)
    removed: PatchRemoval | None = None

    @property
    def current(self) -> EvidencePlanStep | None:
        """The first unsettled step, or None once the gate has opened. Steps settle in order."""
        return next((s for s in self.plan if s.index not in self.settled), None)

    def predetermined(self, step: EvidencePlanStep) -> EvidencePreset | None:
        """How ``step`` settles without any I/O, or None when it must be run.

        Planned presets, a removal whose mutation evidence did not pass, and a
        step on S' when nothing was removed. The aggregate holds every settle
        to this, so the handler can only report what was already decided.
        """
        if step.preset is not None:
            return step.preset
        if step.kind is EvidenceStepKind.REMOVE_MUTATION_PATCHES:
            blocked = removal_blocked(self.plan, self.settled.values(), step)
            return None if blocked is None else _preset(StepOutcome.VOID, blocked)
        if step.kind is EvidenceStepKind.REQUIRED_CHECK and self.removed is None:
            return _preset(StepOutcome.VOID, PATCHES_NOT_REMOVED)
        return None

    def head_for(self, step: EvidencePlanStep) -> str | None:
        """The SHA ``step`` runs against, S' once the removal is recorded."""
        removal = next(
            (s for s in self.plan if s.kind is EvidenceStepKind.REMOVE_MUTATION_PATCHES), None
        )
        return target_head(step, removal.head_sha if removal else None, self.removed)

    def manifest(self) -> EvidenceManifest:
        return build_manifest(self.gate_id, self.plan, self.settled.values(), self.removed)


@dataclass
class EvidenceGateRecord:
    """Every gate an execution's stream holds - replayed state, like `ReviewRecord`."""

    _gates: dict[str, EvidenceGate] = field(default_factory=dict)

    def request(self, gate: EvidenceGate) -> None:
        self._gates[gate.gate_id] = gate

    def get(self, gate_id: str) -> EvidenceGate | None:
        return self._gates.get(gate_id)

    def open_gate(self) -> EvidenceGate | None:
        """The gate still holding a transition, if any. At most one can be open."""
        return next((g for g in self._gates.values() if g.current is not None), None)

    def passed(self) -> tuple[PassedEvidence, ...]:
        """Every dispatched step that settled `passed`, for reuse (§A.3). Reuses are not re-counted."""
        found: list[PassedEvidence] = []
        for gate in self._gates.values():
            for step in gate.plan:
                settled = gate.settled.get(step.index)
                if (
                    settled is None
                    or settled.outcome is not StepOutcome.PASSED
                    or settled.reused_from is not None
                    or step.kind not in (EvidenceStepKind.MUTATION, EvidenceStepKind.INTEGRATION)
                ):
                    continue
                head = settled.head_sha_evidenced or gate.head_for(step)
                if step.repository is None or head is None:
                    continue
                found.append(
                    PassedEvidence(
                        ref=StepRef(gate_id=gate.gate_id, step=step.index),
                        kind=step.kind,
                        repository=step.repository,
                        head_sha=head,
                        tests=frozenset(step.tests),
                    )
                )
        return tuple(found)


_PLAN: Final = TypeAdapter(tuple[EvidencePlanStep, ...])
_DATETIME: Final = TypeAdapter(datetime)


def read_plan_steps(raw: object) -> tuple[EvidencePlanStep, ...]:
    """The plan on a replayed `EvidenceRequested`, models or stored JSON alike."""
    return _PLAN.validate_python(raw or ())


def read_datetime(raw: object) -> datetime:
    """A timestamp on a replayed evidence event, a `datetime` or its stored ISO string."""
    return _DATETIME.validate_python(raw)
