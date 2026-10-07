"""Which kind of work a phase does, read from its phase_id.

Phase type is not recorded on any event: a workflow names its phases freely in
its YAML. The scorecard groups the SDLC workflows' phases by the job they do, so
this mapping is the one place that names them. A phase it does not recognise is
``OTHER``, shown as its own row rather than folded into a neighbour.
"""

from __future__ import annotations

import re
from enum import StrEnum


class PhaseType(StrEnum):
    PREMISE = "premise"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    FIX = "fix"
    REVERIFY = "reverify"
    FINALIZE = "finalize"
    OTHER = "other"


_ROUND_SUFFIX = re.compile(r"_\d+$")
"""``fix_2`` and ``reverify_3`` are later rounds of the same phase type."""

_BY_PHASE_ID: dict[str, PhaseType] = {
    "premise": PhaseType.PREMISE,
    "implement": PhaseType.IMPLEMENT,
    "quickfix": PhaseType.IMPLEMENT,
    "verify": PhaseType.VERIFY,
    "fix": PhaseType.FIX,
    "reverify": PhaseType.REVERIFY,
    "finalize_pr": PhaseType.FINALIZE,
    "open_pr": PhaseType.FINALIZE,
}


def phase_type_of(phase_id: str) -> PhaseType:
    """The phase type a phase_id names, or OTHER when it names none."""
    return _BY_PHASE_ID.get(_ROUND_SUFFIX.sub("", phase_id), PhaseType.OTHER)
