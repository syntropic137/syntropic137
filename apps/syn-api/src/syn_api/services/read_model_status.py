"""Whether a read model is being rebuilt, in words a page can show.

After a deploy bumps a projection's version, that read model replays from
nonce 0 and serves a partial view until it reaches the head: the execution list
shows 1,109 of ~1,300 runs, newest missing, and looks broken. The facts that
explain it are in ``ReadModelLag``; this module turns them into a verdict for
ONE read model, with every number the UI shows computed here rather than by
the client.

WHAT COUNTS AS REBUILDING. A projection is rebuilding when it is behind the
head AND either the coordinator is replaying (``is_catching_up``) or it is more
than ``LIVE_LAG_THRESHOLD`` events behind. The first catches a replay early,
when the count is still small; the second catches a projection replaying on its
own rebuild track (#1318) while the coordinator as a whole is live. Ordinary
live lag - a checkpoint a few events short mid-dispatch - is neither, so a page
does not flash a banner on every write burst.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from syn_api.types import ReadModelStatus

if TYPE_CHECKING:
    from syn_adapters.subscriptions.read_model_lag import ProjectionLag, ReadModelLag

logger = logging.getLogger(__name__)

#: More events behind than this is a rebuild, not live lag. Live lag is bounded
#: by one write burst on a track; a version-bumped replay starts a whole store
#: behind. 500 sits well above the first and far below the second.
LIVE_LAG_THRESHOLD = 500

#: The probe reads the database; past this a page renders without the notice.
_PROBE_TIMEOUT_S = 2.0

#: What each user-facing read model holds, for a sentence. Unlisted names read
#: as their projection name, which is still true, just less friendly.
_LABELS = {
    "workflow_executions": "execution history",
    "workflow_execution_details": "execution details",
    "evals": "evals",
}


def _label(projection: str) -> str:
    return _LABELS.get(projection, projection.replace("_", " "))


def _judge(entry: ProjectionLag, head_position: int) -> ReadModelStatus:
    """The verdict for one projection known to be rebuilding."""
    # Floor, and never 100 while behind: "100%" beside "12 events behind" reads as a bug.
    pct = min(99, entry.position * 100 // head_position) if head_position > 0 else 0
    label = _label(entry.projection)
    behind = f"{entry.lag:,} event{'s' if entry.lag != 1 else ''} behind"
    return ReadModelStatus(
        rebuilding=True,
        projection=entry.projection,
        label_display=label,
        progress_pct=pct,
        progress_display=f"{pct}%",
        events_behind=entry.lag,
        events_behind_display=behind,
        summary_display=f"Rebuilding {label} - {pct}% ({behind}).",
    )


def _is_rebuilding(entry: ProjectionLag, lag: ReadModelLag) -> bool:
    return lag.is_catching_up or entry.lag > LIVE_LAG_THRESHOLD


def rebuilding_read_models(lag: ReadModelLag) -> list[ReadModelStatus]:
    """Every read model that is rebuilding, furthest behind first."""
    return [
        _judge(entry, lag.head_position)
        for entry in lag.lagging_projections
        if _is_rebuilding(entry, lag)
    ]


def judge_read_model_status(lag: ReadModelLag | None, projection: str) -> ReadModelStatus:
    """Whether ``projection`` is rebuilding, given a lag snapshot (None: unknown)."""
    if lag is not None:
        for entry in lag.lagging_projections:
            if entry.projection == projection and _is_rebuilding(entry, lag):
                return _judge(entry, lag.head_position)
    return ReadModelStatus(
        rebuilding=False, projection=projection, label_display=_label(projection)
    )


async def read_model_status(projection: str) -> ReadModelStatus:
    """Whether ``projection`` is rebuilding right now, asked of the live coordinator.

    Fails open to "not rebuilding": no subscription, or a probe that failed or
    hung, must not fail the list or detail request that asked.
    """
    from syn_api.services.lifecycle import _state

    service = _state.subscription_service
    if service is None:
        return judge_read_model_status(None, projection)
    try:
        lag = await asyncio.wait_for(service.describe_read_model_lag(), timeout=_PROBE_TIMEOUT_S)
    except Exception:
        logger.warning(
            "Read model lag probe failed; reporting %s as not rebuilding", projection, exc_info=True
        )
        lag = None
    return judge_read_model_status(lag, projection)
