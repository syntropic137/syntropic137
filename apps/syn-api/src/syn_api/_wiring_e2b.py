"""The E2B executor's sandbox client, wired to the Outage Breaker (#1917).

Kept beside ``_wiring`` so ``build_workspace_service`` stays one call; split
out for the file-size fitness limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_api._wiring import get_execution_run_queue
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from agentic_isolation.providers.e2b_client import E2BSandboxClient


def e2b_client_with_breaker() -> E2BSandboxClient | None:
    """The E2B executor's sandbox client, its creates feeding the Outage Breaker (#1917).

    None (the provider's own SDK client) with the Run Queue off: there is no
    budget row to disable claims on.
    """
    settings = get_settings()
    if not settings.execution.run_queue_enabled or settings.e2b.api_key is None:
        return None
    from datetime import timedelta

    from agentic_isolation.providers.e2b_client import SdkE2BClient

    from syn_adapters.execution_host.outage_breaker import OutageBreaker
    from syn_adapters.workspace_backends.e2b.breaker_client import BreakerE2BClient
    from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID, host_labels

    breaker = OutageBreaker(
        get_execution_run_queue,
        host_labels()[LABEL_HOST_ID],  # the host id the ExecutionHost registers (D5)
        threshold=settings.e2b.breaker_failures,
        cooldown=timedelta(seconds=settings.e2b.breaker_cooldown_s),
    )
    return BreakerE2BClient(SdkE2BClient(api_key=settings.e2b.api_key.get_secret_value()), breaker)
