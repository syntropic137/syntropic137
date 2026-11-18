"""ExecutionLifecycleSinkPort adapters for the orchestration context (#1661).

``WebhookExecutionLifecycleSink`` POSTs each notice, signed, to one URL. Which
sink runs, and with what URL and secret, is wiring and is not decided here.
"""

from syn_adapters.execution_lifecycle.webhook_sink import (
    IDEMPOTENCY_KEY_HEADER,
    SIGNATURE_HEADER,
    LifecycleNoticeUndeliveredError,
    WebhookExecutionLifecycleSink,
)

__all__ = [
    "IDEMPOTENCY_KEY_HEADER",
    "SIGNATURE_HEADER",
    "LifecycleNoticeUndeliveredError",
    "WebhookExecutionLifecycleSink",
]
