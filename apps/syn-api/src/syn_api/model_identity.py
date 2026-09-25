"""Types that make an alias unrepresentable as a run-time model (ADR-067 D9).

Aliases (``opus``, ``gpt-sol``...) are allowed only on workflow DEFINITION
responses. Every run-time response field that names a model - a phase's model,
a session's ``agent_model``, an artifact's producer, a ``cost_by_model`` key -
is typed with one of these, so an alias that ever reaches one fails validation
at the response boundary instead of being shown as if it were what ran.

``tests/test_no_alias_as_model.py`` fails when a new run-time model field is
added without them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

from pydantic import AfterValidator

from syn_shared.observed_model import (
    UNKNOWN_MODEL_KEY,
    RecordedModel,
    is_model_alias,
    split_recorded_model,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _reject_alias(value: str) -> str:
    if is_model_alias(value):
        msg = (
            f"{value!r} is a model ALIAS (a request), not the model that ran; "
            "run-time surfaces carry the harness-reported id or null, and the "
            "alias belongs in requested_model (ADR-067 D9)"
        )
        raise ValueError(msg)
    return value


ObservedModelId = Annotated[str, AfterValidator(_reject_alias)]
"""A model id the harness REPORTED. Never an alias."""

ResolvedModelId = Annotated[str, AfterValidator(_reject_alias)]
"""The concrete id a DEFINITION's alias resolves to. Never an alias, and never
what a run used: that is an ``ObservedModelId``."""

CostModelKey = Annotated[str, AfterValidator(_reject_alias)]
"""A ``cost_by_model`` key: a reported id or ``UNKNOWN_MODEL_KEY``. Never an alias."""


def observed_model_of(model: object, requested_model: object) -> RecordedModel:
    """The observed/requested pair to serve for a stored ``model`` value.

    Read models written after ADR-067 already hold the reported id (or None)
    as ``model``; ones written before may hold the REQUESTED alias there.
    ``split_recorded_model`` with the key treated as present demotes such an
    alias to ``requested`` instead of letting it reach an ``ObservedModelId``
    field and fail the response with a 500.
    """
    return split_recorded_model(model, requested_model, has_requested_key=True)


def cost_by_observed_model(costs: Mapping[str, object]) -> dict[str, Decimal]:
    """A ``cost_by_model`` map keyed only by reported ids or ``UNKNOWN_MODEL_KEY``.

    A key that is an alias came from a legacy read model and was never what
    ran: its cost is folded into the unknown bucket, summed with whatever is
    already there, so the parts still add up to the whole.
    """
    folded: dict[str, Decimal] = {}
    for key, value in costs.items():
        bucket = UNKNOWN_MODEL_KEY if is_model_alias(key) else key
        folded[bucket] = folded.get(bucket, Decimal("0")) + Decimal(str(value))
    return folded


def cost_by_observed_model_text(costs: object) -> dict[str, str]:
    """``cost_by_observed_model`` for the responses that serve costs as strings.

    Takes the untyped map a dict-returning handler produced; anything that is
    not a mapping is treated as no breakdown at all.
    """
    if not isinstance(costs, dict):
        return {}
    return {k: str(v) for k, v in cost_by_observed_model(costs).items()}
