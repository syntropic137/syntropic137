"""How far the read models are behind the event store, and which one is holding it up.

WHY THIS EXISTS. When a deploy changes any projection's version, the coordinator
clears that projection, deletes its checkpoint, and restarts the ONE shared
subscription from global nonce 0 (``SubscriptionCoordinator._get_minimum_position``).
Until that replay finishes, no projection advances. On the v0.28.0-beta.6 deploy
that took 8m46s, during which every freshly dispatched execution was invisible:
``GET /api/v1/executions/{id}`` returned 404 while the workspace container ran
normally.

Throughout all of it ``/health`` said ``status: healthy`` and
``subscription.status: healthy``, because the only thing the subscription block
reported was ``running``, which is set once at ``start()`` and does not move
during a replay. The one endpoint an operator would check actively reassured
them. The checkpoint table was the only thing distinguishing "rebuild in
progress" from "the platform lost my execution" - a distinction worth a rollback
decision, available only to someone with a psql prompt.

This module makes that distinction answerable from the health payload alone.

TWO SIGNALS, BECAUSE THESE ARE TWO DIFFERENT OPERATOR DECISIONS
---------------------------------------------------------------
Both look identical from outside - stale reads and 404s for freshly written
aggregates - and they call for opposite responses, so they are reported
separately:

- ``is_catching_up``: a rebuild is running. It ends by itself. Wait.
- ``is_stalled``: a projection is behind and NOT MOVING. It does not end by
  itself. Intervene.

They are independent, not exclusive. A replay that wedges partway through sets
both, which is the correct reading of that state and needs no special case here.

WHAT "CATCHING UP" MEANS, and why it is two conditions rather than one
----------------------------------------------------------------------
The read path is catching up when BOTH:

1. the coordinator is replaying history - it has not yet dispatched an event
   past the live-boundary nonce it snapshotted when it subscribed; and
2. at least one projection's checkpoint is still short of the event-store head.

Neither condition is sufficient alone, and the failure mode of each is a health
endpoint nobody trusts:

- Condition 2 alone flaps. Checkpoints advance per event per projection, so on a
  busy deployment a sample taken mid-dispatch routinely finds someone one event
  behind. That would mark a perfectly healthy system degraded at random.
- Condition 1 alone is sticky. The coordinator flips to live only when it
  dispatches an event ABOVE the boundary, so on a quiet store after a completed
  replay it stays ``is_catching_up = True`` until the next write arrives. That
  would report a finished rebuild as still running, indefinitely.

Requiring both gives the honest answer in each case, without touching the
coordinator (it lives in the event-sourcing-platform submodule, where a change
reaches a running deployment only after an image build and a digest bump).

WHAT "STALLED" MEANS, and why it is measured in TIME rather than events
-----------------------------------------------------------------------
A projection is stalled when it is short of the head AND its checkpoint has not
moved for ``stalled_after_seconds``. That is the case the paragraph above cannot
see: a projection failing on the events it is handed never advances its
checkpoint (``_dispatch_to_projection`` deliberately does not advance on FAILURE
or on an exception), while the coordinator stays live and every peer keeps up.
Reported as lag alone it is indistinguishable from a healthy system mid-dispatch,
so before this signal existed a permanently stuck read model was answered with
``status: healthy`` - worse than the blackout this module was written for,
because it never resolves on its own.

The obvious threshold is a COUNT: flag anything more than N events behind. It
fails in both directions here, which is why this measures time instead:

- It cannot catch the case it exists for. A wedged projection's lag grows at the
  store's WRITE RATE, not at the rate at which it is broken. On a quiet
  deployment it sits three events behind forever and never reaches any N worth
  setting, while every read of it is stale.
- It fires on healthy bursts. ``_dispatch_event`` walks all projections
  sequentially per event, so during a write burst every projection trails the
  head together by however far the writer got ahead of the subscriber. That
  distance is bounded by write volume, not by health, so any N is a false
  positive waiting for a big enough execution.

Staleness is scale-free in both directions. A checkpoint is written for EVERY
event a projection is handed - processed, or skipped via
``_advance_checkpoint_if_behind`` - so "behind the head and not moving" means not
making progress whatever the write rate, and "behind the head and moving" means
it is working through a backlog and will arrive. The ambiguity that makes
time-BEHIND uncomputable (see THE UNIT IS EVENTS below) does not apply: a
projection caught up on a quiet store also has an old checkpoint, but it is not
short of the head, so it is never a candidate.

THE NUMBER is 120 seconds, and it is derived from this system's own machinery
rather than picked round: the longest a HEALTHY deployment can hold a projection
behind the head with its checkpoint frozen is a subscription reconnect, which
``SubscriptionCoordinator.start`` retries with exponential backoff capped at
30.0s, plus the resubscribe (minimum-position read, head read, redelivery) that
follows it. 120s is four times that cap. A projection still frozen after two
minutes is not waiting on anything the coordinator does.

That reasoning is read off the code, not off a measurement: no sample of
steady-state ``updated_at`` ages from a live ``projection_checkpoints`` table was
available when this was written. What would settle it properly is sampling
``now() - updated_at`` per projection on a real deployment under representative
load, and setting the threshold above the maximum a healthy system produces.
Until then the payload carries ``checkpoint_age_seconds`` per projection, so that
sample can be taken from ``/health`` itself rather than from a psql prompt.

THE UNIT IS EVENTS. ``lag`` counts global-nonce positions between a projection's
checkpoint and the head of the store, which is what a checkpoint records and
therefore the only quantity available exactly. Time-behind would read better and
cannot be computed: a checkpoint stores when it last MOVED, not the timestamp of
the event it sits on, so a projection frozen at a position from an hour ago is
indistinguishable by time from one that caught up an hour ago on a quiet store.
An over-precise wrong number is worse than an honest coarse one, so the payload
carries ``lag_unit`` and says so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "STALLED_AFTER_SECONDS",
    "CheckpointState",
    "ProjectionLag",
    "ReadModelLag",
    "measure_read_model_lag",
]

#: How long a projection may sit behind the head without its checkpoint moving
#: before it is called stalled. Four times the coordinator's 30.0s reconnect
#: backoff cap - see the module docstring for the derivation and for what
#: measurement would replace it.
STALLED_AFTER_SECONDS = 120


class CheckpointState(BaseModel):
    """A checkpoint row as the measurement needs it: where it is, when it moved.

    ``updated_at`` is what separates "behind and working" from "behind and
    stuck"; without it the two are the same row.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: int = Field(description="Global nonce this checkpoint has reached.")
    updated_at: datetime | None = Field(
        default=None,
        description="When this checkpoint last moved, or the earliest time an absent "
        "checkpoint is known to have been absent. None when neither is known, which "
        "is treated as 'cannot prove it is stuck' rather than as stuck.",
    )


