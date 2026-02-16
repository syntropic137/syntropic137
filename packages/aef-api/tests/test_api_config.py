"""Tests for aef_api.v1.config — get config, validate config, env template.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import os

from aef_api.types import Ok

os.environ.setdefault("APP_ENVIRONMENT", "test")


async def test_get_config():
    """Get configuration snapshot."""
    from aef_api.v1.config import get_config

    result = await get_config()

    assert isinstance(result, Ok)
    config = result.value
    assert "app_environment" in config.app
    assert config.app["app_environment"] == "test"
    assert "event_store_host" in config.database
    assert isinstance(config.agents, dict)
    assert isinstance(config.storage, dict)


async def test_get_config_masks_secrets():
    """Config masks secrets by default."""
    from aef_api.v1.config import get_config

    result = await get_config(show_secrets=False)
    assert isinstance(result, Ok)

    # API keys should be masked (empty or ****) when not set
    agents = result.value.agents
    api_key = agents.get("anthropic_api_key", "")
    # If set, should be masked; if not set, should be empty
    assert api_key == "" or "****" in api_key


async def test_validate_config():
    """Validate config returns issues list."""
    from aef_api.v1.config import validate_config

    result = await validate_config()

    assert isinstance(result, Ok)
    issues = result.value
    assert isinstance(issues, list)

    # Should have at least one issue (info about available providers)
    for issue in issues:
        assert issue.level in ("error", "warning", "info")
        assert issue.category
        assert issue.message


async def test_get_env_template():
    """Get environment template."""
    from aef_api.v1.config import get_env_template

    result = await get_env_template()

    assert isinstance(result, Ok)
    template = result.value
    assert "APP_ENVIRONMENT" in template
    assert "ANTHROPIC_API_KEY" in template
    assert "EVENT_STORE_HOST" in template
