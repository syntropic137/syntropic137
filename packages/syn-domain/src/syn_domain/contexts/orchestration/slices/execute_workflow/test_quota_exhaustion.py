"""A spent quota is its own kind, is never retried, and says when it ends (PC-83).

The codex sentence is the one observed on 2026-10-06, verbatim as the task
recorded it (the task elided the middle of it with "..."). No claude quota
message exists in this repo, agentic-workspace or any fixture, so none is
pinned here and claude quota text reads as it did before.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.upstream_failure import (
    UPSTREAM_FAILURES,
    UpstreamFailureKind,
)
from syn_domain.testing.fake_clock import FakeClock

pytestmark = pytest.mark.unit

CODEX_QUOTA = "You've hit your usage limit ... try again at Oct 9th, 2026 9:10 PM"
CODEX_CAPACITY = "Selected model is at capacity. Please try a different model."


def test_the_observed_codex_quota_sentence_reads_as_quota_with_its_reset() -> None:
    reason = codex_fault_reason(CODEX_QUOTA)

    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.QUOTA
    quota = UPSTREAM_FAILURES.quota_of(reason)
    assert quota is not None
    assert quota.resets_at == datetime(2026, 10, 9, 21, 10, tzinfo=UTC)
    assert quota.account() == "codex quota exhausted until 2026-10-09T21:10:00+00:00"


@pytest.mark.parametrize(
    "message",
    [
        "You've hit your usage limit. Upgrade to Pro or try again later.",
        "Visit settings to purchase more credits",
        "You've hit your usage limit. Try again at 9:10 PM.",
    ],
)
def test_a_codex_quota_without_a_dated_reset_says_the_time_is_unstated(message: str) -> None:
    quota = UPSTREAM_FAILURES.quota_of(codex_fault_reason(message))

    assert quota is not None
    assert quota.account() == "codex quota exhausted until an unstated time"


def test_capacity_is_still_capacity() -> None:
    reason = codex_fault_reason(CODEX_CAPACITY)

    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.CAPACITY
    assert UPSTREAM_FAILURES.quota_of(reason) is None


@pytest.mark.parametrize(
    "reason",
    [
        # An agent quoting codex in its own words is not codex's fault line.
        "agent wrote: You've hit your usage limit ... try again at Oct 9th, 2026 9:10 PM",
        "Rate limit reached; quota resets next month",
    ],
)
def test_quota_words_outside_a_codex_fault_line_are_not_quota(reason: str) -> None:
    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.UNKNOWN
    assert UPSTREAM_FAILURES.quota_of(reason) is None


def test_quota_is_neither_transient_nor_an_operator_fault() -> None:
    assert not UpstreamFailureKind.QUOTA.is_transient
    assert not UpstreamFailureKind.QUOTA.needs_operator
    assert "not retried" in UpstreamFailureKind.QUOTA.account()


async def test_a_quota_failure_is_never_granted_a_retry() -> None:
    clock = FakeClock()
    attempts = UpstreamRetryPolicy(clock=clock.as_attempt_clock()).begin(timeout_seconds=3600)

    grant = await attempts.wait_before_retry(
        reason=codex_fault_reason(CODEX_QUOTA), work_done=False
    )

    assert grant is None
    assert clock.slept == []
