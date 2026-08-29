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

import json
from datetime import UTC, date, datetime
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


async def _record_real_session(store, session_id: str, execution_id: str) -> None:
    """Write the observations a real Claude session leaves behind.

    Both lanes, exactly as production writes them: per-turn ``token_usage``
    rows carrying the placeholder output, then one ``session_summary``
    carrying the authoritative totals from the result event.
    """
    for i in range(2):
        await store.record_observation(
            session_id=session_id,
            observation_type=TOKEN_USAGE,
            data={
                "input_tokens": _TURN_INPUT[i],
                "output_tokens": _PLACEHOLDER_OUTPUT_PER_TURN[i],
                "cache_creation_tokens": _TURN_CACHE_CREATION[i],
                "cache_read_tokens": _TURN_CACHE_READ[i],
                "model": _MODEL,
            },
            execution_id=execution_id,
        )

    await store.record_observation(
        session_id=session_id,
        observation_type=SESSION_SUMMARY,
        data={
            "total_input_tokens": _TRUE_INPUT_TOKENS,
            "total_output_tokens": _TRUE_OUTPUT_TOKENS,
            "cache_creation_tokens": _TRUE_CACHE_CREATION,
            "cache_read_tokens": _TRUE_CACHE_READ,
            "total_cost_usd": _VENDOR_COST_USD,
            "num_turns": 2,
            "duration_ms": 163_208,
            "model": _MODEL,
        },
        execution_id=execution_id,
    )


def _utc_today() -> date:
    """Observations are stored in UTC; date.today() is LOCAL.

    Between local midnight and UTC midnight the two disagree, so a suite that
    passed all afternoon starts failing in the evening. Bucketing is done on
    the UTC day, so the test must ask the same question.
    """
    return datetime.now(UTC).date()


def _bucket_for_today(buckets):
    today = _utc_today().isoformat()
    match = [b for b in buckets if b.date == today]
    assert match, f"no bucket for {today}"
    return match[0]


class TestHeatmapReadsAuthoritativeOutput:
    async def test_reports_result_event_output_not_per_turn_placeholder(
        self, event_store, execution_id
    ):
        """The bug: heatmap summed the placeholders and reported 5 instead of 13,300."""
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await _record_real_session(event_store, session_id, execution_id)

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=_utc_today(),
            end=_utc_today(),
            execution_ids={execution_id},
        )

        assert _bucket_for_today(buckets).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS

    async def test_does_not_double_count_output_across_both_lanes(self, event_store, execution_id):
        """Reading summary must REPLACE the per-turn rows, not add to them.

        Guards the obvious wrong fix: unioning the two sources would report
        13,305 - the authoritative total plus the placeholders it supersedes.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await _record_real_session(event_store, session_id, execution_id)

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=_utc_today(),
            end=_utc_today(),
            execution_ids={execution_id},
        )

        breakdown = _bucket_for_today(buckets).breakdown
        assert breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS
        assert breakdown["input_tokens"] == _TRUE_INPUT_TOKENS
        assert breakdown["cache_read_tokens"] == _TRUE_CACHE_READ
        assert breakdown["cache_creation_tokens"] == _TRUE_CACHE_CREATION

    async def test_falls_back_to_token_usage_while_session_still_running(
        self, event_store, execution_id
    ):
        """A session with no summary yet must still appear, priced from what it has.

        Mid-flight sessions are the reason token_usage exists. Preferring the
        summary must not make in-progress work invisible.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await event_store.record_observation(
            session_id=session_id,
            observation_type=TOKEN_USAGE,
            data={
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "model": _MODEL,
            },
            execution_id=execution_id,
        )

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=_utc_today(),
            end=_utc_today(),
            execution_ids={execution_id},
        )

        breakdown = _bucket_for_today(buckets).breakdown
        assert breakdown["output_tokens"] == 50
        assert breakdown["input_tokens"] == 100


class TestHeatmapPrefersVendorReportedCost:
    async def test_uses_the_cli_reported_cost_not_a_recomputation(self, event_store, execution_id):
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
        await _record_real_session(event_store, session_id, execution_id)

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=_utc_today(), end=_utc_today(), execution_ids={execution_id}
        )

        assert _bucket_for_today(buckets).breakdown["cost_usd"] == pytest.approx(
            _VENDOR_COST_USD, abs=1e-4
        )

    async def test_computes_cost_when_the_harness_reported_none(self, event_store, execution_id):
        """Codex reports no cost of its own, so its tokens must still be priced.

        A summary with a NULL cost previously had no path to a dollar figure:
        preferring the vendor number without a fallback would silently price
        every codex session at zero.
        """
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        await event_store.record_observation(
            session_id=session_id,
            observation_type=SESSION_SUMMARY,
            data={
                "total_input_tokens": 1_000_000,
                "total_output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "total_cost_usd": None,
                "model": "claude-opus-4-20250514",
                "num_turns": 1,
            },
            execution_id=execution_id,
        )

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=_utc_today(), end=_utc_today(), execution_ids={execution_id}
        )

        breakdown = _bucket_for_today(buckets).breakdown
        assert breakdown["cost_usd"] > 0.0
        assert breakdown["unpriced_tokens"] == 0.0


