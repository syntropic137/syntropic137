"""What /health says about the read path, and the rule that decides it.

Split out of `lifecycle` because none of this is process lifecycle: it is a
severity table over the ways a read path can be unwell, plus the rule that turns
one subscription measurement into the verdict the health payload publishes.
`lifecycle._enrich_subscription_health` renders that verdict; it does not make
it. Kept together because a signal's severity, its reason and its status are one
fact described three ways — see `_judge_read_path` for why they must stay on one
row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from syn_api.services.degraded_reasons import DegradedReason

if TYPE_CHECKING:
    from syn_adapters.subscriptions.read_model_lag import ReadModelLag


#: The values `subscription.status` can take. "healthy" is the absence of every
#: signal below, so it is not a signal itself and has no row in the table.
_ReadPathStatus = Literal["healthy", "degraded", "stalled", "catching_up"]


@dataclass(frozen=True)
class _ReadPathSignal:
    """One way the read path can be unwell: whether it is, and what to say if so.

    `reason` is what `degraded_reasons` carries; `status` is what
    `subscription.status` says when this is the most severe signal firing. Both
    live on the same row because they are one signal described two ways, and a
    row is the whole of what a new signal costs.
    """

    fires: bool
    reason: DegradedReason
    status: _ReadPathStatus


@dataclass(frozen=True)
class _ReadPathVerdict:
    """What /health should say about the read path."""

    status: _ReadPathStatus
    degraded_reasons: tuple[DegradedReason, ...]


def _judge_read_path(*, running: bool, lag: ReadModelLag | None) -> _ReadPathVerdict:
    """Turn the subscription's facts into the verdict /health publishes.

    ADDING A THIRD SIGNAL? Add a row. It is deliberately impossible to add one
    that reports a reason but no status, or a status no reason explains: the
    ranking and the list are read off the SAME rows, so they cannot drift into
    disagreeing about one deployment. That drift is the bug this shape exists to
    make unwriteable, and it was reachable while the two were computed apart.

    THE ROWS ARE ORDERED BY SEVERITY, most severe first, because
    `subscription.status` has ONE slot and the signals are independent. When
    several fire it leads with the one needing a human: a dead coordinator, then
    a stall, then a rebuild. That ranking is presentation only —
    `degraded_reasons` carries EVERY signal that fired, so a wedged replay is
    `stalled` with both reasons raised. Two true facts about one read path, not
    a conflict.

    `lag is None` means the subscription is not up yet, which is a different
    answer from "not behind": it fires no lag signal of its own, and `running`
    is what reports it.
    """
    signals = (
        _ReadPathSignal(
            fires=not running,
            reason=DegradedReason.SUBSCRIPTION_COORDINATOR,
            status="degraded",
        ),
        _ReadPathSignal(
            fires=lag is not None and lag.is_stalled,
            reason=DegradedReason.PROJECTION_STALLED,
            status="stalled",
        ),
        _ReadPathSignal(
            fires=lag is not None and lag.is_catching_up,
            reason=DegradedReason.PROJECTION_CATCHUP,
            status="catching_up",
        ),
    )
    fired = tuple(signal for signal in signals if signal.fires)

    return _ReadPathVerdict(
        status=fired[0].status if fired else "healthy",
        degraded_reasons=tuple(signal.reason for signal in fired),
    )
