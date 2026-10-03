"""Process state survives replay without certifying descendant/capture settlement."""

from itertools import permutations

import pytest

from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    InvocationLifecycleEvidence,
    StoredEvidenceBatch,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    CoverageContract,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceReference,
    EvidenceRetraction,
    InventoryNodeRef,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.services.evidence_assembly import assemble_evidence
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)

pytestmark = pytest.mark.unit
RUN = RunIdentity(source_instance_id="source", execution_id="run")
NODE = InventoryNodeRef(kind="invocation", source_instance_id="source", local_id="child")


def observation(sequence: int, status: str, code: int | None = None) -> InvocationLifecycleEvidence:
    return InvocationLifecycleEvidence.model_validate(
        {
            "node": NODE,
            "sequence": sequence,
            "status": status,
            "exit_code": code,
            "evidence": EvidenceReference(
                producer_id="journal",
                evidence_id=f"record-{sequence}",
                source_revision=str(sequence),
                locator=f"record/{sequence}",
                extractor_version="1",
            ),
        }
    )


def source(*items: InvocationLifecycleEvidence) -> SessionEvidence:
    return SessionEvidence(
        run=RUN,
        invocation_lifecycle=items,
        coverage_contract=CoverageContract(contract_id="supported/1", expected_nodes=(NODE,)),
    )


@pytest.mark.parametrize(
    "status,code,reason",
    [
        ("launch_failed", None, "invocation_launch_failed"),
        ("failed", 1, "invocation_transport_failed_before_announce"),
        ("cancelled", -15, "invocation_cancelled"),
        ("launched", None, "invocation_running"),
    ],
)
def test_outcomes_remain_distinct(status: str, code: int | None, reason: str) -> None:
    result = resolve_relationships(source(observation(1, status, code)))
    assert reason in {gap.reason for gap in result.gaps}
    assert result.coverage.state == "open"
    assert result.coverage.missing_keys == (NODE.key,)
    assert result.bindings == ()


def test_failure_after_an_observed_launch_is_invocation_failed() -> None:
    records = (observation(1, "launched"), observation(2, "failed", 1))
    for order in permutations(records):
        reasons = {gap.reason for gap in resolve_relationships(source(*order)).gaps}
        assert "invocation_failed" in reasons
        assert "invocation_transport_failed_before_announce" not in reasons


def test_process_completion_clears_running_gap_but_does_not_seal_capture() -> None:
    records = (observation(1, "launched"), observation(2, "completed", 0))
    expected = resolve_relationships(source(*records))
    assert expected.coverage.state == "open"
    assert {gap.reason for gap in expected.gaps} == {"expected_body_unavailable"}
    for order in permutations(records):
        assert resolve_relationships(source(*order, order[0])) == expected


def test_running_child_reopens_a_premature_seal() -> None:
    original = source(observation(1, "launched"))
    assert original.coverage_contract is not None
    sealed = original.model_copy(
        update={
            "coverage_contract": original.coverage_contract.model_copy(update={"sealed": True}),
        }
    )
    assert resolve_relationships(sealed).coverage.state == "open"


@pytest.mark.parametrize(
    "records",
    [
        (observation(1, "completed", 0), observation(2, "failed", 1)),
        (observation(1, "completed", 0), observation(2, "launched")),
        (observation(1, "launch_failed"), observation(2, "completed", 0)),
    ],
)
def test_impossible_transition_never_chooses_latest_terminal(
    records: tuple[InvocationLifecycleEvidence, ...],
) -> None:
    results = [resolve_relationships(source(*order)) for order in permutations(records)]
    assert results[0] == results[1]
    assert "conflicting_invocation_lifecycle" in {gap.reason for gap in results[0].gaps}


def test_lifecycle_survives_serialization_assembly_and_explicit_correction() -> None:
    item = observation(1, "launch_failed")
    batch = StoredEvidenceBatch(
        sequence=1,
        batch=EvidenceBatch(
            producer_id="journal",
            batch_id="1",
            evidence=source(item),
        ),
    )
    restored = StoredEvidenceBatch.model_validate_json(batch.model_dump_json())
    assembled = assemble_evidence(RUN, (restored,))
    assert resolve_relationships(assembled) == resolve_relationships(source(item))
    corrected = assembled.model_copy(
        update={
            "retractions": (
                EvidenceRetraction(
                    target=item.evidence,
                    evidence=item.evidence.model_copy(update={"evidence_id": "correction"}),
                ),
            )
        }
    )
    assert "invocation_launch_failed" not in {
        g.reason for g in resolve_relationships(corrected).gaps
    }


def test_lifecycle_cannot_bypass_scope_and_batch_quota() -> None:
    item = observation(1, "launched")
    with pytest.raises(ValueError, match="namespaces"):
        SessionEvidence(
            run=RunIdentity(source_instance_id="other", execution_id="run"),
            invocation_lifecycle=(item,),
        )
    with pytest.raises(ValueError, match="500"):
        EvidenceBatch(producer_id="journal", batch_id="1", evidence=source(*(item,) * 501))


