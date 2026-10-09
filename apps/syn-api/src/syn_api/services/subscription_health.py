"""Renders the read-path block of /health from what the subscription reports.

Split out of `lifecycle` (#1737): the coordinator's own facts - running, held,
halted - must be published whether or not the lag and dropped-start probes
succeed, so the block is built in two places there and once here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_api.services.read_model_status import rebuilding_read_models
from syn_api.types import HeldProjectionHealth, SubscriptionHealth

if TYPE_CHECKING:
    from syn_adapters.subscriptions.coordinator_service import SubscriptionServiceStatus
    from syn_adapters.subscriptions.read_model_lag import ReadModelLag
    from syn_adapters.subscriptions.unapplied_starts import UnappliedStart
    from syn_api.types import SubscriptionHealthStatus


def render_subscription_health(
    sub_status: SubscriptionServiceStatus,
    status: SubscriptionHealthStatus,
    lag: ReadModelLag | None = None,
    unapplied: list[UnappliedStart] | None = None,
) -> SubscriptionHealth:
    """The block, with the probe results when there are any."""
    return SubscriptionHealth(
        status=status,
        running=sub_status.running,
        projection_count=sub_status.projection_count,
        realtime_enabled=sub_status.realtime_enabled,
        held_projections=[
            HeldProjectionHealth(
                projection=entry.projection_name,
                event_type=entry.event_type,
                global_nonce=entry.global_nonce,
            )
            for entry in sub_status.held_projections
        ],
        halted_at=sub_status.halted_at,
        unapplied_starts=unapplied,
        rebuilding_read_models=rebuilding_read_models(lag) if lag is not None else None,
        **(lag.model_dump() if lag is not None else {}),
    )
