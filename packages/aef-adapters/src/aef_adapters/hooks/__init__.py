"""Hook integration for AEF.

Provides a wrapper around the agentic_hooks client with AEF settings integration,
plus validator registry for security validation of tool operations.

Usage:
    from aef_adapters.hooks import get_hook_client, ValidatorRegistry

    # Get configured hook client
    async with get_hook_client() as client:
        await client.emit(HookEvent(...))

    # Use validators
    registry = ValidatorRegistry()
    result = registry.validate("Bash", {"command": "ls -la"})
"""

from aef_adapters.hooks.client import AEFHookClient, get_hook_client
from aef_adapters.hooks.validators import ValidationResult, ValidatorRegistry

__all__ = [
    "AEFHookClient",
    "ValidationResult",
    "ValidatorRegistry",
    "get_hook_client",
]
