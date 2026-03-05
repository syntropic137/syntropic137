"""Event subscription services for projection updates.

This module provides subscription services that connect the event store
to projections using the pub/sub pattern.

Two implementations are available:
- EventSubscriptionService: Legacy service with global checkpoint (deprecated)
- CoordinatorSubscriptionService: New service using SubscriptionCoordinator (ADR-014)
"""

from syn_adapters.subscriptions.coordinator_service import (
    CoordinatorSubscriptionService,
    RealTimeProjectionAdapter,
    create_coordinator_service,
)
from syn_adapters.subscriptions.position_checkpoint import PositionCheckpoint
from syn_adapters.subscriptions.service import EventSubscriptionService

__all__ = [
    "CoordinatorSubscriptionService",
    "EventSubscriptionService",
    "PositionCheckpoint",
    "RealTimeProjectionAdapter",
    "create_coordinator_service",
]
