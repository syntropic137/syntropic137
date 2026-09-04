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

WHAT "CATCHING UP" MEANS HERE, and why it is two conditions rather than one
--------------------------------------------------------------------------
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

KNOWN BLIND SPOT, stated rather than papered over: a projection wedged behind a
poison event - returning FAILURE forever, so its checkpoint never advances -
happens with the coordinator live, so condition 1 is false and this reports
``is_catching_up: false``. Its lag is still visible in ``lagging_projections``,
because that list is measured unconditionally, but it does not raise the flag or
degrade the mode. Detecting a stuck projection needs checkpoint STALENESS
(``updated_at`` not moving) rather than position, which is a different signal
and a different change.

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

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "ProjectionLag",
    "ReadModelLag",
    "measure_read_model_lag",
]


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


class ReadModelLag(BaseModel):
    """Whether the read path is behind, by how much, and who is furthest behind.

    Serialized straight into the ``subscription`` block of ``/health``, so every
    field name here is part of that endpoint's contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_catching_up: bool = Field(
        description="True while the coordinator is replaying history AND some projection has "
        "not reached the head. Queries against the read models may return stale "
        "data or 404 for recently written aggregates while this is true.",
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
        "entry is the answer to 'which one is holding this up'.",
    )


def measure_read_model_lag(
    *,
    head_position: int,
    checkpoints: Mapping[str, int],
    projection_names: Iterable[str],
    replaying: bool,
) -> ReadModelLag:
    """Judge the read path from a snapshot of checkpoint positions.

    Args:
        head_position: Global nonce of the newest event in the store.
        checkpoints: Projection name -> checkpoint global position, for the
            projections that currently HAVE a checkpoint.
        projection_names: Every registered projection. Names absent from
            ``checkpoints`` are treated as position 0 rather than skipped: a
            projection whose checkpoint was just deleted for rebuild is the
            furthest behind of all, and omitting it would hide precisely the
            case this exists for.
        replaying: The coordinator's own catch-up flag - see the module
            docstring for why this is required as well as a measured lag.
    """
    lagging = sorted(
        (
            ProjectionLag(
                projection=name,
                position=checkpoints.get(name, 0),
                lag=head_position - checkpoints.get(name, 0),
            )
            for name in projection_names
            if checkpoints.get(name, 0) < head_position
        ),
        key=lambda entry: (-entry.lag, entry.projection),
    )

    return ReadModelLag(
        is_catching_up=replaying and bool(lagging),
        lag=lagging[0].lag if lagging else 0,
        head_position=head_position,
        lagging_projections=lagging,
    )
