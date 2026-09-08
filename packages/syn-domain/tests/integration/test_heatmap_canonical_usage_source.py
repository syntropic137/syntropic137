"""The heatmap must report a session's REAL output tokens, not the CLI placeholder.

Claude Code's per-assistant-message ``usage.output_tokens`` is a PLACEHOLDER.
Only the stream's terminating ``result`` event carries authoritative totals,
and ``ObservabilityCollector`` writes those to ``session_summary`` - never
back into the per-turn ``token_usage`` rows.

``TimescaleHeatmapQuery`` read ``token_usage`` and nothing else, so it priced
the placeholder. Every other cost consumer (``execution_cost``,
``session_cost``) already prefers ``session_summary``; the heatmap was the
one query that did not, which is why the dashboard showed 9.9M tokens and
$5.71 beside 9,151,116 and $6.2711 for the same reality.

FIXTURE PROVENANCE: every literal below is copied from a real stored
transcript - session a49345da-0219-48b8-8a57-956a388115be, recovered from
the syn-conversations bucket. Its two assistant messages report
``output_tokens`` 4 and 1; the result event reports 13300, and that same
result event's ``iterations`` block shows one of those "1 output token"
messages actually produced 767. The placeholder is not a rounding error.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest

from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# --- Real values from session a49345da (see FIXTURE PROVENANCE above) ---
_MODEL = "haiku"
_PLACEHOLDER_OUTPUT_PER_TURN = (4, 1)
"""What the per-message usage blocks claimed. Sums to 5."""

_TRUE_OUTPUT_TOKENS = 13_300
"""What the result event reported, and what the session actually produced."""

_TURN_INPUT = (10, 8)
_TURN_CACHE_CREATION = (3_239, 12_570)
_TURN_CACHE_READ = (27_470, 30_709)

_TRUE_INPUT_TOKENS = sum(_TURN_INPUT)  # 18
_TRUE_CACHE_CREATION = sum(_TURN_CACHE_CREATION)  # 15_809
_TRUE_CACHE_READ = sum(_TURN_CACHE_READ)  # 58_179

_VENDOR_COST_USD = 0.09439815
"""``total_cost_usd`` as the Claude CLI itself reported it for this session."""


@pytest.fixture
async def event_store(test_infrastructure):
    from syn_adapters.events import AgentEventStore

    store = AgentEventStore(test_infrastructure.timescaledb_url)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def execution_id() -> str:
    return str(uuid4())


_MIDDAY = time(12, 0, tzinfo=UTC)
"""Where an anchored observation lands, leaving room either side of it.

