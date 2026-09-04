"""The payload shapes carried by agent observations.

``AgentObservationEvent.data`` is a JSON object whose keys depend on the
observation type, and for most types that shape is only described in a comment
(see ``agent_observation.py``). The two named here are the ones the cost ledger
reads, so their producer and their consumers share one declaration instead of
agreeing by string key and hoping.

``TypedDict`` rather than a model, deliberately: these payloads are stored and
replayed as plain dicts, and a projection has to read back exactly what was
written. Parsing them into objects would put a re-serialisation between writer
and reader, which is precisely the hop at which a field goes missing.

Only two shapes are declared. The rest still travel untyped - notably anything
recorded from a git or hook event, whose payload is flattened from arbitrary
hook context and genuinely has no fixed shape to declare.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class TokenUsageData(TypedDict):
    """One turn's token deltas, as a ``token_usage`` observation carries them.

    Written by ``ObservabilityCollector.record_token_usage`` and
    ``AgentObservationEvent.token_usage``, accumulated by the cost projections.

    These are PER-TURN deltas, so summing them over-counts the context re-sent
    on every turn. ``SessionSummaryData`` carries the run's cumulative figure,
    which is why a summary replaces the accumulated sum rather than adding to it.
    """

    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    model: str | None


class SessionSummaryData(TypedDict):
    """A run's end-of-run totals, as a ``session_summary`` observation carries them.

    Written once per phase by ``ObservabilityCollector.record_session_summary``
    and read by the cost projections. Cumulative rather than deltas, so these
    REPLACE the accumulated per-turn counts.

    The nullable fields are nullable because a run that was killed or timed out
    never got to report them. Absent and null therefore mean the same thing -
    nobody counted this - and a consumer that assigns either over a counted
    value throws away what the run actually did (#1164).
    """

    total_cost_usd: float | None
    total_input_tokens: int
    total_output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    num_turns: int | None
    duration_ms: int | None
    model: str | None

    #: Read by both summary consumers, written by no current producer, so it
    #: always resolves to "not reported" and leaves the counted tool calls
    #: alone. Declared because the drift is worth seeing rather than leaving
    #: as two string keys that quietly never match.
    tool_count: NotRequired[int]

    #: Whether the harness reported these totals itself, or they are what was
    #: observed before it died. ``NotRequired`` for read compatibility only:
    #: every producer writes it, but summaries recorded before the flag existed
    #: carry no key, so read it with a ``True`` default to keep their original
    #: replace-and-settle semantics on replay.
    totals_are_authoritative: NotRequired[bool]
