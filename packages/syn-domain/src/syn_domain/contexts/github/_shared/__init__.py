"""Shared components for the GitHub context.

Contains:
- Value objects: InstallationId, InstallationToken
- Trigger evaluation types: TriggerMatchResult, TriggerDeferredResult
- Trigger evaluator protocol
- GitHub API client
- Trigger query store port and in-memory adapter
"""

from syn_domain.contexts.github._shared.github_client import (
    GitHubAppClient,
    GitHubAppClientError,
    JWTGenerationError,
    TokenFetchError,
    TokenResponse,
    get_github_client,
    reset_github_client,
)
from syn_domain.contexts.github._shared.trigger_evaluation_types import (
    TriggerDeferredResult,
    TriggerMatchResult,
)
from syn_domain.contexts.github._shared.trigger_evaluator import TriggerEvaluator
from syn_domain.contexts.github._shared.trigger_query_store import (
    InMemoryTriggerQueryStore,
    TriggerQueryStore,
    get_trigger_query_store,
    reset_trigger_store,
    set_trigger_store,
)
from syn_domain.contexts.github._shared.value_objects import (
    GitHubAccount,
    InstallationId,
    InstallationToken,
    RepositoryPermission,
)

__all__ = [
    "GitHubAccount",
    "GitHubAppClient",
    "GitHubAppClientError",
    "InMemoryTriggerQueryStore",
    "InstallationId",
    "InstallationToken",
    "JWTGenerationError",
    "RepositoryPermission",
    "TokenFetchError",
    "TokenResponse",
    "TriggerDeferredResult",
    "TriggerEvaluator",
    "TriggerMatchResult",
    "TriggerQueryStore",
    "get_github_client",
    "get_trigger_query_store",
    "reset_github_client",
    "reset_trigger_store",
    "set_trigger_store",
]
