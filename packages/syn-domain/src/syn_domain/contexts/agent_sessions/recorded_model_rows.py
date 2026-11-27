"""Reading the model fields of stored usage rows, in SQL and in memory (ADR-067).

Every cost reader that groups ``agent_events`` by model has to carry THREE
facts per group, not one: the stored ``model``, the stored
``requested_model``, and whether the row HAS a ``requested_model`` key at all.
The third is what ``syn_shared.observed_model.split_recorded_model`` needs to
tell a legacy row (``model`` held the request, often an alias) from a row
written under ADR-067 (``model`` is what the harness reported, or null).

The SQL fragments and the row reader live together here so that the columns a
query projects and the names the reader looks up cannot drift apart, and so
the in-memory projections - which read the observation ``data`` directly via
``split_observation_model`` - and the SQL paths classify a row identically.
That identity is what keeps a replayed projection and a live query in
agreement about the same stored rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from syn_shared.observed_model import (
    OBSERVED_MODEL_KEY,
    REQUESTED_MODEL_KEY,
    RecordedModel,
    split_recorded_model,
)
from syn_shared.pricing import CacheWrites

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

REQUESTED_MODEL_COLUMN: Final[str] = "requested_model"
"""Result column carrying ``data->>'requested_model'``."""

HAS_REQUESTED_MODEL_COLUMN: Final[str] = "has_requested_model"
"""Result column carrying ``data ? 'requested_model'`` (key presence)."""


def recorded_model_select(data: str = "data", *, model_column: str = "model") -> str:
    """The three model columns for a SELECT list, over the JSONB ``data`` expr.

    ``model_column`` names the observed-model column, because some queries
    have always called it ``agent_model`` and their callers read it by that name.
    """
    return (
        f"{data}->>'{OBSERVED_MODEL_KEY}' as {model_column}, "
        f"{data}->>'{REQUESTED_MODEL_KEY}' as {REQUESTED_MODEL_COLUMN}, "
        f"({data} ? '{REQUESTED_MODEL_KEY}') as {HAS_REQUESTED_MODEL_COLUMN}"
    )


def recorded_model_group_by(data: str = "data") -> str:
    """The GROUP BY terms matching ``recorded_model_select``.

    All three are grouped on. Grouping on ``model`` alone would merge a legacy
    ``opus`` row (the request) with a new row that REPORTED a model named the
    same, and classify the merged group once for both.
    """
    return (
        f"{data}->>'{OBSERVED_MODEL_KEY}', "
        f"{data}->>'{REQUESTED_MODEL_KEY}', "
        f"({data} ? '{REQUESTED_MODEL_KEY}')"
    )


def zero_usage_group_by(data: str = "data") -> str:
    """A GROUP BY term that keeps observations reporting no tokens apart.

    Replay prices each ``token_usage`` observation alone, and one with no
    tokens is a priced zero at any rate (issue #890). Summed into a group with
    a positive observation on an unrated model, it would be priced as that
    group: unpriced, and counted in ``unpriced_observation_count``. Grouping on
    this term keeps SQL pricing what replay prices (#1420).

    ``bigint``, as ``turn_usage_columns`` reads the same fields: the usage
    rollup's trigger evaluates this on every ingested turn (ADR-079), and an
    ``int`` cast there would abort the insert of a turn the token columns
    accept, for one count above 2^31 or for four whose sum is.
    """
    return (
        f"((COALESCE(({data}->>'input_tokens')::bigint, 0) "
        f"+ COALESCE(({data}->>'output_tokens')::bigint, 0) "
        f"+ COALESCE(({data}->>'cache_creation_tokens')::bigint, 0) "
        f"+ COALESCE(({data}->>'cache_read_tokens')::bigint, 0)) = 0)"
    )


class ModelRow(Protocol):
    """What a row must offer: ``asyncpg.Record`` and a plain mapping both do."""

    def get(self, key: str, /) -> object: ...


def recorded_model_from_row(row: ModelRow, *, model_column: str = "model") -> RecordedModel:
    """Classify one grouped row's model columns (see ``recorded_model_select``).

    A row without the presence column - a hand-built fixture, or a query not yet
    selecting it - reads as a legacy row, which is the safe direction: a legacy
    alias is demoted to requested, and an explicit id is kept.
    """
    return split_recorded_model(
        row.get(model_column),
        row.get(REQUESTED_MODEL_COLUMN),
        has_requested_key=bool(row.get(HAS_REQUESTED_MODEL_COLUMN)),
    )


def pick_primary_model(tokens_by_model: Mapping[str, int]) -> str | None:
    """The model that did most of the work. Most tokens wins, ties by name.

    Callers pass OBSERVED models only (or requested models only, for the
    requested field), never a mixture, and never the unknown bucket: a primary
    model is a claim about what ran, and "unknown" is not a model.
    """
    if not tokens_by_model:
        return None
    return max(tokens_by_model.items(), key=lambda kv: (kv[1], kv[0]))[0]


def observed_cache_creation_1h(
    turn_rows: Iterable[ModelRow], total: int, *, session_ids: frozenset[str] | None = None
) -> int:
    """The 1-hour share of ``total`` cache writes, as a session's turns recorded it.

    A ``session_summary`` row records every cache write in one total and no
    TTL split, so a reader that prices or counts from a summary takes the split
    from the ``token_usage`` rows (grouped, each carrying ``cache_creation_1h``)
    of the same sessions (#2145). Clamped to ``total`` by ``CacheWrites``; a
    legacy turn without the column contributes 0. Execution queries group turns
    per session and pass the summarized ``session_ids`` so unfinished sessions
    cannot contribute a split to another session's authoritative total.
    """
    one_hour = 0
    for row in turn_rows:
        if session_ids is not None and row.get("session_id") not in session_ids:
            continue
        value = row.get("cache_creation_1h")
        one_hour += value if isinstance(value, int) else 0
    return CacheWrites.from_recorded(total, one_hour).one_hour


__all__ = [
    "HAS_REQUESTED_MODEL_COLUMN",
    "REQUESTED_MODEL_COLUMN",
    "ModelRow",
    "observed_cache_creation_1h",
    "pick_primary_model",
    "recorded_model_from_row",
    "recorded_model_group_by",
    "recorded_model_select",
    "zero_usage_group_by",
]
