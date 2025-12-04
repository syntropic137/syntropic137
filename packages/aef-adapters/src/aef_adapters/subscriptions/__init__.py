"""Event subscription service for projection updates.

This module provides the EventSubscriptionService which connects the event store
to projections using the pub/sub pattern.
"""

from aef_adapters.subscriptions.service import EventSubscriptionService

__all__ = ["EventSubscriptionService"]
