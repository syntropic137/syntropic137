"""A spent quota is its own kind, is never retried, and says when it ends (PC-83).

The codex sentence is the one observed on 2026-10-06, byte for byte as the
task recorded it. The claude sentence is the one exec-0ffa4337a4a8 stored on
2026-10-13 (PC-151, #1669), byte for byte, which 1.0.0 read as UNKNOWN.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    _extract_error_reason,  # pyright: ignore[reportPrivateUsage]
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_1344_raw_stream_activity_stops_a_retry import (
    _claude,  # pyright: ignore[reportPrivateUsage]
    _run_claude,  # pyright: ignore[reportPrivateUsage]
)
from syn_domain.contexts.orchestration.slices.execute_workflow.upstream_failure import (
    UPSTREAM_FAILURES,
    UpstreamFailureKind,
)
from syn_domain.testing.fake_clock import FakeClock

pytestmark = pytest.mark.unit

CODEX_QUOTA = (
    "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to "
    "purchase more credits or try again at Oct 9th, 2026 9:10 PM."
)
CLAUDE_WEEKLY_LIMIT = "You've hit your weekly limit · resets Oct 15, 8am (UTC)"
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
        f"agent wrote: {CODEX_QUOTA}",
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


def _claude_reason(result_text: str) -> str:
    """The reason the claude parser records for an `is_error` result carrying this text."""
    return _extract_error_reason(result_text)


def test_the_stored_claude_weekly_limit_reads_as_quota() -> None:
    """PC-151: the exact stored line, through the parser that writes the reason."""
    reason = _claude_reason(CLAUDE_WEEKLY_LIMIT)

    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.QUOTA
    quota = UPSTREAM_FAILURES.quota_of(reason)
    assert quota is not None
    assert quota.provider == "claude"
    # The line names no year, so the reset cannot be placed without guessing one.
    assert quota.account() == "claude quota exhausted until an unstated time"


def test_an_agent_quoting_the_claude_weekly_limit_is_not_quota() -> None:
    reason = _claude_reason(f"The CLI said: {CLAUDE_WEEKLY_LIMIT}")

    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.UNKNOWN


async def test_the_claude_weekly_limit_is_never_retried() -> None:
    clock = FakeClock()
    attempts = UpstreamRetryPolicy(clock=clock.as_attempt_clock()).begin(timeout_seconds=3600)

    grant = await attempts.wait_before_retry(
        reason=_claude_reason(CLAUDE_WEEKLY_LIMIT), work_done=False
    )

    assert grant is None
    assert clock.slept == []


def _claude_error_result(result_text: str) -> str:
    """One raw claude terminal line: an ``is_error`` result carrying ``result_text``."""
    return json.dumps({"type": "result", "is_error": True, "result": result_text})


def _anthropic_body(error_type: str, message: str) -> str:
    return json.dumps({"type": "error", "error": {"type": error_type, "message": message}})


#: Every shape the claude parser accepts the weekly-limit sentence in. The
#: structured ones used to lose the sentence to the "Rate limited (HTTP 429)"
#: label, which reads as a retryable rate limit (#1882, verify finding 4).
_WEEKLY_LIMIT_SHAPES = {
    "plain stored text": CLAUDE_WEEKLY_LIMIT,
    "plain, with surrounding whitespace": f"\n  {CLAUDE_WEEKLY_LIMIT}  \n",
    "structured HTTP 429": f"API Error: 429 {_anthropic_body('rate_limit_error', CLAUDE_WEEKLY_LIMIT)}",
    "structured, no status": _anthropic_body("rate_limit_error", CLAUDE_WEEKLY_LIMIT),
}


@pytest.mark.parametrize("result_text", _WEEKLY_LIMIT_SHAPES.values(), ids=_WEEKLY_LIMIT_SHAPES)
def test_every_shape_of_the_weekly_limit_reads_as_quota(result_text: str) -> None:
    assert UPSTREAM_FAILURES.kind_of(_claude_reason(result_text)) is UpstreamFailureKind.QUOTA


@pytest.mark.parametrize("result_text", _WEEKLY_LIMIT_SHAPES.values(), ids=_WEEKLY_LIMIT_SHAPES)
async def test_the_weekly_limit_through_the_raw_stream_launches_once(result_text: str) -> None:
    handler = await _run_claude(_claude(_claude_error_result(result_text)))

    assert len(handler.granted_timeouts) == 1, (
        f"{len(handler.granted_timeouts)} launches: a spent quota was retried"
    )


async def test_a_structured_rate_limit_without_quota_words_is_still_retried() -> None:
    """The control: the quota case is not passing because nothing is retried."""
    raw = f"API Error: 429 {_anthropic_body('rate_limit_error', 'Rate limit exceeded')}"

    handler = await _run_claude(_claude(_claude_error_result(raw)))

    assert UPSTREAM_FAILURES.kind_of(_claude_reason(raw)) is UpstreamFailureKind.RATE_LIMITED
    assert len(handler.granted_timeouts) == UpstreamRetryPolicy().max_attempts
