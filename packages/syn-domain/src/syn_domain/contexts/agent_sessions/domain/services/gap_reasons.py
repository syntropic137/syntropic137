"""Gap vocabulary shared by the resolver and the coverage seal (#1398)."""

from enum import StrEnum

from syn_domain.contexts.agent_sessions.domain.read_models.launch_failure import (
    LaunchFailureReason,
)


class GapReason(StrEnum):
    # Process outcomes (``invocation_`` + lifecycle status for the others).
    INVOCATION_RUNNING = "invocation_running"
    # A committed child intent whose launch was never acknowledged (a native
    # hook killed between commit and exit, a launch denied by another hook, or
    # a spawn the harness rejected without firing a hook). Never settled.
    INVOCATION_PENDING = "invocation_pending"
    INVOCATION_LAUNCH_FAILED = "invocation_launch_failed"
    # A failed launch whose producer named the cause (see LaunchFailureReason).
    LAUNCH_FAILED_PROCESS_START = "invocation_launch_failed_process_start_failed"
    LAUNCH_FAILED_CODEX_SANDBOX_UNAVAILABLE = "invocation_launch_failed_codex_sandbox_unavailable"
    LAUNCH_FAILED_NATIVE_TOOL_FAILED = "invocation_launch_failed_native_tool_failed"
    LAUNCH_FAILED_NATIVE_TOOL_INTERRUPTED = "invocation_launch_failed_native_tool_interrupted"
    LAUNCH_FAILED_CAPTURE_HOOK_FAILED = "invocation_launch_failed_capture_hook_failed"
    LAUNCH_FAILED_HOOK_WATCHDOG = "invocation_launch_failed_hook_watchdog"
    LAUNCH_FAILED_CAPTURE_HOOK_UNREACHABLE = "invocation_launch_failed_capture_hook_unreachable"
    # Failed with no launch ever observed and no native id ever claimed: the
    # transport broke before the wrapper announced, so the agent is not known
    # to have run. Distinct from a launched-then-failed ``invocation_failed``.
    INVOCATION_TRANSPORT_FAILED_BEFORE_ANNOUNCE = "invocation_transport_failed_before_announce"
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


LAUNCH_FAILURE_GAPS: dict[LaunchFailureReason, GapReason] = {
    LaunchFailureReason.PROCESS_START_FAILED: GapReason.LAUNCH_FAILED_PROCESS_START,
    LaunchFailureReason.CODEX_SANDBOX_UNAVAILABLE: (
        GapReason.LAUNCH_FAILED_CODEX_SANDBOX_UNAVAILABLE
    ),
    LaunchFailureReason.NATIVE_TOOL_FAILED: GapReason.LAUNCH_FAILED_NATIVE_TOOL_FAILED,
    LaunchFailureReason.NATIVE_TOOL_INTERRUPTED: GapReason.LAUNCH_FAILED_NATIVE_TOOL_INTERRUPTED,
    LaunchFailureReason.CAPTURE_HOOK_FAILED: GapReason.LAUNCH_FAILED_CAPTURE_HOOK_FAILED,
    LaunchFailureReason.HOOK_WATCHDOG: GapReason.LAUNCH_FAILED_HOOK_WATCHDOG,
    LaunchFailureReason.CAPTURE_HOOK_UNREACHABLE: GapReason.LAUNCH_FAILED_CAPTURE_HOOK_UNREACHABLE,
}

# Every gap that means "this child never started": it needs no body.
LAUNCH_FAILED_REASONS = frozenset(
    {GapReason.INVOCATION_LAUNCH_FAILED, *LAUNCH_FAILURE_GAPS.values()}
)

# Invocations that have not reached an outcome: they block any seal until the
# settlement deadline, then become ``invocation_unsettled_at_seal``.
UNSETTLED_PROCESS_REASONS = frozenset({GapReason.INVOCATION_RUNNING, GapReason.INVOCATION_PENDING})
