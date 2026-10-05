"""The upstream failure reader recognises auth faults that carry detail (#1592).

Both parsers append detail to an auth label: codex its CLI's log line, claude
the provider's own message. A reader that recognised only the bare label read
both as `unknown`, so the operator was never told to fix the credentials.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    _extract_error_reason,  # pyright: ignore[reportPrivateUsage]
)
from syn_domain.contexts.orchestration.slices.execute_workflow.upstream_failure import (
    UPSTREAM_FAILURES,
    UpstreamFailureKind,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw",
    [
        '{"type":"error","error":{"type":"authentication_error","message":"Invalid API key"}}',
        '{"type":"error","error":{"type":"permission_error","message":"Org has no access"}}',
    ],
)
def test_a_claude_auth_error_with_its_message_reads_as_auth(raw: str) -> None:
    reason = _extract_error_reason(raw)

    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.AUTH


def test_detail_never_makes_a_fault_transient() -> None:
    """Only `auth` is read by prefix: appended text must not buy a retry."""
    reason = _extract_error_reason(
        '{"type":"error","error":{"type":"rate_limit_error","message":"quota resets next month"}}'
    )

    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.UNKNOWN


def test_an_auth_label_quoted_mid_reason_is_not_auth() -> None:
    assert (
        UPSTREAM_FAILURES.kind_of("agent wrote: Authentication failed: see above")
        is UpstreamFailureKind.UNKNOWN
    )
