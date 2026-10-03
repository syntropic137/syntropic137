"""The harness-neutral rule for reading a reported model off a stream (#1284).

Its own module so that both stream processors AND the observability collector
can share it without the collector importing a stream processor. Re-exported
from ``EventStreamProcessor`` for existing importers.
"""

from __future__ import annotations

__all__ = ["announced_model_from"]


def announced_model_from(*candidates: object) -> str | None:
    """The model this line says is running, or None if it does not say (#1284).

    Shared by both stream processors, because the RULE is harness-neutral even
    though the places to look are not: the first candidate that is a non-blank
    string wins. ``CodexStreamProcessor`` imports it rather than restating it,
    so "" and a late rebind are rejected identically on both streams.

    Claude states it in two places and both are the harness speaking about
    itself: the ``system``/``init`` line carries it at the top level, and every
    ``assistant`` line repeats it under ``message``. Both are offered here
    rather than picking one, so a recording that begins mid-stream still yields
    an answer instead of none.

    The candidates are passed as values rather than the line itself: the
    parameter would otherwise be one more ``Mapping[str, Any]``, which spends
    ratchet budget to say nothing (#673).

    Returns None for a line that carries no model at all, which is most of
    them, and for a blank one - "" is not an identity and must not displace the
    real value that a later line may carry.
    """
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None
