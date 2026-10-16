"""The evidence gate's pure rules (plan §A.3/§A.6, PR 5b).

Every fixture is built from PR 5a's recorded state (`DeclaredEvidence`,
`ObservedHead`) and PR 1's contract, never from a shape invented here, so a
change to either fails these rather than drifting past them.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceRequest,
    EvidenceStepKind,
    PatchRemoval,
    StepOutcome,
    StepRef,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
    FOREIGN_REPOSITORY,
    FORGE_UNREADABLE,
    HEAD_MOVED,
    MUTATION_NOT_PASSED,
    NO_TESTS_DECLARED,
    PR_MISMATCH,
    TOO_MANY_TESTS,
    UNREADABLE,
    GateInputs,
    PassedEvidence,
    PlannedStep,
    SettledStep,
    build_manifest,
    gate_opens,
    plan_steps,
    removal_blocked,
    target_head,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    DeclaredEvidence,
    ObservedHead,
)

pytestmark = pytest.mark.unit

REPO = "syntropic137/syntropic137"
BRANCH = "feat/x"
S = "a" * 40
S2 = "b" * 40
S_PRIME = "c" * 40
PR = 42


def _request(
    kind: EvidenceKind = EvidenceKind.MUTATION,
    tests: tuple[str, ...] = ("tests/test_a.py::test_one",),
    *,
    repository: str = REPO,
    head_sha: str = S,
    pr: int = PR,
) -> DeclaredEvidence:
    return DeclaredEvidence(
        request=EvidenceRequest(
            kind=kind, repository=repository, branch=BRANCH, pr=pr, head_sha=head_sha, tests=tests
        )
    )


def _head(*, sha: str = S, patches: bool | None = False, readable: bool = True) -> ObservedHead:
    return ObservedHead(
        repository=REPO,
        branch=BRANCH,
        readable=readable,
        head_sha=sha if readable else None,
        mutation_patches_present=patches,
        open_pr_number=PR,
    )


def _inputs(
    declared: tuple[DeclaredEvidence, ...] = (),
    observed: tuple[ObservedHead, ...] = (),
    *,
    final: bool = False,
    certified: bool = False,
    passed: tuple[PassedEvidence, ...] = (),
    earlier: dict[str, tuple[str, ...]] | None = None,
) -> GateInputs:
    return GateInputs(
        declared=declared,
        observed=observed or (_head(),),
        repositories=frozenset({REPO}),
        next_is_final=final,
        certified=certified,
        passed=passed,
        earlier_mutation_tests=earlier or {},
    )


def _passed_mutation(tests: tuple[str, ...], sha: str = S) -> PassedEvidence:
    return PassedEvidence(
        ref=StepRef(gate_id="g-earlier", step=0),
        kind=EvidenceStepKind.MUTATION,
        repository=REPO,
        head_sha=sha,
        tests=frozenset(tests),
    )


class TestGateOpens:
    def test_flag_off_never_opens_even_with_a_declaration(self) -> None:
        assert not gate_opens(enabled=False, has_next_phase=True, inputs=_inputs((_request(),)))

    def test_never_after_the_final_phase(self) -> None:
        assert not gate_opens(enabled=True, has_next_phase=False, inputs=_inputs((_request(),)))

    def test_a_declaration_opens_it(self) -> None:
        assert gate_opens(enabled=True, has_next_phase=True, inputs=_inputs((_request(),)))

    def test_an_unreadable_declaration_opens_it(self) -> None:
        declared = (DeclaredEvidence.refused("kind: bad"),)
        assert gate_opens(enabled=True, has_next_phase=True, inputs=_inputs(declared))

    def test_nothing_declared_nothing_patched_stays_shut(self) -> None:
        assert not gate_opens(enabled=True, has_next_phase=True, inputs=_inputs())

    def test_undeclared_patches_without_passed_evidence_open_it(self) -> None:
        inputs = _inputs(observed=(_head(patches=True),))
        assert gate_opens(enabled=True, has_next_phase=True, inputs=inputs)

    def test_patches_already_proven_on_that_sha_do_not_open_it_mid_loop(self) -> None:
        inputs = _inputs(observed=(_head(patches=True),), passed=(_passed_mutation(("t.py",)),))
        assert not gate_opens(enabled=True, has_next_phase=True, inputs=inputs)

    def test_proven_patches_open_it_before_a_certified_final_phase_for_cleanup(self) -> None:
        inputs = _inputs(
            observed=(_head(patches=True),),
            passed=(_passed_mutation(("t.py",)),),
            final=True,
            certified=True,
        )
        assert gate_opens(enabled=True, has_next_phase=True, inputs=inputs)

    def test_an_unreadable_forge_with_nothing_declared_stays_shut(self) -> None:
        inputs = _inputs(observed=(_head(readable=False, patches=None),))
        assert not gate_opens(enabled=True, has_next_phase=True, inputs=inputs)


class TestIdentityAndRefusals:
    def _only(self, inputs: GateInputs) -> PlannedStep:
        (step,) = plan_steps(inputs)
        return step

    def test_unreadable_declaration_is_a_void_step_not_a_drop(self) -> None:
        step = self._only(_inputs((DeclaredEvidence.refused("pr: not an int"),)))
        assert step.preset is not None
        assert step.preset.outcome is StepOutcome.VOID
        assert step.preset.reason == f"{UNREADABLE}: pr: not an int"

    def test_foreign_repository_is_void(self) -> None:
        step = self._only(_inputs((_request(repository="other/repo"),)))
        assert step.preset is not None
        assert (step.preset.outcome, step.preset.reason) == (StepOutcome.VOID, FOREIGN_REPOSITORY)

    def test_declared_head_the_forge_does_not_have_is_void(self) -> None:
        step = self._only(_inputs((_request(head_sha=S2),)))
        assert step.preset is not None
        assert step.preset.reason == HEAD_MOVED

    def test_declared_pr_not_open_from_the_branch_is_void(self) -> None:
        step = self._only(_inputs((_request(pr=PR + 1),)))
        assert step.preset is not None
        assert step.preset.reason == PR_MISMATCH

    def test_unreadable_forge_with_a_declaration_is_unavailable(self) -> None:
        step = self._only(_inputs((_request(),), (_head(readable=False),)))
        assert step.preset is not None
        assert (step.preset.outcome, step.preset.reason) == (
            StepOutcome.UNAVAILABLE,
            FORGE_UNREADABLE,
        )

    def test_a_matching_declaration_is_dispatched(self) -> None:
        step = self._only(_inputs((_request(),)))
        assert step.preset is None
        assert (step.repository, step.head_sha, step.pr) == (REPO, S, PR)


class TestMutationNormalisation:
    def test_requests_for_one_head_collapse_into_one_step_with_the_sorted_union(self) -> None:
        declared = (
            _request(tests=("tests/test_b.py::t", "tests/test_a.py::t")),
            _request(tests=("tests/test_a.py::t", "tests/test_c.py::t")),
        )
        (step,) = plan_steps(_inputs(declared))
        assert step.tests == ("tests/test_a.py::t", "tests/test_b.py::t", "tests/test_c.py::t")

    def test_a_union_over_the_dispatch_limit_is_void(self) -> None:
        first = tuple(f"tests/test_{i}.py::t" for i in range(30))
        second = tuple(f"tests/test_{i}.py::t" for i in range(30, 60))
        (step,) = plan_steps(_inputs((_request(tests=first), _request(tests=second))))
        assert step.preset is not None
        assert step.preset.reason == TOO_MANY_TESTS

    def test_undeclared_patches_reuse_the_earlier_selection(self) -> None:
        earlier = {REPO: ("tests/test_old.py::t",)}
        (step,) = plan_steps(_inputs(observed=(_head(patches=True),), earlier=earlier))
        assert step.kind is EvidenceStepKind.MUTATION
        assert step.preset is None
        assert (step.head_sha, step.tests) == (S, ("tests/test_old.py::t",))

    def test_undeclared_patches_with_no_selection_settle_void(self) -> None:
        (step,) = plan_steps(_inputs(observed=(_head(patches=True),)))
        assert step.preset is not None
        assert (step.preset.outcome, step.preset.reason) == (StepOutcome.VOID, NO_TESTS_DECLARED)

    def test_declared_patches_are_not_planned_twice(self) -> None:
        steps = plan_steps(_inputs((_request(),), (_head(patches=True),)))
        assert [s.kind for s in steps] == [EvidenceStepKind.MUTATION]


class TestReuse:
    def test_a_subset_of_passed_tests_on_the_same_head_is_reused(self) -> None:
        passed = (_passed_mutation(("tests/test_a.py::test_one", "tests/test_b.py::t")),)
        (step,) = plan_steps(_inputs((_request(),), passed=passed))
        assert step.preset is not None
        assert step.preset.outcome is StepOutcome.PASSED
        assert step.preset.reused_from == StepRef(gate_id="g-earlier", step=0)

    def test_a_test_beyond_what_passed_is_dispatched_again(self) -> None:
        passed = (_passed_mutation(("tests/test_b.py::t",)),)
        (step,) = plan_steps(_inputs((_request(),), passed=passed))
        assert step.preset is None

    def test_another_head_is_not_reused(self) -> None:
        passed = (_passed_mutation(("tests/test_a.py::test_one",), sha=S2),)
        (step,) = plan_steps(_inputs((_request(),), passed=passed))
        assert step.preset is None


class TestCleanupPlanning:
    def _final(self, *, certified: bool) -> tuple[PlannedStep, ...]:
        declared = (
            _request(),
            _request(EvidenceKind.INTEGRATION, ("tests/integration/test_i.py::t",)),
        )
        return plan_steps(
            _inputs(declared, (_head(patches=True),), final=True, certified=certified)
        )

    def test_certified_in_front_of_the_final_phase_orders_the_whole_sequence(self) -> None:
        steps = self._final(certified=True)
        assert [s.kind for s in steps] == [
            EvidenceStepKind.MUTATION,
            EvidenceStepKind.REMOVE_MUTATION_PATCHES,
            EvidenceStepKind.INTEGRATION,
            EvidenceStepKind.REQUIRED_CHECK,
        ]
        assert [s.index for s in steps] == [0, 1, 2, 3]
        integration = steps[2]
        assert integration.on_cleaned_head
        assert integration.head_sha is None
        assert steps[1].head_sha == S

    def test_without_certification_patches_stay_and_integration_runs_on_s(self) -> None:
        steps = self._final(certified=False)
        assert [s.kind for s in steps] == [EvidenceStepKind.MUTATION, EvidenceStepKind.INTEGRATION]
        assert steps[1].head_sha == S
        assert not steps[1].on_cleaned_head

    def test_never_cleans_up_in_front_of_a_review(self) -> None:
        steps = plan_steps(_inputs((_request(),), (_head(patches=True),), certified=True))
        assert EvidenceStepKind.REMOVE_MUTATION_PATCHES not in [s.kind for s in steps]


class TestWhenAStepIsReached:
    def _plan(self) -> tuple[PlannedStep, ...]:
        return plan_steps(
            _inputs((_request(),), (_head(patches=True),), final=True, certified=True)
        )

    def test_removal_waits_for_every_mutation_step_on_its_head_to_pass(self) -> None:
        plan = self._plan()
        removal = plan[1]
        failed = (SettledStep(index=0, outcome=StepOutcome.FAILED),)
        assert removal_blocked(plan, failed, removal) == MUTATION_NOT_PASSED
        assert removal_blocked(plan, (), removal) == MUTATION_NOT_PASSED
        passed = (SettledStep(index=0, outcome=StepOutcome.PASSED),)
        assert removal_blocked(plan, passed, removal) is None

    def test_a_step_on_the_cleaned_head_follows_the_removal(self) -> None:
        check = self._plan()[2]
        removed = PatchRemoval(before_sha=S, after_sha=S_PRIME, author="syn-app[bot]")
        assert target_head(check, S, removed) == S_PRIME
        assert target_head(check, S, None) == S

    def test_a_step_on_s_ignores_the_removal(self) -> None:
        mutation = self._plan()[0]
        removed = PatchRemoval(before_sha=S, after_sha=S_PRIME, author="syn-app[bot]")
        assert target_head(mutation, S, removed) == S


class TestManifest:
    def test_is_built_from_settlements_with_provenance(self) -> None:
        plan = plan_steps(
            _inputs((_request(),), (_head(patches=True),), final=True, certified=True)
        )
        removed = PatchRemoval(before_sha=S, after_sha=S_PRIME, author="syn-app[bot]")
        settled = (
            SettledStep(index=0, outcome=StepOutcome.PASSED, run_url="u0", head_sha_evidenced=S),
            SettledStep(index=1, outcome=StepOutcome.PASSED, head_sha_evidenced=S_PRIME),
            SettledStep(index=2, outcome=StepOutcome.UNAVAILABLE, reason="timeout"),
        )
        manifest = build_manifest("g-1", plan, settled, removed)
        assert manifest.complete is True
        assert manifest.patch_removal == removed
        assert [(s.kind, s.outcome) for s in manifest.steps] == [
            (EvidenceStepKind.MUTATION, StepOutcome.PASSED),
            (EvidenceStepKind.REMOVE_MUTATION_PATCHES, StepOutcome.PASSED),
            (EvidenceStepKind.REQUIRED_CHECK, StepOutcome.UNAVAILABLE),
        ]
        assert manifest.steps[0].run_url == "u0"
        assert manifest.steps[2].reason == "timeout"

    def test_refuses_while_a_step_is_unsettled(self) -> None:
        plan = plan_steps(_inputs((_request(), _request(EvidenceKind.INTEGRATION))))
        settled = (SettledStep(index=0, outcome=StepOutcome.PASSED),)
        with pytest.raises(ValueError, match=r"steps \[1\] have not settled"):
            build_manifest("g-1", plan, settled, None)

    def test_a_reused_step_points_at_its_origin(self) -> None:
        plan = plan_steps(
            _inputs((_request(),), passed=(_passed_mutation(("tests/test_a.py::test_one",)),))
        )
        origin = StepRef(gate_id="g-earlier", step=0)
        settled = (SettledStep(index=0, outcome=StepOutcome.PASSED, reused_from=origin),)
        assert build_manifest("g-2", plan, settled, None).steps[0].reused_from == origin
