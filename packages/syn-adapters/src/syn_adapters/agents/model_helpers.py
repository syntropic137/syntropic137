"""Model registry helper functions.

Extracted from models.py to reduce module complexity.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from syn_shared.env_constants import MODEL_HAIKU, MODEL_OPUS, MODEL_SONNET
from syn_shared.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def load_yaml(path: Path) -> dict[str, Any]:
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


def load_fallback_aliases() -> dict[str, str]:
    """Return fallback model aliases if primitives not available."""
    # Minimal fallback - uses actual existing API model names
    # Update these when new model versions are released
    # TODO: hardcoded values. Not maintainable. Should come from a central config.
    aliases: dict[str, str] = {
        # Sonnet aliases
        MODEL_SONNET: "claude-sonnet-4-5-20250514",
        "claude-sonnet": "claude-sonnet-4-5-20250514",
        # Opus aliases
        MODEL_OPUS: "claude-3-opus-20240229",
        "claude-opus": "claude-3-opus-20240229",
        # Haiku aliases - uses Claude 3.5 Haiku (current available)
        MODEL_HAIKU: "claude-3-5-haiku-20241022",
        "claude-haiku": "claude-3-5-haiku-20241022",
    }
    logger.warning("using_fallback_models", aliases=list(aliases.keys()))
    return aliases


def find_model_by_field(
    models: dict[str, dict[str, Any]], model: str
) -> dict[str, Any] | None:
    """Search models dict by api_name or alias fields."""
    for model_data in models.values():
        if model_data.get("api_name") == model or model_data.get("alias") == model:
            return model_data
    return None


def get_model_info(
    models: dict[str, dict[str, Any]], model: str
) -> dict[str, Any] | None:
    """Get full model information by name, alias, or ID.

    Args:
        models: The loaded models dict.
        model: Model name, alias, or ID

    Returns:
        Model configuration dict or None if not found
    """
    if model in models:
        return models[model]
    return find_model_by_field(models, model)


def get_context_window(
    models: dict[str, dict[str, Any]],
    model: str,
    default: int = 200_000,
) -> int:
    """Get the context window size for a model.

    Args:
        models: The loaded models dict.
        model: Model name or alias
        default: Default context window if not found

    Returns:
        Context window size in tokens
    """
    info = get_model_info(models, model)
    if not info:
        return default
    return info.get("capabilities", {}).get("context_window", default)


def list_models(
    models: dict[str, dict[str, Any]],
    provider: str | None = None,
) -> list[str]:
    """List available model IDs.

    Args:
        models: The loaded models dict.
        provider: Optional provider filter (e.g., "anthropic")

    Returns:
        List of model IDs
    """
    if provider:
        return [
            m_id for m_id, m_data in models.items() if m_data.get("provider") == provider
        ]
    return list(models.keys())


def list_aliases(
    aliases: dict[str, str],
    resolve_fn: Any,
) -> dict[str, str]:
    """Get all registered aliases and their resolved API names.

    Args:
        aliases: The raw aliases dict.
        resolve_fn: Callable that resolves an alias to an API name.

    Returns:
        Dict mapping alias -> resolved API name.
    """
    return {alias: resolve_fn(alias) for alias in aliases}
