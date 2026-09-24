"""Observed vs requested model: the one contract every run-time surface uses.

A workflow DEFINITION names a model the way its author wrote it - usually an
alias (``opus``, ``gpt-sol``). What actually ran is only known when the harness
reports it (claude's ``system/init`` line, codex's rollout). Those are two
different facts and conflating them is how every run-time surface came to show
``opus`` as "the model", which proves nothing: ``opus`` is a pointer, and where
it points moves.

Rule (ADR-067, "Observed vs requested model"): aliases appear ONLY on workflow
definition surfaces. Everywhere else ``model`` is what the harness REPORTED, or
explicitly unknown, and the alias is carried separately as ``requested_model``.

Lane 2 observations therefore carry two fields:

- ``model``: the reported id, or null. Never an alias.
- ``requested_model``: what the workflow asked for, or null.

Rows written before this contract carry only ``model``, set to the REQUESTED
value. ``split_recorded_model`` reads both shapes, deterministically, so a
replay of the same stream always yields the same read model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from syn_shared.agents import CodexModelAlias, ModelAlias

UNKNOWN_MODEL_KEY: Final[str] = "unattributed-model"
"""``cost_by_model`` bucket for cost whose model the harness did not report.

The value predates this module (it was the execution-cost bucket for
summaries naming no model) and is kept so existing clients keep working. It
now means the single thing both cases have in common: no reported model.
"""

REQUESTED_MODEL_KEY: Final[str] = "requested_model"
"""Observation data key for the requested model. Its PRESENCE marks a row as
written under this contract (see ``split_recorded_model``)."""

OBSERVED_MODEL_KEY: Final[str] = "model"
"""Observation data key for the reported model."""

LEGACY_REQUESTED_ALIASES: Final[frozenset[str]] = frozenset(
    {
        ModelAlias.HAIKU,
        ModelAlias.SONNET,
        ModelAlias.OPUS,
        ModelAlias.FABLE,
        CodexModelAlias.GPT_SOL,
    }
)
"""Aliases a pre-contract writer could have put in ``data.model``.

FROZEN on purpose, not derived from the live alias enums: classification of a
legacy row must never change because an alias was added later. Only rows
WITHOUT a ``requested_model`` key are classified with it, and every row
written after this contract has the key, so no future alias can ever need to
be listed here. Do not add to it.
"""


@dataclass(frozen=True, slots=True)
class RecordedModel:
    """The two model facts a run-time record carries."""

    observed: str | None
    """What the harness reported. None = not reported (unknown)."""

    requested: str | None
    """What the workflow asked for (often an alias). None = not recorded."""

    @property
    def cost_key(self) -> str:
        """The ``cost_by_model`` key: the reported id, or the unknown bucket."""
        return self.observed if self.observed else UNKNOWN_MODEL_KEY

    @property
    def pricing_model(self) -> str | None:
        """The model to price against.

        The reported model when there is one. Otherwise the requested one, so
        a run whose model was never reported keeps the cost it has always had
        rather than silently becoming free; its cost is still attributed to
        ``UNKNOWN_MODEL_KEY``, never to the alias.
        """
        return self.observed or self.requested


def _clean(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def is_model_alias(value: str | None) -> bool:
    """True when ``value`` is any alias a workflow may declare (current or legacy)."""
    if value is None:
        return False
    return (
        value in LEGACY_REQUESTED_ALIASES
        or value in frozenset(ModelAlias)
        or value in frozenset(CodexModelAlias)
    )


def split_recorded_model(
    model: object,
    requested_model: object,
    *,
    has_requested_key: bool,
) -> RecordedModel:
    """Read a stored record's model fields under either writer era.

    ``has_requested_key`` is whether the record HAS a ``requested_model`` key
    (a JSON null counts as present). Callers must pass the key's presence, not
    the value's truthiness: that distinction is what tells a post-contract row
    whose model was unreported from a pre-contract row.

    - Post-contract row: fields are taken as written. A ``model`` that is
      nonetheless an alias is demoted to requested - defence in depth, since
      the whole point is that an alias is never reported as what ran.
    - Pre-contract row whose ``model`` is a legacy alias: that value was the
      REQUEST, and nothing observed what ran.
    - Pre-contract row with an explicit id (delegate imports, old pinned ids):
      that id came from a transcript or an explicit pin and is kept as the
      model.
    """
    observed = _clean(model)
    requested = _clean(requested_model)
    if has_requested_key:
        if observed is not None and is_model_alias(observed):
            return RecordedModel(observed=None, requested=requested or observed)
        return RecordedModel(observed=observed, requested=requested)
    if observed is not None and observed in LEGACY_REQUESTED_ALIASES:
        return RecordedModel(observed=None, requested=observed)
    return RecordedModel(observed=observed, requested=None)


def split_observation_model(data: object) -> RecordedModel:
    """``split_recorded_model`` over an observation ``data`` mapping."""
    if not isinstance(data, dict):
        return RecordedModel(observed=None, requested=None)
    return split_recorded_model(
        data.get(OBSERVED_MODEL_KEY),
        data.get(REQUESTED_MODEL_KEY),
        has_requested_key=REQUESTED_MODEL_KEY in data,
    )


UNKNOWN_MODEL_DISPLAY: Final[str] = "unknown"


def format_observed_model(observed: str | None, requested: str | None) -> str:
    """Human display for a run-time model. Clients render it verbatim.

    ``claude-opus-5-5`` -> ``claude-opus-5-5`` (the explicit id, never
    prettified: the id IS the proof), unknown with a request ->
    ``unknown (requested: gpt-sol)``, neither -> ``unknown``.
    """
    if observed:
        return observed
    if requested:
        return f"{UNKNOWN_MODEL_DISPLAY} (requested: {requested})"
    return UNKNOWN_MODEL_DISPLAY


def format_cost_model_key(key: str) -> str:
    """Display for a ``cost_by_model`` key."""
    return UNKNOWN_MODEL_DISPLAY if key == UNKNOWN_MODEL_KEY else key
