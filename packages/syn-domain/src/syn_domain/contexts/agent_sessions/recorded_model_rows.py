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

if TYPE_CHECKING:
    from collections.abc import Mapping

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


__all__ = [
    "HAS_REQUESTED_MODEL_COLUMN",
    "REQUESTED_MODEL_COLUMN",
    "ModelRow",
    "pick_primary_model",
    "recorded_model_from_row",
    "recorded_model_group_by",
    "recorded_model_select",
]