Midnight would not: an event placed a second earlier belongs to the previous
day, which is the whole failure this module had.
"""


@pytest.fixture
def utc_day() -> date:
    """The one UTC date a test writes on, queries for, and asserts about.

    Observations are stored in UTC while ``date.today()`` is LOCAL, and the
    heatmap buckets by the UTC day, so the test must ask the UTC question.

    Read ONCE per test, and every other date derives from this value. Reading
    the clock a second time - to place an observation, to build the window, or
    to find the bucket - lets a run that crosses midnight get a different
    answer from each read (#1001): the rows land on one day, the query asks
    for another, and the assertion reads ``0.0 == 13300``, indistinguishable
    from the production query returning nothing.

    The clock is still read, so the tests still price a real session on the
    real current day; it is read once, so no boundary can fall between two
    halves of the same assertion.
    """
    return datetime.now(UTC).date()


async def _record_observation_on(
    store,
    day: date,
    session_id: str,
    execution_id: str,
    observation_type: str,
    data: dict[str, object],
    *,
    seconds_past_midday: int = 0,
) -> None:
    """Write one observation at midday on ``day``, through the production writer.

    ``record_observation`` stamps ``datetime.now()`` and offers no way to say
    otherwise, so it is the wall-clock read that decides which day a row lands
    on. ``insert_one`` is that same write path one layer down - it is what
    ``record_observation`` calls, with the same validation and the same INSERT
    - and it takes the timestamp from the caller, so anchoring costs no
    fidelity.

    These timestamps are in the FUTURE whenever the suite runs before midday,
    and that is fine: nothing under test rejects ``time > now()``. Ranking
    orders by untruncated ``time DESC`` and the heatmap buckets by date, so
    only date membership and relative order matter. Fear of future timestamps
    is what made the first fix (#1000) narrow the window instead of closing it.
    """
    await store.insert_one(
        event={
            "event_type": observation_type,
            "session_id": session_id,
            "timestamp": datetime.combine(day, _MIDDAY) + timedelta(seconds=seconds_past_midday),
            **data,
        },
        execution_id=execution_id,
    )


async def _record_real_session(store, day: date, session_id: str, execution_id: str) -> None:
    """Write the observations a real Claude session leaves behind, all on ``day``.

    Both lanes, exactly as production writes them: per-turn ``token_usage``
    rows carrying the placeholder output, then one ``session_summary``
    carrying the authoritative totals from the result event.
    """
    for i in range(2):
        await _record_observation_on(
            store,
            day,
            session_id,
            execution_id,
            TOKEN_USAGE,
            {
                "input_tokens": _TURN_INPUT[i],
                "output_tokens": _PLACEHOLDER_OUTPUT_PER_TURN[i],
                "cache_creation_tokens": _TURN_CACHE_CREATION[i],
                "cache_read_tokens": _TURN_CACHE_READ[i],
                "model": _MODEL,
            },
            seconds_past_midday=i,
        )

    await _record_observation_on(
        store,
        day,
        session_id,
        execution_id,
        SESSION_SUMMARY,
        {
            "total_input_tokens": _TRUE_INPUT_TOKENS,
            "total_output_tokens": _TRUE_OUTPUT_TOKENS,
            "cache_creation_tokens": _TRUE_CACHE_CREATION,
            "cache_read_tokens": _TRUE_CACHE_READ,
            "total_cost_usd": _VENDOR_COST_USD,
            "num_turns": 2,
            "duration_ms": 163_208,
            "model": _MODEL,
        },
        seconds_past_midday=2,
    )


def _bucket_for_date(buckets, day: date):
    """The bucket for ``day`` - the date the caller already chose, not today's.

    Taking the date as an argument is what keeps the assertion on the same day
    the observations were written to (#1001).
    """
    wanted = day.isoformat()
    match = [b for b in buckets if b.date == wanted]
    assert match, f"no bucket for {wanted}"
    return match[0]


class TestHeatmapReadsAuthoritativeOutput:
    async def test_reports_result_event_output_not_per_turn_placeholder(
        self, event_store, execution_id, utc_day
    ):
        """The bug: heatmap summed the placeholders and reported 5 instead of 13,300."""
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await _record_real_session(event_store, utc_day, session_id, execution_id)

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=utc_day,
            end=utc_day,
            execution_ids={execution_id},
        )

        assert _bucket_for_date(buckets, utc_day).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS

    async def test_does_not_double_count_output_across_both_lanes(
        self, event_store, execution_id, utc_day
    ):
        """Reading summary must REPLACE the per-turn rows, not add to them.

        Guards the obvious wrong fix: unioning the two sources would report
        13,305 - the authoritative total plus the placeholders it supersedes.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await _record_real_session(event_store, utc_day, session_id, execution_id)

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=utc_day,
            end=utc_day,
            execution_ids={execution_id},
        )

        breakdown = _bucket_for_date(buckets, utc_day).breakdown
        assert breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS
        assert breakdown["input_tokens"] == _TRUE_INPUT_TOKENS
        assert breakdown["cache_read_tokens"] == _TRUE_CACHE_READ
        assert breakdown["cache_creation_tokens"] == _TRUE_CACHE_CREATION

    async def test_falls_back_to_token_usage_while_session_still_running(
        self, event_store, execution_id, utc_day
    ):
        """A session with no summary yet must still appear, priced from what it has.

        Mid-flight sessions are the reason token_usage exists. Preferring the
        summary must not make in-progress work invisible.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await _record_observation_on(
            event_store,
            utc_day,
            session_id,
            execution_id,
            TOKEN_USAGE,
            {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "model": _MODEL,
            },
        )

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=utc_day,
            end=utc_day,
            execution_ids={execution_id},
        )

        breakdown = _bucket_for_date(buckets, utc_day).breakdown
        assert breakdown["output_tokens"] == 50
        assert breakdown["input_tokens"] == 100


class TestHeatmapPrefersVendorReportedCost:
    async def test_uses_the_cli_reported_cost_not_a_recomputation(
        self, event_store, execution_id, utc_day
    ):
        """The vendor's own number wins when the harness reported one.

        Claude Code reports ``total_cost_usd`` per session; Codex does not, so
        its cost is computed from tokens. Recomputing BOTH would discard the
        billing truth we were given, and using the summary's tokens while
        ignoring its cost is how the heatmap and the metrics card ended up
        quoting different dollars for the same sessions.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await _record_real_session(event_store, utc_day, session_id, execution_id)

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(start=utc_day, end=utc_day, execution_ids={execution_id})

        assert _bucket_for_date(buckets, utc_day).breakdown["cost_usd"] == pytest.approx(
            _VENDOR_COST_USD, abs=1e-4
        )

    async def test_computes_cost_when_the_harness_reported_none(
        self, event_store, execution_id, utc_day
    ):
        """Codex reports no cost of its own, so its tokens must still be priced.

        A summary with a NULL cost previously had no path to a dollar figure:
        preferring the vendor number without a fallback would silently price
        every codex session at zero.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await _record_observation_on(
            event_store,
            utc_day,
            session_id,
            execution_id,
            SESSION_SUMMARY,
            {
                "total_input_tokens": 1_000_000,
                "total_output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "total_cost_usd": None,
                "model": "claude-opus-4-20250514",
                "num_turns": 1,
            },
        )

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(start=utc_day, end=utc_day, execution_ids={execution_id})

        breakdown = _bucket_for_date(buckets, utc_day).breakdown
        assert breakdown["cost_usd"] > 0.0
        assert breakdown["unpriced_tokens"] == 0.0


class TestEmptySummaryDoesNotEraseRealUsage:
    async def test_all_zero_summary_falls_back_to_the_turn_rows(
        self, event_store, execution_id, utc_day
    ):
        """A summary of zeroes is an ABSENCE of usage, not a measurement of none.

        Found on live data: two sessions carry a session_summary whose four
        token fields are all 0 while their token_usage rows hold real work.
        The cause is upstream - AgentExecutionHandler resolves the aggregate's
        totals with a per-field ``result_x or accumulated_x`` fallback but
        writes the summary from the RAW result fields, so a run that produced
        no result event records the accumulator in Lane 1 and zeroes in Lane 2.

        Letting that summary supersede the turn rows reports the session as
        free, which is the silently-cheap failure this whole change exists to
        remove. Superseding requires the summary to actually carry usage.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await _record_observation_on(
            event_store,
            utc_day,
            session_id,
            execution_id,
            TOKEN_USAGE,
            {
                "input_tokens": 18,
                "output_tokens": 5,
                "cache_creation_tokens": 4_521,
                "cache_read_tokens": 58_654,
                "model": _MODEL,
            },
        )
        await _record_observation_on(
            event_store,
            utc_day,
            session_id,
            execution_id,
            SESSION_SUMMARY,
            {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "total_cost_usd": None,
                "model": _MODEL,
            },
        )

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(start=utc_day, end=utc_day, execution_ids={execution_id})

        breakdown = _bucket_for_date(buckets, utc_day).breakdown
        assert breakdown["cache_read_tokens"] == 58_654
        assert breakdown["input_tokens"] == 18
        assert breakdown["tokens"] == 63_198


class TestOneSummaryPerSession:
    async def test_two_summaries_do_not_add_together(self, event_store, execution_id, utc_day):
        """ "Supersedes" must mean CHOOSE one, not SUM them.

        The rule says a session's summary replaces its turn rows. The SQL
        grouped by (session_id, model, cost-nullness) and summed, so a session
        carrying two summaries contributed both - doubling its tokens and its
        cost. Splitting on model or cost-nullness makes them separate rows,
        which hides the duplication rather than preventing it.

        Real shapes that produce a second summary: a retried phase reusing a
        session id, and a resumed run re-emitting its totals.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        for seconds in range(2):
            await _record_observation_on(
                event_store,
                utc_day,
                session_id,
                execution_id,
                SESSION_SUMMARY,
                {
                    "total_input_tokens": 18,
                    "total_output_tokens": 13_300,
                    "cache_creation_tokens": 15_809,
                    "cache_read_tokens": 58_179,
                    "total_cost_usd": _VENDOR_COST_USD,
                    "model": _MODEL,
                },
                seconds_past_midday=seconds,
            )

        buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=utc_day, end=utc_day, execution_ids={execution_id}
        )
        breakdown = _bucket_for_date(buckets, utc_day).breakdown

        assert breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS
        assert breakdown["cost_usd"] == pytest.approx(_VENDOR_COST_USD, abs=1e-4)

    async def test_differing_models_across_summaries_still_yield_one(
        self, event_store, execution_id, utc_day
    ):
        """Grouping by model must not turn a duplicate into two legitimate rows."""
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        for seconds, (model, cost) in enumerate(
            ((_MODEL, _VENDOR_COST_USD), ("claude-sonnet-5", None))
        ):
            await _record_observation_on(
                event_store,
                utc_day,
                session_id,
                execution_id,
                SESSION_SUMMARY,
                {
                    "total_input_tokens": 18,
                    "total_output_tokens": 13_300,
                    "cache_creation_tokens": 15_809,
                    "cache_read_tokens": 58_179,
                    "total_cost_usd": cost,
                    "model": model,
                },
                seconds_past_midday=seconds,
            )

        buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=utc_day, end=utc_day, execution_ids={execution_id}
        )
        assert _bucket_for_date(buckets, utc_day).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS

    async def test_a_newer_corrected_summary_beats_an_older_larger_one(
        self, event_store, execution_id, utc_day
    ):
        """Recency decides among usable summaries - not size.

        The rank ordered by total token count DESC, so a correction that
        REDUCES a session's totals could never win: the stale, larger row
        outranked it forever. "Prefer a summary that carries usage, then the
        most recent" is the rule; ordering by magnitude is a different rule
        that agrees with it only when corrections happen to grow.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        # The larger summary is written FIRST, so only recency can pick the
        # smaller one that follows it a second later.
        for seconds, output in ((0, 99_999), (1, _TRUE_OUTPUT_TOKENS)):
            await _record_observation_on(
                event_store,
                utc_day,
                session_id,
                execution_id,
                SESSION_SUMMARY,
                {
                    "total_input_tokens": 18,
                    "total_output_tokens": output,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_cost_usd": _VENDOR_COST_USD,
                    "model": _MODEL,
                },
                seconds_past_midday=seconds,
            )

        buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=utc_day, end=utc_day, execution_ids={execution_id}
        )
        assert _bucket_for_date(buckets, utc_day).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS


class TestSessionsStraddlingTheWindow:
    async def test_summary_after_the_window_still_supersedes_turn_rows(
        self, event_store, execution_id, utc_day
    ):
        """A session's authoritative record must be found even if it lands late.

        scoped_events filters observations by the requested window BEFORE the
        canonical CTE runs, so a session that starts inside the window and
        whose summary arrives after it was priced from its placeholder turn
        rows - reporting 5 output tokens for a session that produced 13,300,
        which is the exact bug this module exists to prevent, reintroduced at
        the window edge.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        # Turn rows land on the queried day; the summary lands the day after,
        # outside the window - which is the whole point of the test, and is now
        # stated as a date rather than as an offset from an unrelated clock.
        await _record_observation_on(
            event_store,
            utc_day,
            session_id,
            execution_id,
            TOKEN_USAGE,
            {
                "input_tokens": 18,
                "output_tokens": 5,
                "cache_creation_tokens": 15_809,
                "cache_read_tokens": 58_179,
                "model": _MODEL,
            },
        )
        await _record_observation_on(
            event_store,
            utc_day + timedelta(days=1),
            session_id,
            execution_id,
            SESSION_SUMMARY,
            {
                "total_input_tokens": 18,
                "total_output_tokens": _TRUE_OUTPUT_TOKENS,
                "cache_creation_tokens": 15_809,
                "cache_read_tokens": 58_179,
                "total_cost_usd": _VENDOR_COST_USD,
                "model": _MODEL,
            },
        )

        buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=utc_day, end=utc_day, execution_ids={execution_id}
        )

        assert _bucket_for_date(buckets, utc_day).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS
