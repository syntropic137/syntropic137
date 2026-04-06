"""Tests for syn_api.services.config — get config, validate config, env template.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import os

from syn_api.types import Ok

os.environ.setdefault("APP_ENVIRONMENT", "test")


async def test_get_config():
    """Get configuration snapshot."""
    from syn_api.services.config import get_config

    result = await get_config()

    assert isinstance(result, Ok)
    config = result.value
    assert "app_environment" in config.app
    assert config.app["app_environment"] == "test"
    assert "event_store_host" in config.database
    assert isinstance(config.storage, dict)


async def test_validate_config():
    """Validate config returns issues list."""
    from syn_api.services.config import validate_config

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
    from syn_api.services.config import get_env_template

    result = await get_env_template()

    assert isinstance(result, Ok)
    template = result.value
    assert "APP_ENVIRONMENT" in template
    assert "EVENT_STORE_HOST" in template
    assert "ANTHROPIC_API_KEY" in template or "CLAUDE_CODE_OAUTH_TOKEN" in template
