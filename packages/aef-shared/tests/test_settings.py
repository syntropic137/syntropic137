"""Tests for settings configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from aef_shared.settings import AppEnvironment, Settings, get_settings, reset_settings


@pytest.fixture(autouse=True)
def reset_settings_cache() -> None:
    """Reset settings cache before and after each test."""
    reset_settings()
    yield
    reset_settings()


@pytest.mark.integration
class TestSettings:
    """Test Settings class."""

    def test_default_values(self) -> None:
        """Default values should be sensible for development."""
        with patch.dict(os.environ, {}, clear=True):
            # Use _env_file=None to prevent reading from .env file
            settings = Settings(_env_file=None)

            assert settings.app_name == "agentic-engineering-framework"
            assert settings.app_environment == AppEnvironment.DEVELOPMENT
            assert settings.debug is False
            assert settings.database_url is None
            assert settings.log_level == "INFO"

    def test_environment_override(self) -> None:
        """Environment variables should override defaults."""
        env = {
            "APP_ENVIRONMENT": "production",
            "DEBUG": "true",
            "LOG_LEVEL": "ERROR",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

            assert settings.app_environment == AppEnvironment.PRODUCTION
            assert settings.debug is True
            assert settings.log_level == "ERROR"

    def test_database_url_validation(self) -> None:
        """Database URL should be validated as PostgreSQL DSN."""
        env = {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()
            assert settings.database_url is not None
            assert "postgresql" in str(settings.database_url)

    def test_secret_values_protected(self) -> None:
        """Secret values should not be exposed in repr."""
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-secret-key",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

            # Secret should not appear in string representation
            assert "sk-ant-secret-key" not in repr(settings)
            assert "sk-ant-secret-key" not in str(settings.anthropic_api_key)

            # But can be accessed explicitly
            assert settings.anthropic_api_key is not None
            assert settings.anthropic_api_key.get_secret_value() == "sk-ant-secret-key"


class TestComputedProperties:
    """Test computed properties."""

    def test_is_development(self) -> None:
        """is_development should be true in development."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}, clear=True):
            settings = Settings()
            assert settings.is_development is True
            assert settings.is_production is False
            assert settings.is_test is False

    def test_is_production(self) -> None:
        """is_production should be true in production."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}, clear=True):
            settings = Settings()
            assert settings.is_production is True
            assert settings.is_development is False

    def test_is_test(self) -> None:
        """is_test should be true in test environment."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}, clear=True):
            settings = Settings()
            assert settings.is_test is True

    def test_use_in_memory_storage(self) -> None:
        """In-memory storage only allowed in test environment."""
        # Test env without database = in-memory allowed
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}, clear=True):
            # Use _env_file=None to prevent reading from .env file
            settings = Settings(_env_file=None)
            assert settings.use_in_memory_storage is True

        # Development without database = NOT in-memory (should use Docker)
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}, clear=True):
            settings = Settings(_env_file=None)
            assert settings.use_in_memory_storage is False

        # With database configured = never in-memory
        with patch.dict(
            os.environ,
            {"APP_ENVIRONMENT": "test", "DATABASE_URL": "postgresql://localhost/db"},
            clear=True,
        ):
            settings = Settings(_env_file=None)
            assert settings.use_in_memory_storage is False


class TestGetSettings:
    """Test get_settings function."""

    def test_cached(self) -> None:
        """get_settings should return cached instance."""
        with patch.dict(os.environ, {}, clear=True):
            settings1 = get_settings()
            settings2 = get_settings()
            assert settings1 is settings2

    def test_reset_clears_cache(self) -> None:
        """reset_settings should clear the cache."""
        with patch.dict(os.environ, {}, clear=True):
            settings1 = get_settings()
            reset_settings()
            settings2 = get_settings()
            # Different instances after reset
            assert settings1 is not settings2
