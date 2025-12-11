"""Event subscription services for projection updates.

This module provides subscription services that connect the event store
to projections using the pub/sub pattern.

Two implementations are available:
- EventSubscriptionService: Legacy service with global checkpoint (deprecated)
- CoordinatorSubscriptionService: New service using SubscriptionCoordinator (ADR-014)
"""

from aef_adapters.subscriptions.coordinator_service import (
    CoordinatorSubscriptionService,
    RealTimeProjectionAdapter,
    create_coordinator_service,
)
from aef_adapters.subscriptions.service import EventSubscriptionService

__all__ = [
    "CoordinatorSubscriptionService",
    "EventSubscriptionService",
    "RealTimeProjectionAdapter",
    "create_coordinator_service",
]
