"""Whether a read model is being rebuilt, in words a page can show.

After a deploy bumps a projection's version, that read model replays from
nonce 0 and serves a partial view until it reaches the head: the execution list
shows 1,109 of ~1,300 runs, newest missing, and looks broken. The facts that
explain it are in ``ReadModelLag``; this module turns them into a verdict for
ONE read model, with every number the UI shows computed here rather than by
the client.

WHAT COUNTS AS REBUILDING. A projection is rebuilding when it is more than
``LIVE_LAG_THRESHOLD`` events behind the head, whether the coordinator as a
whole is replaying or it replays on its own rebuild track (#1318). The
coordinator's ``is_catching_up`` is deliberately not used: it is true while ANY
track replays, so it would call a peer on ordinary live lag rebuilding too.
Ordinary live lag - a checkpoint a few events short mid-dispatch - is never a
rebuild, so a page does not flash a banner on every write burst. The cost is
that a replay's last few hundred events read as caught up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from syn_api.types import ReadModelStatus

if TYPE_CHECKING:
    from collections.abc import Collection

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


def _is_rebuilding(entry: ProjectionLag) -> bool:
    """Far enough behind that its page is visibly incomplete.

    Distance alone, not the coordinator's `is_catching_up`: that is true while
    ANY track replays, so a peer a few events behind on ordinary live lag
    would be called rebuilding beside the one projection that is.
    """
    return entry.lag > LIVE_LAG_THRESHOLD


def rebuilding_read_models(lag: ReadModelLag) -> list[ReadModelStatus]:
    """Every read model that is rebuilding, furthest behind first."""
    return [
        _judge(entry, lag.head_position)
        for entry in lag.lagging_projections
        if _is_rebuilding(entry)
    ]


def judge_read_model_status(lag: ReadModelLag | None, projection: str) -> ReadModelStatus:
    """Whether ``projection`` is rebuilding, given a lag snapshot (None: unknown)."""
    if lag is not None:
        for entry in lag.lagging_projections:
            if entry.projection == projection and _is_rebuilding(entry):
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


async def read_models_rebuilding(projections: Collection[str]) -> str | None:
    """Why any of ``projections`` may be incomplete now, or None when none can be.

    For a caller that DELETES on what a read model says, so it fails closed
    where `read_model_status` fails open: no subscription, or a probe that
    failed or hung, is a reason. And a projection with no checkpoint is
    rebuilding at any distance, not only past ``LIVE_LAG_THRESHOLD``:
    `rebuild_projection` deletes the checkpoint and clears the data while the
    coordinator stays live, and on a small store that is fewer events behind.
    """
    from syn_api.services.lifecycle import _state

    service = _state.subscription_service
    if service is None:
        return "no subscription service to ask whether read models are rebuilding"
    try:
        lag = await asyncio.wait_for(service.describe_read_model_lag(), timeout=_PROBE_TIMEOUT_S)
    except Exception as exc:
        return f"read model lag probe failed ({type(exc).__name__}: {exc})"
    if lag is None:
        return "read model lag is not known yet"
    for entry in lag.lagging_projections:
        if entry.projection in projections and (_is_rebuilding(entry) or entry.position == 0):
            return f"{entry.projection} is rebuilding ({entry.lag} events behind)"
    return None
