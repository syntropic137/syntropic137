"""Gap vocabulary shared by the resolver and the coverage seal (#1398)."""

from enum import StrEnum


class GapReason(StrEnum):
    # Process outcomes (``invocation_`` + lifecycle status for the others).
    INVOCATION_RUNNING = "invocation_running"
    INVOCATION_LAUNCH_FAILED = "invocation_launch_failed"
    CONFLICTING_LIFECYCLE = "conflicting_invocation_lifecycle"
    # Child attribution through a registered attempt.
    CONFLICTING_CONTEXT = "conflicting_invocation_context"
    UNVERIFIED_CONTEXT = "unverified_invocation_context"
    # Lineage and identity.
    CONFLICTING_PARENTAGE = "conflicting_parentage"
    LINEAGE_CYCLE = "lineage_cycle"
    UNRESOLVED_PARENTAGE = "unresolved_parentage"
    CONFLICTING_SOURCE = "conflicting_source_evidence"
    CONFLICTING_BINDING = "conflicting_native_binding"
    # Coverage seal.
    EXPECTED_BODY_UNAVAILABLE = "expected_body_unavailable"
    INVOCATION_UNSETTLED_AT_SEAL = "invocation_unsettled_at_seal"
    CAPTURE_UNSETTLED_AT_SEAL = "capture_unsettled_at_seal"
    CHILD_CONTEXT_UNRESOLVED_AT_SEAL = "child_context_unresolved_at_seal"
    PARENTAGE_UNRESOLVED_AT_SEAL = "parentage_unresolved_at_seal"
    NO_HOST_REGISTRATION = "no_host_registration"


# Any of these anywhere in a run makes its completeness unknowable.
CONFLICT_REASONS = frozenset(
    {
        GapReason.CONFLICTING_LIFECYCLE,
        GapReason.CONFLICTING_CONTEXT,
        GapReason.CONFLICTING_PARENTAGE,
        GapReason.LINEAGE_CYCLE,
        GapReason.CONFLICTING_SOURCE,
        GapReason.CONFLICTING_BINDING,
    }
)