class ProjectionLag(BaseModel):
    """One projection's distance from the head of the event store."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection: str = Field(description="Projection name, as it appears in projection_checkpoints.")
    position: int = Field(
        description="Global nonce this projection's checkpoint has reached. 0 when it has no "
        "checkpoint at all, which is what a projection looks like immediately after a "
        "version bump clears it.",
    )
    lag: int = Field(description="Events between position and the store head. Always > 0 here.")
    checkpoint_age_seconds: int | None = Field(
        default=None,
        description="Seconds since this projection's checkpoint last moved. None when the "
        "projection has no checkpoint row yet. This is the evidence behind `stalled`, "
        "and the number to sample if the stall threshold needs revisiting.",
    )
    stalled: bool = Field(
        default=False,
        description="True when this projection is behind the head and its checkpoint has not "
        "moved for longer than the stall threshold (120s by default): it is not "
        "working through a backlog, it is stuck.",
    )


class ReadModelLag(BaseModel):
    """Whether the read path is behind, by how much, and who is furthest behind.

    Serialized straight into the ``subscription`` block of ``/health``, so every
    field name here is part of that endpoint's contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_catching_up: bool = Field(
        description="True while the coordinator is replaying history AND some projection has "
        "not reached the head. Queries against the read models may return stale "
        "data or 404 for recently written aggregates while this is true. Ends by "
        "itself when the replay finishes.",
    )
    is_stalled: bool = Field(
        default=False,
        description="True when some projection is behind the head and its checkpoint has "
        "stopped moving. Unlike is_catching_up this does NOT resolve on its own - "
        "it means a read model is stuck and needs intervention. Independent of "
        "is_catching_up: a replay that wedges partway sets both.",
    )
    lag: int = Field(
        description="Distance of the FURTHEST-BEHIND projection from the store head, in the "
        "unit named by lag_unit. 0 when every projection is at the head.",
    )
    lag_unit: Literal["events"] = Field(
        default="events",
        description="Unit of lag: event-store global-nonce positions, not seconds.",
    )
    head_position: int = Field(description="Global nonce of the newest event in the store.")
    lagging_projections: list[ProjectionLag] = Field(
        default_factory=list,
        description="Every projection short of the head, furthest behind first. The first "
        "entry is the answer to 'which one is holding this up'; the entries with "
        "`stalled` set are the ones to intervene on.",
    )


