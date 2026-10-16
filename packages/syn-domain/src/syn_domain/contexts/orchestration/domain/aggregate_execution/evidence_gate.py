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

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

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

    from syn_domain.contexts.orchestration._shared.evidence_contract import EvidenceRequest
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        DeclaredEvidence,
        ObservedHead,
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

_KIND_TO_STEP: Final = {
    EvidenceKind.MUTATION: EvidenceStepKind.MUTATION,
    EvidenceKind.INTEGRATION: EvidenceStepKind.INTEGRATION,
}


@dataclass(frozen=True)
class Preset:
    """A step that settles when it is reached, without dispatching anything."""

    outcome: StepOutcome
    reason: str | None = None
    reused_from: StepRef | None = None


@dataclass(frozen=True)
class PlannedStep:
    """One step of a gate's plan, as `EvidenceRequested` records it.

    ``head_sha`` None with ``on_cleaned_head`` True means "the head the
    removal step produced", which does not exist when the plan is made.
    """

    index: int
    kind: EvidenceStepKind
    repository: str | None = None
    branch: str | None = None
    pr: int | None = None
    head_sha: str | None = None
    tests: tuple[str, ...] = ()
    on_cleaned_head: bool = False
    preset: Preset | None = None


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
    patched = _patched_heads(inputs.observed)
    if any(not _mutation_passed_for(inputs.passed, h.repository, sha) for h, sha in patched):
        return True
    return inputs.next_is_final and inputs.certified and bool(patched)


def plan_steps(inputs: GateInputs) -> tuple[PlannedStep, ...]:
    """The ordered plan: mutation, removal, integration, required check (§A.3)."""
    mutation: dict[tuple[str, str], _MutationGroup] = {}
    integration: list[PlannedStep] = []
    unplannable: list[PlannedStep] = []
    for declared in inputs.declared:
        refused = _refusal(declared, inputs)
        if refused is not None:
            unplannable.append(refused)
            continue
        request = declared.request
        assert request is not None  # `_refusal` returned None, so it is a request
        if request.kind is EvidenceKind.MUTATION:
            key = (request.repository, request.head_sha)
            mutation.setdefault(key, _MutationGroup(request)).tests.update(request.tests)
        else:
            integration.append(_step_for(request, EvidenceStepKind.INTEGRATION, request.tests))

    undeclared = [
        (head, sha)
        for head, sha in _patched_heads(inputs.observed)
        if (head.repository, sha) not in mutation
        and not _mutation_passed_for(inputs.passed, head.repository, sha)
    ]
    steps: list[PlannedStep] = [group.step() for group in mutation.values()]
    steps += [_undeclared_mutation(head, sha, inputs) for head, sha in undeclared]
    steps += unplannable

    cleanup = _cleanup_head(inputs)
    if cleanup is not None:
        head, sha = cleanup
        steps.append(
            PlannedStep(
                index=0,
                kind=EvidenceStepKind.REMOVE_MUTATION_PATCHES,
                repository=head.repository,
                branch=head.branch,
                pr=head.open_pr_number,
                head_sha=sha,
            )
        )
    for step in integration:
        moves = cleanup is not None and (step.repository, step.head_sha) == (
            cleanup[0].repository,
            cleanup[1],
        )
        steps.append(replace(step, head_sha=None, on_cleaned_head=True) if moves else step)
    if cleanup is not None:
        head, _ = cleanup
        steps.append(
            PlannedStep(
                index=0,
                kind=EvidenceStepKind.REQUIRED_CHECK,
                repository=head.repository,
                branch=head.branch,
                pr=head.open_pr_number,
                on_cleaned_head=True,
            )
        )
    return tuple(_reuse(replace(s, index=i), inputs.passed) for i, s in enumerate(steps))


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
    plan: Sequence[PlannedStep], settled: Iterable[SettledStep], removal: PlannedStep
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


def target_head(
    step: PlannedStep, removal_before: str | None, removed: PatchRemoval | None
) -> str | None:
    """The SHA a step runs against. A step planned on S' runs on S when nothing was removed.

    ``removal_before`` is the removal step's planned head S.
    """
    if not step.on_cleaned_head:
        return step.head_sha
    return removed.after_sha if removed is not None else removal_before


def build_manifest(
    gate_id: str,
    plan: Sequence[PlannedStep],
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

    def step(self) -> PlannedStep:
        planned = _step_for(self.first, EvidenceStepKind.MUTATION, tuple(sorted(self.tests)))
        if len(self.tests) > MAX_TESTS:
            return replace(planned, preset=Preset(StepOutcome.VOID, TOO_MANY_TESTS))
        return planned


def _step_for(
    request: EvidenceRequest, kind: EvidenceStepKind, tests: Iterable[str]
) -> PlannedStep:
    return PlannedStep(
        index=0,
        kind=kind,
        repository=request.repository,
        branch=request.branch,
        pr=request.pr,
        head_sha=request.head_sha,
        tests=tuple(tests),
    )


def _refusal(declared: DeclaredEvidence, inputs: GateInputs) -> PlannedStep | None:
    """A step that settles at plan time for a declaration the platform cannot act on."""
    request = declared.request
    if request is None:
        # `EvidenceStepKind` has no member for an entry whose kind could not be
        # read; it is planned as the stricter kind so the manifest shows a
        # void mutation step rather than nothing.
        return PlannedStep(
            index=0,
            kind=EvidenceStepKind.MUTATION,
            preset=Preset(StepOutcome.VOID, f"{UNREADABLE}: {declared.unreadable}"),
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
    return replace(_step_for(request, kind, request.tests), preset=Preset(outcome, reason))


def _undeclared_mutation(head: ObservedHead, sha: str, inputs: GateInputs) -> PlannedStep:
    tests = inputs.earlier_mutation_tests.get(head.repository, ())
    return PlannedStep(
        index=0,
        kind=EvidenceStepKind.MUTATION,
        repository=head.repository,
        branch=head.branch,
        pr=head.open_pr_number,
        head_sha=sha,
        tests=tests,
        preset=None if tests else Preset(StepOutcome.VOID, NO_TESTS_DECLARED),
    )


def _cleanup_head(inputs: GateInputs) -> tuple[ObservedHead, str] | None:
    """The head whose patches the gate removes: only in front of the final phase, certified."""
    if not (inputs.next_is_final and inputs.certified):
        return None
    patched = _patched_heads(inputs.observed)
    return patched[0] if patched else None


def _reuse(step: PlannedStep, passed: Sequence[PassedEvidence]) -> PlannedStep:
    if step.preset is not None or step.head_sha is None or not step.tests:
        return step
    for earlier in passed:
        if (
            earlier.kind is step.kind
            and earlier.repository == step.repository
            and earlier.head_sha == step.head_sha
            and set(step.tests) <= earlier.tests
        ):
            return replace(step, preset=Preset(StepOutcome.PASSED, reused_from=earlier.ref))
    return step


def _patched_heads(observed: Iterable[ObservedHead]) -> list[tuple[ObservedHead, str]]:
    return [
        (head, head.head_sha)
        for head in observed
        if head.readable and head.mutation_patches_present and head.head_sha is not None
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
