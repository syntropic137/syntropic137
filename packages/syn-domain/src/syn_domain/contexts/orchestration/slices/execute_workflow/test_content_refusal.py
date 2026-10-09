"""A provider's content-filter refusal is its own kind, and hands over to the fallback.

The codex sentence is the one real refusal in this repo, read from
`tests/fixtures/codex/codex_turn_failed.jsonl` rather than retyped, so the
test pins what codex actually wrote. No claude refusal output exists in this
repo, agentic-workspace or any fixture, so none is pinned here and claude
refusal text reads as UNKNOWN.
"""

from __future__ import annotations

import json
from pathlib import Path

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

_FIXTURE = (
    Path(__file__).parents[6] / "tests" / "fixtures" / "codex" / "codex_turn_failed.jsonl"
)


def _codex_refusal() -> str:
    for line in _FIXTURE.read_text().splitlines():
        event = json.loads(line)
        if event["type"] == "turn.failed":
            return str(event["error"]["message"])
    raise AssertionError(f"no turn.failed in {_FIXTURE}")


CODEX_REFUSAL = _codex_refusal()


def test_the_observed_codex_refusal_reads_as_refusal() -> None:
    assert "flagged for possible cybersecurity risk" in CODEX_REFUSAL
    reason = codex_fault_reason(CODEX_REFUSAL)

    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.REFUSAL
    assert UPSTREAM_FAILURES.quota_of(reason) is None


@pytest.mark.parametrize(
    "reason",
    [
        # An agent quoting codex in its own words is not codex's fault line.
        f"agent wrote: {CODEX_REFUSAL}",
        f"API Error: {CODEX_REFUSAL}",
    ],
)
def test_refusal_words_outside_a_codex_fault_line_are_not_refusal(reason: str) -> None:
    assert UPSTREAM_FAILURES.kind_of(reason) is UpstreamFailureKind.UNKNOWN


def test_refusal_is_neither_transient_nor_an_operator_fault() -> None:
    assert not UpstreamFailureKind.REFUSAL.is_transient
    assert not UpstreamFailureKind.REFUSAL.needs_operator
    assert "not retried" in UpstreamFailureKind.REFUSAL.account()


async def test_a_refusal_is_never_retried_on_the_same_agent() -> None:
    clock = FakeClock()
    attempts = UpstreamRetryPolicy(clock=clock.as_attempt_clock()).begin(timeout_seconds=3600)

    grant = await attempts.wait_before_retry(
        reason=codex_fault_reason(CODEX_REFUSAL), work_done=False
    )

    assert grant is None
    assert clock.slept == []


def test_a_refusal_before_any_work_is_granted_the_fallback() -> None:
    attempts = UpstreamRetryPolicy(clock=FakeClock().as_attempt_clock()).begin(
        timeout_seconds=3600
    )

    grant = attempts.fallback_attempt(reason=codex_fault_reason(CODEX_REFUSAL), work_done=False)

    assert grant is not None


def test_a_refusal_after_work_is_not_granted_the_fallback() -> None:
    attempts = UpstreamRetryPolicy(clock=FakeClock().as_attempt_clock()).begin(
        timeout_seconds=3600
    )

    grant = attempts.fallback_attempt(reason=codex_fault_reason(CODEX_REFUSAL), work_done=True)

    assert grant is None
