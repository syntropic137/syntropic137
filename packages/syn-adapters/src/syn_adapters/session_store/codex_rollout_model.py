"""Which model a codex rollout names (issues #1284, #1424).

Codex names its model on disk and NOWHERE on its stdout stream, so the rollout
is the only place a codex phase's model can be observed at all. WHERE it names
it - ``turn_context.payload.model`` - is codex's format, which changes when
codex ships, so the reader lives here in the adapter rather than in the domain.
The domain receives the answer through ``CodexRolloutPort``.

``rollout_record_model`` is the ONLY reader of that field. ``model_from_rollout``
below and the usage adapter's codex scan (``transcript_usage``) both go through
it: a rollout field with two readers drifts the moment codex moves it, and the
failure is silent - both the price and the identity would go quietly unknown.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import RolloutDocument, RolloutRecord


def rollout_record_model(record: RolloutRecord) -> str | None:
    """The model one codex rollout record names, or None if it names none.

    A rollout carries its model on turn_context rather than on usage.
    """
    if record.get("type") != "turn_context":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    model = payload.get("model")
    return model if isinstance(model, str) else None


def model_from_rollout(document: RolloutDocument) -> str | None:
    """Which model a codex rollout says ran, or None if it does not say one.

    None is returned for a rollout that names no model AND for one that names
    several. The second is the refusal the usage adapter already makes for
    pricing, for the same reason: a session that spanned models cannot be
    attributed to one of them, and naming whichever came first would read as
    evidence. The caller cannot tell those two apart, and does not need to -
    both mean "the rollout does not establish a model".

    A blank model names nothing and is dropped rather than returned. ``""``
    is not an id, and a caller that received one would carry it onward as
    though it were - which is the "unknown" sentinel mistake in a shorter
    spelling.
    """
    models = {
        model.strip()
        for record in document
        if isinstance(record, Mapping)
        and (model := rollout_record_model(record)) is not None
        and model.strip()
    }
    return next(iter(models)) if len(models) == 1 else None
