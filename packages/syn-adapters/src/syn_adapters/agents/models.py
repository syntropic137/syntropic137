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

from syn_shared.logging import get_logger

logger = get_logger(__name__)

# Path to agentic-primitives models directory
# Navigate from: packages/syn-adapters/src/syn_adapters/agents/models.py
# To: lib/agentic-primitives/providers/models
_PRIMITIVES_MODELS_PATH = (
    Path(__file__).parents[5] / "lib" / "agentic-primitives" / "providers" / "models"
)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file safely."""
    try:
        import yaml
    except ImportError:
        logger.warning("pyyaml_not_installed")
        return {}

    try:
        with path.open() as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("failed_to_load_yaml", path=str(path), error=str(e))
        return {}


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

        # First pass: Load all individual model files to get api_names
        model_id_to_api_name: dict[str, str] = {}

        for provider_dir in _PRIMITIVES_MODELS_PATH.iterdir():
            if not provider_dir.is_dir():
                continue

            provider_id = provider_dir.name

            # Load provider config
            config_path = provider_dir / "config.yaml"
            if config_path.exists():
                config = _load_yaml(config_path)
                self._providers[provider_id] = config

            # Load individual model files
            for model_file in provider_dir.glob("*.yaml"):
                if model_file.name == "config.yaml":
                    continue

                model_data = _load_yaml(model_file)
                if not model_data:
                    continue

                model_id = model_data.get("id", model_file.stem)
                self._models[model_id] = model_data

                # Register model aliases
                if api_name := model_data.get("api_name"):
                    # Map model_id to api_name
                    self._aliases[model_id] = api_name
                    model_id_to_api_name[model_id] = api_name
                    # Map explicit alias if present
                    if alias := model_data.get("alias"):
                        self._aliases[alias] = api_name

        # Second pass: Create simple aliases from current_models that resolve to API names
        for provider_id, config in self._providers.items():
            current_models = config.get("current_models", {})
            for model_type, model_id in current_models.items():
                # Get the API name for this model
                api_name = model_id_to_api_name.get(model_id, model_id)

                # Simple aliases that work across versions:
                # - "sonnet" -> latest sonnet API name
                # - "claude-sonnet" -> latest sonnet API name
                # - "opus" -> latest opus API name
                # - "claude-opus" -> latest opus API name
                if provider_id == "anthropic":
                    # Short alias (e.g., "sonnet")
                    self._aliases[model_type] = api_name
                    # Claude-prefixed alias (e.g., "claude-sonnet")
                    self._aliases[f"claude-{model_type}"] = api_name
                else:
                    # Other providers: use provider/type format
                    self._aliases[f"{provider_id}/{model_type}"] = api_name

        logger.debug(
            "models_loaded",
            providers=list(self._providers.keys()),
            models=len(self._models),
            aliases=len(self._aliases),
        )

    def _load_fallback(self) -> None:
        """Load fallback model definitions if primitives not available."""
        # Minimal fallback - uses actual existing API model names
        # Update these when new model versions are released
        # TODO: hardcoded values. Not maintainable. Should come from a central config.
        self._aliases = {
            # Sonnet aliases
            "sonnet": "claude-sonnet-4-5-20250514",
            "claude-sonnet": "claude-sonnet-4-5-20250514",
            # Opus aliases
            "opus": "claude-3-opus-20240229",
            "claude-opus": "claude-3-opus-20240229",
            # Haiku aliases - uses Claude 3.5 Haiku (current available)
            "haiku": "claude-3-5-haiku-20241022",
            "claude-haiku": "claude-3-5-haiku-20241022",
        }
        logger.warning("using_fallback_models", aliases=list(self._aliases.keys()))

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
        # Try direct lookup
        if model in self._models:
            return self._models[model]

        # Try resolving alias to model ID
        for _model_id, model_data in self._models.items():
            if model_data.get("api_name") == model or model_data.get("alias") == model:
                return model_data

        return None

    def get_context_window(self, model: str) -> int:
        """Get the context window size for a model.

        Args:
            model: Model name or alias

        Returns:
            Context window size in tokens (default 200000)
        """
        info = self.get_model_info(model)
        if info:
            return info.get("capabilities", {}).get("context_window", 200_000)
        return 200_000

    def list_models(self, provider: str | None = None) -> list[str]:
        """List available model IDs.

        Args:
            provider: Optional provider filter (e.g., "anthropic")

        Returns:
            List of model IDs
        """
        if provider:
            return [
                m_id for m_id, m_data in self._models.items() if m_data.get("provider") == provider
            ]
        return list(self._models.keys())

    def list_aliases(self) -> dict[str, str]:
        """Get all registered aliases and their resolved API names."""
        return {alias: self.resolve(alias) for alias in self._aliases}


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