@pytest.mark.parametrize("status,code", [("launch_failed", 1), ("failed", 0)])
def test_malformed_outcomes_are_rejected(status: str, code: int | None) -> None:
    with pytest.raises(ValueError, match="disagree"):
        observation(1, status, code)


def test_independent_producer_sequences_cannot_hide_conflicting_process_outcome() -> None:
    completed = observation(100, "completed", 0)
    failed = observation(1, "launch_failed")
    failed = failed.model_copy(
        update={
            "evidence": failed.evidence.model_copy(update={"producer_id": "other-journal"}),
        }
    )
    for order in permutations((completed, failed)):
        result = resolve_relationships(source(*order))
        assert "conflicting_invocation_lifecycle" in {gap.reason for gap in result.gaps}


def test_same_sequence_conflicting_outcomes_remain_visible() -> None:
    completed = observation(1, "completed", 0)
    failed = observation(1, "failed", 1)
    failed = failed.model_copy(
        update={
            "evidence": failed.evidence.model_copy(update={"evidence_id": "conflicting-record"}),
        }
    )
    result = resolve_relationships(source(completed, failed))
    assert "conflicting_invocation_lifecycle" in {gap.reason for gap in result.gaps}


def test_unknown_exit_code_is_not_fabricated_or_conflicting_with_later_proof() -> None:
    historical = observation(1, "completed")
    precise = observation(2, "completed", 0)
    assert historical.exit_code is None
    result = resolve_relationships(source(historical, precise))
    assert {gap.reason for gap in result.gaps} == {"expected_body_unavailable"}
    assert result.coverage.state == "open"


# --- Schema v3 native child lifecycle (#1398) --------------------------------


def _gaps(*items: InvocationLifecycleEvidence) -> set[str]:
    return {gap.reason for gap in resolve_relationships(source(*items)).gaps}


def test_pending_intent_is_its_own_gap_never_running_or_settled() -> None:
    from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import GapReason

    pending = _gaps(observation(1, "pending"))
    assert GapReason.INVOCATION_PENDING in pending
    assert GapReason.INVOCATION_RUNNING not in pending
    # Launch acknowledged after the intent: running, then settled by the stop.
    assert GapReason.INVOCATION_PENDING not in _gaps(
        observation(1, "pending"), observation(2, "launched")
    )
    assert (
        _gaps(observation(1, "pending"), observation(2, "launched"), observation(3, "completed"))
        & {
            GapReason.INVOCATION_PENDING,
            GapReason.INVOCATION_RUNNING,
        }
        == set()
    )


def test_native_stop_without_exit_code_settles() -> None:
    settled = observation(2, "completed")
    assert settled.exit_code is None
    assert not any(
        reason.startswith("invocation_") for reason in _gaps(observation(1, "pending"), settled)
    )


def test_pending_rejects_an_exit_code_and_only_failed_launches_carry_a_reason() -> None:
    from pydantic import ValidationError

    from syn_domain.contexts.agent_sessions import LaunchFailureReason

    with pytest.raises(ValidationError):
        observation(1, "pending", 0)
    completed = observation(1, "completed").model_dump()
    with pytest.raises(ValidationError):
        InvocationLifecycleEvidence.model_validate(
            {**completed, "reason": LaunchFailureReason.HOOK_WATCHDOG}
        )


@pytest.mark.parametrize(
    "cause",
    [
        "process_start_failed",
        "codex_sandbox_unavailable",
        "native_tool_failed",
        "native_tool_interrupted",
        "capture_hook_failed",
        "hook_watchdog",
        "capture_hook_unreachable",
        "claude_nested_auth_unavailable",
        "parent_permissions_unavailable",
        "nested_journal_unavailable",
    ],
)
def test_every_named_launch_failure_maps_to_its_own_gap(cause: str) -> None:
    from syn_domain.contexts.agent_sessions import LaunchFailureReason
    from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import (
        LAUNCH_FAILED_REASONS,
        LAUNCH_FAILURE_GAPS,
        GapReason,
    )

    reason = LaunchFailureReason(cause)
    failed = observation(2, "launch_failed").model_copy(update={"reason": reason})
    gaps = _gaps(observation(1, "pending"), failed)
    assert LAUNCH_FAILURE_GAPS[reason] in gaps
    assert LAUNCH_FAILURE_GAPS[reason] in LAUNCH_FAILED_REASONS
    assert GapReason.INVOCATION_LAUNCH_FAILED not in gaps
    assert GapReason.INVOCATION_PENDING not in gaps


def test_launch_failure_vocabulary_is_total() -> None:
    from syn_domain.contexts.agent_sessions import LaunchFailureReason
    from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import LAUNCH_FAILURE_GAPS

    assert set(LAUNCH_FAILURE_GAPS) == set(LaunchFailureReason)
    assert len(set(LAUNCH_FAILURE_GAPS.values())) == len(LaunchFailureReason)


def test_unnamed_launch_failure_stays_generic() -> None:
    from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import GapReason

    assert GapReason.INVOCATION_LAUNCH_FAILED in _gaps(observation(1, "launch_failed"))
