"""Model registry - loads model definitions from agentic-primitives.

This module dynamically loads model configurations from the agentic-primitives
library, ensuring we always use the latest model definitions without hardcoding.

Usage:
    from syn_adapters.agents.models import get_model_registry

    registry = get_model_registry()
    api_name = registry.resolve("claude-sonnet")  # -> "claude-sonnet-4-5-20250929"
    api_name = registry.resolve("sonnet")  # -> "claude-sonnet-4-5-20250929"
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from syn_adapters.agents.model_helpers import (
    find_model_by_field,
    get_context_window,
    get_model_info,
    list_aliases,
    list_models,
    load_fallback_aliases,
    load_provider,
    register_current_model_aliases,
)
from syn_shared.logging import get_logger

logger = get_logger(__name__)

# Path to agentic-primitives models directory
# Navigate from: packages/syn-adapters/src/syn_adapters/agents/models.py
# To: lib/agentic-primitives/providers/models
_PRIMITIVES_MODELS_PATH = (
    Path(__file__).parents[5] / "lib" / "agentic-primitives" / "providers" / "models"
)


class ModelRegistry:
    """Registry for AI model configurations loaded from agentic-primitives."""

    def __init__(self) -> None:
        """Initialize the model registry by loading from primitives."""
        self._providers: dict[str, dict[str, Any]] = {}
        self._models: dict[str, dict[str, Any]] = {}
        self._aliases: dict[str, str] = {}
        self._load_models()

    def _load_models(self) -> None:
        """Load all model definitions from agentic-primitives."""
        if not _PRIMITIVES_MODELS_PATH.exists():
            logger.warning(
                "primitives_models_not_found",
                path=str(_PRIMITIVES_MODELS_PATH),
            )
            self._load_fallback()
            return

        model_id_to_api_name: dict[str, str] = {}
        for provider_dir in _PRIMITIVES_MODELS_PATH.iterdir():
            if not provider_dir.is_dir():
                continue
            load_provider(
                provider_dir,
                self._providers,
                self._models,
                self._aliases,
                model_id_to_api_name,
            )

        register_current_model_aliases(self._providers, self._aliases, model_id_to_api_name)

        logger.debug(
            "models_loaded",
            providers=list(self._providers.keys()),
            models=len(self._models),
            aliases=len(self._aliases),
        )

    def _load_fallback(self) -> None:
        """Load fallback model definitions if primitives not available."""
        self._aliases = load_fallback_aliases()

    def resolve(self, model: str) -> str:
        """Resolve a model alias to its API name.
        # TODO: hardcoded values. Not maintainable. Should come from a central config.
        Simple aliases resolve directly to API names:
        - "sonnet" -> "claude-sonnet-4-5-20250929"
        - "claude-sonnet" -> "claude-sonnet-4-5-20250929"
        - "opus" -> "claude-opus-4-1-20250630"
        - "claude-opus" -> "claude-opus-4-1-20250630"

        Args:
            model: Model name, alias, or API name

        Returns:
            The actual API model name to use with the provider
        """
        # Direct alias lookup - all aliases now resolve directly to API names
        if model in self._aliases:
            return self._aliases[model]

        # Already an API name, return as-is
        return model

    def get_model_info(self, model: str) -> dict[str, Any] | None:
        """Get full model information.

        Args:
            model: Model name, alias, or ID

        Returns:
            Model configuration dict or None if not found
        """
        return get_model_info(self._models, model)

    def _find_model_by_field(self, model: str) -> dict[str, Any] | None:
        """Search models by api_name or alias fields."""
        return find_model_by_field(self._models, model)

    _DEFAULT_CONTEXT_WINDOW = 200_000

    def get_context_window(self, model: str) -> int:
        """Get the context window size for a model.

        Args:
            model: Model name or alias

        Returns:
            Context window size in tokens (default 200000)
        """
        return get_context_window(self._models, model, self._DEFAULT_CONTEXT_WINDOW)

    def list_models(self, provider: str | None = None) -> list[str]:
        """List available model IDs.

        Args:
            provider: Optional provider filter (e.g., "anthropic")

        Returns:
            List of model IDs
        """
        return list_models(self._models, provider)

    def list_aliases(self) -> dict[str, str]:
        """Get all registered aliases and their resolved API names."""
        return list_aliases(self._aliases, self.resolve)


@lru_cache(maxsize=1)
def get_model_registry() -> ModelRegistry:
    """Get the cached model registry instance."""
    return ModelRegistry()


def resolve_model(model: str) -> str:
    """Convenience function to resolve a model alias.

    Args:
        model: Model name or alias

    Returns:
        API model name
    """
    return get_model_registry().resolve(model)
