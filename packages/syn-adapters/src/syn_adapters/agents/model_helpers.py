"""Model registry helper functions.

Extracted from models.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syn_shared.env_constants import MODEL_HAIKU, MODEL_OPUS, MODEL_SONNET
from syn_shared.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

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


def find_model_by_field(models: dict[str, dict[str, Any]], model: str) -> dict[str, Any] | None:
    """Search models dict by api_name or alias fields."""
    for model_data in models.values():
        if model_data.get("api_name") == model or model_data.get("alias") == model:
            return model_data
    return None


def get_model_info(models: dict[str, dict[str, Any]], model: str) -> dict[str, Any] | None:
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
        return [m_id for m_id, m_data in models.items() if m_data.get("provider") == provider]
    return list(models.keys())


def list_aliases(
    aliases: dict[str, str],
    resolve_fn: Any,  # noqa: ANN401
) -> dict[str, str]:
    """Get all registered aliases and their resolved API names.

    Args:
        aliases: The raw aliases dict.
        resolve_fn: Callable that resolves an alias to an API name.

    Returns:
        Dict mapping alias -> resolved API name.
    """
    return {alias: resolve_fn(alias) for alias in aliases}


def load_provider(
    provider_dir: Path,
    providers: dict[str, dict[str, Any]],
    models: dict[str, dict[str, Any]],
    aliases: dict[str, str],
    model_id_to_api_name: dict[str, str],
) -> None:
    """Load a single provider directory's config and model files."""
    provider_id = provider_dir.name
    config_path = provider_dir / "config.yaml"
    if config_path.exists():
        providers[provider_id] = load_yaml(config_path)

    for model_file in provider_dir.glob("*.yaml"):
        if model_file.name == "config.yaml":
            continue
        register_model_file(model_file, models, aliases, model_id_to_api_name)


def register_model_file(
    model_file: Path,
    models: dict[str, dict[str, Any]],
    aliases: dict[str, str],
    model_id_to_api_name: dict[str, str],
) -> None:
    """Register a single model YAML file."""
    model_data = load_yaml(model_file)
    if not model_data:
        return

    model_id = model_data.get("id", model_file.stem)
    models[model_id] = model_data
    register_model_aliases(model_id, model_data, aliases, model_id_to_api_name)


def register_model_aliases(
    model_id: str,
    model_data: dict[str, Any],
    aliases: dict[str, str],
    model_id_to_api_name: dict[str, str],
) -> None:
    """Register aliases for a model if it has an api_name."""
    api_name = model_data.get("api_name")
    if not api_name:
        return
    aliases[model_id] = api_name
    model_id_to_api_name[model_id] = api_name
    if alias := model_data.get("alias"):
        aliases[alias] = api_name


def register_current_model_aliases(
    providers: dict[str, dict[str, Any]],
    aliases: dict[str, str],
    model_id_to_api_name: dict[str, str],
) -> None:
    """Create shorthand aliases from provider current_models configs."""
    for provider_id, config in providers.items():
        for model_type, model_id in config.get("current_models", {}).items():
            register_provider_alias(
                provider_id,
                str(model_type),
                model_id_to_api_name.get(model_id, model_id),
                aliases,
            )


def register_provider_alias(
    provider_id: str,
    model_type: str,
    api_name: str | None,
    aliases: dict[str, str],
) -> None:
    """Register aliases for a single provider/model-type combination."""
    if api_name is None:
        return
    resolved = str(api_name)
    if provider_id == "anthropic":
        aliases[model_type] = resolved
        aliases[f"claude-{model_type}"] = resolved
    else:
        aliases[f"{provider_id}/{model_type}"] = resolved
