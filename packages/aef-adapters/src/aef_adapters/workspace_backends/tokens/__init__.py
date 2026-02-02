"""Token adapters for workspace bounded context.

This module provides adapters for token vending and injection:
- TokenVendingServiceAdapter: Wraps aef-tokens TokenVendingService
- SidecarTokenInjectionAdapter: Injects tokens via sidecar proxy

These adapters implement the port interfaces from aef_domain.contexts.orchestration.

Usage:
    from aef_adapters.workspace_backends.tokens import (
        TokenVendingServiceAdapter,
        SidecarTokenInjectionAdapter,
    )

    # Create vending adapter
    vending = TokenVendingServiceAdapter(token_service)

    # Create injection adapter (composes vending + sidecar)
    injection = SidecarTokenInjectionAdapter(vending, sidecar_adapter)

See ADR-022: Secure Token Architecture
"""

from aef_adapters.workspace_backends.tokens.token_injection_adapter import (
    SidecarTokenInjectionAdapter,
)
from aef_adapters.workspace_backends.tokens.token_vending_adapter import (
    TokenVendingServiceAdapter,
)

__all__ = [
    "SidecarTokenInjectionAdapter",
    "TokenVendingServiceAdapter",
]
