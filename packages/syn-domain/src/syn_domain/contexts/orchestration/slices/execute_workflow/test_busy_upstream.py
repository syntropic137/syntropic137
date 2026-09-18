"""What `UpstreamRetryPolicy` decides, and how long it waits to decide it (#1303).

The outcomes this produces are pinned where they are produced, against the real
processor, in
`packages/syn-domain/tests/contexts/workflows/execute_workflow/test_1303_a_busy_upstream_is_not_a_failed_run.py`.
What is here instead is the arithmetic that test deliberately switches off so
it does not sleep: the bound, and the backoff between attempts. Nobody watching
a run can tell 5s from 50s from 0s, so if the schedule is not asserted it is
not specified.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# CI selects with `pytest -m unit`; without this the whole module is collected
# by no job and can fail on main behind a green check (#825).
pytestmark = pytest.mark.unit

AT_CAPACITY = "codex reported: Selected model is at capacity. Please try a different model."


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """Every backoff the policy asks for, in order, without serving any of it."""
    recorded: list[float] = []

    async def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(
        "syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream.asyncio.sleep",
        _record,
    )
    yield recorded


class TestTheBackoff:
    async def test_it_waits_longer_each_time(self, waits: list[float]) -> None:
        """Doubling, from the first retry. A fixed delay retried into a queue
        that has not drained is three requests at the same bad moment."""
        policy = UpstreamRetryPolicy()

        assert await policy.wait_before_retry(reason=AT_CAPACITY, attempt=1)
        assert await policy.wait_before_retry(reason=AT_CAPACITY, attempt=2)

        assert waits == [5.0, 10.0]

    async def test_the_attempt_that_will_not_be_retried_does_not_wait(
        self, waits: list[float]
    ) -> None:
        """The wait buys a later attempt. With no later attempt it buys
        nothing, and charges the execution for it anyway."""
        policy = UpstreamRetryPolicy()

        assert not await policy.wait_before_retry(reason=AT_CAPACITY, attempt=3)
        assert not await policy.wait_before_retry(reason="Authentication failed", attempt=1)

        assert waits == []


class TestWhatCountsAsBusy:
    """The list is closed on purpose: everything on it is an upstream talking
    about ITSELF. A statement about the request will say the same thing next
    time, having charged for the trip."""

    @pytest.mark.parametrize(
        "reason",
        [
            "codex reported: Selected model is at capacity. Please try a different model.",
            "API overloaded (HTTP 529)",
            "Rate limited (HTTP 429)",
            'API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}',
        ],
    )
    async def test_busy(self, reason: str, waits: list[float]) -> None:
        assert await UpstreamRetryPolicy().wait_before_retry(reason=reason, attempt=1)

    @pytest.mark.parametrize(
        "reason",
        [
            None,
            "",
            "codex reported: You are not logged in. Run `codex login` to continue.",
            "Authentication failed (HTTP 401)",
            "Invalid request (HTTP 400)",
            "codex reported: This content was flagged for possible cybersecurity risk",
            "codex stream ended without a terminal turn.completed event",
            # A 5xx is deliberately absent from the list: it may be a blip and
            # it may be a persistent rejection, and the message cannot say
            # which. See the module docstring.
            "API internal error (HTTP 500)",
        ],
    )
    async def test_not_busy(self, reason: str | None, waits: list[float]) -> None:
        assert not await UpstreamRetryPolicy().wait_before_retry(reason=reason, attempt=1)