def _age_seconds(updated_at: datetime | None, now: datetime) -> int | None:
    """Seconds since a checkpoint last moved, or None if it never has.

    Naive timestamps are read as UTC and negative ages clamped to 0: checkpoints
    can be written by another node, and neither a stored naive timestamp nor a
    slightly fast peer clock is a reason for a health probe to raise or to report
    a negative age.
    """
    if updated_at is None:
        return None
    moment = updated_at if updated_at.tzinfo is not None else updated_at.replace(tzinfo=UTC)
    return max(0, int((now - moment).total_seconds()))


def measure_read_model_lag(
    *,
    head_position: int,
    checkpoints: Mapping[str, CheckpointState],
    projection_names: Iterable[str],
    replaying: bool,
    now: datetime,
    stalled_after_seconds: int = STALLED_AFTER_SECONDS,
) -> ReadModelLag:
    """Judge the read path from a snapshot of checkpoint rows.

    Args:
        head_position: Global nonce of the newest event in the store.
        checkpoints: Projection name -> checkpoint state, for the projections
            that currently HAVE a checkpoint.
        projection_names: Every registered projection. Names absent from
            ``checkpoints`` are treated as position 0 rather than skipped: a
            projection whose checkpoint was just deleted for rebuild is the
            furthest behind of all, and omitting it would hide precisely the
            case this exists for.
        replaying: The coordinator's own catch-up flag - see the module
            docstring for why this is required as well as a measured lag.
        now: The moment to measure checkpoint ages against. Passed in rather
            than read here so the judgement is a pure function of its inputs.
        stalled_after_seconds: How long a checkpoint may stay put while behind
            the head before the projection is called stalled.
    """
    unknown = CheckpointState(position=0)
    lagging: list[ProjectionLag] = []
    for name in projection_names:
        checkpoint = checkpoints.get(name, unknown)
        if checkpoint.position >= head_position:
            continue
        age = _age_seconds(checkpoint.updated_at, now)
        lagging.append(
            ProjectionLag(
                projection=name,
                position=checkpoint.position,
                lag=head_position - checkpoint.position,
                checkpoint_age_seconds=age,
                stalled=age is not None and age >= stalled_after_seconds,
            )
        )
    lagging.sort(key=lambda entry: (-entry.lag, entry.projection))

    return ReadModelLag(
        is_catching_up=replaying and bool(lagging),
        is_stalled=any(entry.stalled for entry in lagging),
        lag=lagging[0].lag if lagging else 0,
        head_position=head_position,
        lagging_projections=lagging,
    )