class TestEmptySummaryDoesNotEraseRealUsage:
    async def test_all_zero_summary_falls_back_to_the_turn_rows(self, event_store, execution_id):
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
        await event_store.record_observation(
            session_id=session_id,
            observation_type=TOKEN_USAGE,
            data={
                "input_tokens": 18,
                "output_tokens": 5,
                "cache_creation_tokens": 4_521,
                "cache_read_tokens": 58_654,
                "model": _MODEL,
            },
            execution_id=execution_id,
        )
        await event_store.record_observation(
            session_id=session_id,
            observation_type=SESSION_SUMMARY,
            data={
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "total_cost_usd": None,
                "model": _MODEL,
            },
            execution_id=execution_id,
        )

        query = TimescaleHeatmapQuery(event_store.pool)
        buckets = await query.query(
            start=_utc_today(), end=_utc_today(), execution_ids={execution_id}
        )

        breakdown = _bucket_for_today(buckets).breakdown
        assert breakdown["cache_read_tokens"] == 58_654
        assert breakdown["input_tokens"] == 18
        assert breakdown["tokens"] == 63_198


class TestOneSummaryPerSession:
    async def test_two_summaries_do_not_add_together(self, event_store, execution_id):
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
        for _ in range(2):
            await event_store.record_observation(
                session_id=session_id,
                observation_type=SESSION_SUMMARY,
                data={
                    "total_input_tokens": 18,
                    "total_output_tokens": 13_300,
                    "cache_creation_tokens": 15_809,
                    "cache_read_tokens": 58_179,
                    "total_cost_usd": _VENDOR_COST_USD,
                    "model": _MODEL,
                },
                execution_id=execution_id,
            )

        buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=_utc_today(), end=_utc_today(), execution_ids={execution_id}
        )
        breakdown = _bucket_for_today(buckets).breakdown

        assert breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS
        assert breakdown["cost_usd"] == pytest.approx(_VENDOR_COST_USD, abs=1e-4)

    async def test_differing_models_across_summaries_still_yield_one(
        self, event_store, execution_id
    ):
        """Grouping by model must not turn a duplicate into two legitimate rows."""
        from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
            TimescaleHeatmapQuery,
        )

        session_id = str(uuid4())
        for model, cost in ((_MODEL, _VENDOR_COST_USD), ("claude-sonnet-5", None)):
            await event_store.record_observation(
                session_id=session_id,
                observation_type=SESSION_SUMMARY,
                data={
                    "total_input_tokens": 18,
                    "total_output_tokens": 13_300,
                    "cache_creation_tokens": 15_809,
                    "cache_read_tokens": 58_179,
                    "total_cost_usd": cost,
                    "model": model,
                },
                execution_id=execution_id,
            )

        buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=_utc_today(), end=_utc_today(), execution_ids={execution_id}
        )
        assert _bucket_for_today(buckets).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS

    async def test_a_newer_corrected_summary_beats_an_older_larger_one(
        self, event_store, execution_id
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
        async with event_store.pool.acquire() as conn:
            for hours_ago, output in ((2, 99_999), (1, _TRUE_OUTPUT_TOKENS)):
                await conn.execute(
                    """
                    INSERT INTO agent_events
                        (time, event_type, session_id, execution_id, phase_id, data)
                    VALUES (now() - make_interval(hours => $1), $2, $3, $4, NULL, $5::jsonb)
                    """,
                    hours_ago,
                    SESSION_SUMMARY,
                    session_id,
                    execution_id,
                    json.dumps(
                        {
                            "total_input_tokens": 18,
                            "total_output_tokens": output,
                            "cache_creation_tokens": 0,
                            "cache_read_tokens": 0,
                            "total_cost_usd": _VENDOR_COST_USD,
                            "model": _MODEL,
                        }
                    ),
                )

        buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=_utc_today(), end=_utc_today(), execution_ids={execution_id}
        )
        assert _bucket_for_today(buckets).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS


class TestSessionsStraddlingTheWindow:
    async def test_summary_after_the_window_still_supersedes_turn_rows(
        self, event_store, execution_id
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
        today = _utc_today()
        # Turn rows land today; the summary lands tomorrow, outside the query.
        await event_store.record_observation(
            session_id=session_id,
            observation_type=TOKEN_USAGE,
            data={
                "input_tokens": 18,
                "output_tokens": 5,
                "cache_creation_tokens": 15_809,
                "cache_read_tokens": 58_179,
                "model": _MODEL,
            },
            execution_id=execution_id,
        )
        async with event_store.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_events
                    (time, event_type, session_id, execution_id, phase_id, data)
                VALUES (now() + interval '1 day', $1, $2, $3, NULL, $4::jsonb)
                """,
                SESSION_SUMMARY,
                session_id,
                execution_id,
                json.dumps(
                    {
                        "total_input_tokens": 18,
                        "total_output_tokens": _TRUE_OUTPUT_TOKENS,
                        "cache_creation_tokens": 15_809,
                        "cache_read_tokens": 58_179,
                        "total_cost_usd": _VENDOR_COST_USD,
                        "model": _MODEL,
                    }
                ),
            )

        buckets = await TimescaleHeatmapQuery(event_store.pool).query(
            start=today, end=today, execution_ids={execution_id}
        )

        assert _bucket_for_today(buckets).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS
