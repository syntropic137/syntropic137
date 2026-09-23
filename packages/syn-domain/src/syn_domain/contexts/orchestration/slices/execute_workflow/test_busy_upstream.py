"""What `UpstreamRetryPolicy` decides, and how long it waits to decide it (#1303).

The outcomes this produces are pinned where they are produced, against the real
processor, in
`packages/syn-domain/tests/contexts/workflows/execute_workflow/test_1303_a_busy_upstream_is_not_a_failed_run.py`.
What is here instead is the arithmetic that test deliberately switches off so
it does not sleep: which reasons qualify, the bound, the backoff, and the one
deadline all of it is spent from. Nobody watching a run can tell 5s from 50s
from 0s, so if the schedule is not asserted it is not specified.

THE CLASSIFICATION HALF IS MOSTLY NEGATIVE ON PURPOSE. The rule is exact-match
against the fixed strings the stream processors normalise a busy upstream into,
and the whole value of "exact" is what it REFUSES. `TestASignatureInsideOther
Prose` is that: every fragment the old substring list matched on, embedded in a
quota notice, a billing message, an authentication failure, an invalid-request
error and an agent's own prose. Each one used to buy three full phase
executions against a condition no wait can clear.
"""

from __future__ import annotations

import itertools

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    _MIN_USEFUL_ATTEMPT_SECONDS,
    PhaseAttempts,
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    api_error_label,
)
from syn_domain.testing.fake_clock import FakeClock

# CI selects with `pytest -m unit`; without this the whole module is collected
# by no job and can fail on main behind a green check (#825).
pytestmark = pytest.mark.unit

#: Spelled by asking the same functions production asks. A literal here would
#: pass this file and still miss the real string the day either side reworded.
AT_CAPACITY = codex_fault_reason("Selected model is at capacity. Please try a different model.")
OVERLOADED = api_error_label(ApiErrorType.OVERLOADED, "529")
RATE_LIMITED = api_error_label(ApiErrorType.RATE_LIMIT, "429")

#: Long enough that no case here is decided by the deadline. The deadline has
#: its own class below.
ROOMY = 3600.0


def _begin(
    *, timeout_seconds: float = ROOMY, oversleeps_by: float = 0.0
) -> tuple[PhaseAttempts, FakeClock]:
    """A phase's attempts, on a clock the test owns, at production's bound.

    ``oversleeps_by`` is how much longer than asked each backoff really takes -
    see `FakeClock`. Zero is a clock that keeps its word, which no real one
    promises to.
    """
    clock = FakeClock(oversleeps_by=oversleeps_by)
    policy = UpstreamRetryPolicy(clock=clock.as_attempt_clock())
    return policy.begin(timeout_seconds=timeout_seconds), clock


#: The least time an attempt may be given and still be worth starting, as
#: `busy_upstream` defines it. Read from the module rather than written as 30
#: so these boundary cases stay boundary cases if the floor is ever retuned.
MIN_USEFUL = _MIN_USEFUL_ATTEMPT_SECONDS

#: What the first backoff costs, which is what a pre-sleep check has to forecast.
FIRST_BACKOFF = UpstreamRetryPolicy().base_delay_seconds


class TestTheBackoff:
    async def test_it_waits_longer_each_time(self) -> None:
        """Doubling, from the first retry. A fixed delay retried into a queue
        that has not drained is three requests at the same bad moment."""
        attempts, clock = _begin()

        assert await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)
        assert await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)

        assert clock.slept == [5.0, 10.0]

    async def test_the_attempt_that_will_not_be_retried_does_not_wait(self) -> None:
        """The wait buys a later attempt. With no later attempt it buys
        nothing, and charges the execution for it anyway."""
        spent, clock = _begin()
        assert await spent.wait_before_retry(reason=AT_CAPACITY, work_done=False)
        assert await spent.wait_before_retry(reason=AT_CAPACITY, work_done=False)
        clock.slept.clear()

        assert not await spent.wait_before_retry(reason=AT_CAPACITY, work_done=False)

        permanent, other_clock = _begin()
        assert not await permanent.wait_before_retry(
            reason=api_error_label(ApiErrorType.AUTHENTICATION), work_done=False
        )

        assert clock.slept == []
        assert other_clock.slept == []


class TestWhatCountsAsBusy:
    """The list is closed, and matched IN FULL. Everything on it is an upstream
    talking about ITSELF, in the exact words the stream processors give it."""

    @pytest.mark.parametrize(
        "reason",
        [
            AT_CAPACITY,
            OVERLOADED,
            RATE_LIMITED,
            # The same two faults when the provider sent no HTTP status with
            # them: `_format_anthropic_error` then reports the bare label.
            api_error_label(ApiErrorType.OVERLOADED),
            api_error_label(ApiErrorType.RATE_LIMIT),
        ],
    )
    async def test_busy(self, reason: str) -> None:
        attempts, _ = _begin()
        assert await attempts.wait_before_retry(reason=reason, work_done=False)

    @pytest.mark.parametrize(
        "reason",
        [
            None,
            "",
            codex_fault_reason("You are not logged in. Run `codex login` to continue."),
            api_error_label(ApiErrorType.AUTHENTICATION, "401"),
            api_error_label(ApiErrorType.INVALID_REQUEST, "400"),
            codex_fault_reason("This content was flagged for possible cybersecurity risk"),
            "codex stream ended without a terminal turn.completed event",
            # A 5xx is deliberately absent from the list: it may be a blip and
            # it may be a persistent rejection, and the message cannot say
            # which. See the module docstring.
            api_error_label(ApiErrorType.API, "500"),
        ],
    )
    async def test_not_busy(self, reason: str | None) -> None:
        attempts, _ = _begin()
        assert not await attempts.wait_before_retry(reason=reason, work_done=False)


class TestASignatureInsideOtherProse:
    """Every fragment the old substring list matched on, in a message where
    waiting changes nothing.

    This is the half the previous rule got wrong, and it got it wrong in the
    expensive direction: a quota that resets next month, a card that was
    declined, a login that is not valid and a malformed parameter each bought
    three full phase executions and arrived at the identical message. The
    ones an AGENT can write are worse still - a phase whose own output quotes
    "rate limit" could make itself retryable by saying so.
    """

    @pytest.mark.parametrize(
        ("what", "reason"),
        [
            (
                "a quota, which resets on a calendar and not on a backoff",
                "Rate limit reached; quota resets next month",
            ),
            (
                "a quota, spelled the way the raw API type spells it",
                "You have exceeded your monthly quota (rate_limit_error)",
            ),
            (
                "billing, which a wait cannot pay",
                "Your credit balance is too low. Rate limited until payment is received.",
            ),
            (
                "authentication, which will be invalid again in five seconds",
                "Authentication failed: this key is rate limited to zero requests",
            ),
            (
                "an invalid request, which is a statement about the request",
                "Invalid request: rate_limit must be positive",
            ),
            (
                "an invalid request naming the overload type as a value",
                'Invalid request: error.type must be one of ["overloaded_error"]',
            ),
            (
                "the agent's own prose, which the harness forwards verbatim",
                codex_fault_reason(
                    "I could not finish: the API docs say the model is at capacity "
                    "under load, so I added a retry to the client."
                ),
            ),
            (
                "the agent quoting the very sentence that would qualify",
                codex_fault_reason(
                    'The test asserts on "Selected model is at capacity. Please try a '
                    'different model." and that assertion failed.'
                ),
            ),
            (
                "a permanent account state that happens to say 'at capacity'",
                "Organization is at capacity for this plan; upgrade to add seats",
            ),
        ],
    )
    async def test_it_is_not_a_busy_upstream(self, what: str, reason: str) -> None:
        attempts, clock = _begin()

        assert not await attempts.wait_before_retry(reason=reason, work_done=False), (
            f"Retried {what}. Three attempts, the same answer, three times the bill."
        )
        assert clock.slept == []


class TestTheOneDeadline:
    """A phase's timeout is spent ONCE, across every attempt and every backoff.

    It used to be spent per attempt: three attempts at a 3600-second phase were
    three fresh 3600-second clocks, so a phase that could not exceed an hour
    could run for three and bill for three.
    """

    async def test_the_backoff_comes_out_of_the_phase_budget(self) -> None:
        """Not added on top of it. The wait is time the phase does not get."""
        attempts, clock = _begin(timeout_seconds=ROOMY)
        started_with = attempts.seconds_left

        await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)

        assert clock.slept == [5.0]
        assert attempts.seconds_left == started_with - 5.0

    async def test_an_attempt_gets_what_is_left_not_what_the_phase_started_with(
        self,
    ) -> None:
        attempts, clock = _begin(timeout_seconds=1000.0)

        clock.advance(600.0)

        assert attempts.seconds_left == 400.0

    async def test_a_budget_that_cannot_fund_another_attempt_ends_it(self) -> None:
        """Attempts remain and the upstream is genuinely busy - and it still
        stops, because there is no time to run one in.

        The attempt is worth starting or it is not; one second of it is not a
        smaller attempt but a container launch that gets killed during setup
        and reports a timeout where the upstream's own reason used to be.
        """
        attempts, clock = _begin(timeout_seconds=1000.0)
        clock.advance(999.0)

        assert attempts.attempt < attempts.max_attempts, "the bound is not what stopped it"
        assert not await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)
        assert clock.slept == [], "waited out a backoff it had already decided not to use"

    async def test_the_deadline_never_moves(self) -> None:
        """Across everything: attempts running, backoffs served, the lot.

        Three attempts and two backoffs on a 1000-second phase must land inside
        1000 seconds. Under a per-attempt timeout the same sequence reached
        3015.
        """
        attempts, clock = _begin(timeout_seconds=1000.0)
        granted: list[float] = []

        while True:
            granted.append(attempts.seconds_left)
            # Each attempt spends 400s of what it was granted, or all of it if
            # that is less. Spending a FIXED amount would let a budget that
            # silently reset still land inside 1000, which is the whole defect.
            clock.advance(min(400.0, attempts.seconds_left))
            if not await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False):
                break

        assert len(granted) > 1, "never retried at all - the test proves nothing"
        assert clock.now <= 1000.0, (
            f"{clock.now}s spent against a 1000s phase timeout: the deadline moved"
        )
        assert all(later < earlier for earlier, later in itertools.pairwise(granted)), (
            f"an attempt got at least as much time as the one before it: {granted}"
        )


class TestAnAttemptThatGotSomewhere:
    """Retrying re-runs the ORIGINAL prompt in the SAME workspace, so it is only
    safe while the attempt it replaces did nothing. What "did nothing" means is
    decided in `agent_attempts`; that it is obeyed is decided here."""

    async def test_work_already_done_is_not_retried_however_busy_the_upstream_was(
        self,
    ) -> None:
        attempts, clock = _begin()

        assert not await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=True)
        assert clock.slept == []

    async def test_the_same_failure_with_no_work_behind_it_is_retried(self) -> None:
        """The control. Without it the assertion above passes on the reason."""
        attempts, _ = _begin()

        assert await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)


class TestABackoffThatOverslept:
    """The deadline is rechecked AFTER the wait, not only forecast before it.

    `wait_before_retry` used to check affordability, sleep, and then return
    True unconditionally. The check was a forecast of where the clock would be;
    the sleep is what actually moved it, and `sleep(delay)` does not promise to
    return after `delay` - a suspended host, a busy loop or a descheduled
    container can come back arbitrarily late.

    When that happened the caller had already been told to go again, and was
    handed `int(seconds_left)` for the attempt. Past the deadline that is 0,
    and the workspace provider reads a falsey timeout as NO TIMEOUT
    (`if not timeout_seconds: return False` in `providers/base.py`). So an
    overslept backoff did not merely waste the rest of the budget - it removed
    the bound the budget existed to impose, and the hard phase timeout an
    operator configured stopped applying at all.
    """

    async def test_a_sleep_that_overshoots_the_deadline_dispatches_no_successor(self) -> None:
        """The reproduction from the review, in its own terms: a budget that
        can afford the wait, a wait that takes far longer than it asked for."""
        attempts, clock = _begin(timeout_seconds=40.0, oversleeps_by=45.0)

        assert not await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False), (
            "the backoff came back past the deadline and another attempt was launched anyway"
        )
        assert clock.slept == [FIRST_BACKOFF], "it did not get as far as sleeping"
        assert attempts.seconds_left == 0.0

    async def test_a_backoff_leaving_exactly_the_minimum_still_retries(self) -> None:
        """The boundary from the affordable side, and the control for the two
        below: they must fail on the shortfall, not on the recheck existing."""
        attempts, clock = _begin(timeout_seconds=MIN_USEFUL + FIRST_BACKOFF)

        assert await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)
        assert attempts.seconds_left == MIN_USEFUL
        assert clock.now == FIRST_BACKOFF

    async def test_a_backoff_leaving_just_under_the_minimum_does_not(self) -> None:
        """Half a second short. Before the recheck this was indistinguishable
        from the case above, because only the forecast was ever consulted and
        the forecast said 30."""
        attempts, _ = _begin(timeout_seconds=MIN_USEFUL + FIRST_BACKOFF, oversleeps_by=0.5)

        assert not await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)

    async def test_a_backoff_leaving_exactly_zero_does_not(self) -> None:
        """The value that matters most, because it is not a short attempt.

        Zero is what `int(seconds_left)` truncates to at the deadline and what
        the provider reads as unbounded.
        """
        attempts, _ = _begin(timeout_seconds=MIN_USEFUL + FIRST_BACKOFF, oversleeps_by=MIN_USEFUL)

        assert not await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)
        assert attempts.seconds_left == 0.0

    async def test_an_overshoot_past_an_hour_long_deadline_does_not(self) -> None:
        """At the largest phase timeout the platform configures.

        The arithmetic is otherwise correct at this size - that is pinned in
        `TestTheOneDeadline` - so what fails here is only the oversleep, and it
        fails by more than an hour.
        """
        attempts, clock = _begin(timeout_seconds=3600.0, oversleeps_by=3600.0)
        clock.advance(3600.0 - MIN_USEFUL - FIRST_BACKOFF)

        assert not await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)
        assert clock.now > 3600.0, "the clock did not actually overshoot - test proves nothing"

    async def test_the_timeout_handed_to_an_attempt_is_never_zero(self) -> None:
        """Whatever the clock has done, and however far past the deadline.

        `seconds_left` may legitimately be 0.0 - it is a remaining budget. The
        number the handler is given may not be, because downstream 0 does not
        mean "no time" but "no limit". This is the floor that makes that
        impossible rather than merely unlikely.
        """
        attempts, clock = _begin(timeout_seconds=100.0)
        clock.advance(500.0)

        assert attempts.seconds_left == 0.0
        assert attempts.first_attempt().timeout_seconds >= 1, (
            "an attempt would have been dispatched with a falsey timeout, which the "
            "workspace provider reads as no timeout at all"
        )


class TestTheGrantCarriesTheBudgetThatWasChecked:
    """The approval and the number are produced by ONE reading of the clock.

    Rechecking the deadline after the backoff closed half the hole. The other
    half was the hop after it: the decision said "go again", and the caller
    then read `seconds_left` for ITSELF at the dispatch line and truncated it.
    Two readings, and the clock moves between any two readings - so a budget
    that passed the recheck at exactly 30s could be dispatched at 0s, floored
    to a meaningless 1s, with the recheck having prevented nothing.

    `FakeClock(drifts_per_reading=...)` is what makes that assertable: every
    reading of the clock costs time, exactly as every reading of a real one
    does. What is asserted is that the handler's number comes from the reading
    that was JUDGED, not from whatever the clock said later.
    """

    async def test_the_granted_timeout_is_the_checked_budget_not_a_later_reading(
        self,
    ) -> None:
        """A drift that would carry the next reading to the deadline exactly.

        The post-backoff check sees 30s and approves. One reading later the
        budget is 0. The grant must be the 30 that was approved: reading again
        at dispatch is what produced the falsey timeout this whole class is
        about.
        """
        clock = FakeClock(drifts_per_reading=MIN_USEFUL)
        policy = UpstreamRetryPolicy(base_delay_seconds=0.0, clock=clock.as_attempt_clock())
        # Three readings precede the post-backoff one (construction, the first
        # attempt's grant, the pre-backoff forecast), so 4 * MIN_USEFUL leaves
        # the check looking at exactly MIN_USEFUL.
        attempts = policy.begin(timeout_seconds=MIN_USEFUL * 4)
        assert attempts.first_attempt().timeout_seconds == MIN_USEFUL * 3

        grant = await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)

        assert grant is not None, "the budget was affordable at the moment it was checked"
        assert grant.timeout_seconds == int(MIN_USEFUL), (
            f"{grant.timeout_seconds}s: the grant was denominated by a reading taken "
            "after the one that approved it, and by then the deadline had passed"
        )
        assert attempts.seconds_left == 0.0, "the clock did not drift - the test proves nothing"

    @pytest.mark.parametrize("drift", [0.0, 0.5, 7.0, MIN_USEFUL, 200.0, 400.0])
    async def test_no_grant_is_ever_below_the_minimum_useful_budget(self, drift: float) -> None:
        """The invariant, across drifts that do and do not outrun the deadline.

        A grant that exists is a grant that was affordable. There is no
        drift - none - that produces a successor bounded by less than the
        minimum, because no second reading of the clock is ever consulted.
        """
        clock = FakeClock(drifts_per_reading=drift)
        policy = UpstreamRetryPolicy(base_delay_seconds=0.0, clock=clock.as_attempt_clock())
        attempts = policy.begin(timeout_seconds=1000.0)
        granted: list[int] = []

        while True:
            grant = await attempts.wait_before_retry(reason=AT_CAPACITY, work_done=False)
            if grant is None:
                break
            granted.append(grant.timeout_seconds)

        assert granted, f"drift={drift}: nothing was granted at all - the invariant is vacuous"
        assert all(t >= MIN_USEFUL for t in granted), (
            f"{granted}: a successor was granted less than the {MIN_USEFUL}s minimum"
        )
