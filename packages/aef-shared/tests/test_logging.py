"""Tests for logging module."""

import pytest

from aef_shared.logging import (
    LogConfig,
    Logger,
    LogLevel,
    configure_logging,
    get_logger,
)


@pytest.mark.unit
class TestLogConfig:
    """Test LogConfig model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = LogConfig()
        assert config.level == LogLevel.INFO
        assert config.json_format is False
        assert config.include_timestamp is True
        assert config.include_module is True
        assert config.include_correlation_id is True

    def test_custom_config(self):
        """Test custom configuration values."""
        config = LogConfig(
            level=LogLevel.DEBUG,
            json_format=True,
            include_timestamp=False,
        )
        assert config.level == LogLevel.DEBUG
        assert config.json_format is True
        assert config.include_timestamp is False


class TestLogger:
    """Test Logger implementation."""

    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a Logger instance."""
        configure_logging(LogConfig())
        logger = get_logger(__name__)
        assert isinstance(logger, Logger)

    def test_logger_methods_callable(self):
        """Test that logger has all required methods."""
        logger = get_logger(__name__)

        # These should not raise
        logger.debug("debug message")
        logger.info("info message")
        logger.warning("warning message")
        logger.error("error message")
        logger.critical("critical message")

    def test_logger_bind_returns_new_logger(self):
        """Test that bind returns a new logger instance."""
        logger = get_logger(__name__)
        bound_logger = logger.bind(request_id="123")
        assert isinstance(bound_logger, Logger)
        assert bound_logger is not logger

    def test_logger_accepts_kwargs(self):
        """Test that logger methods accept keyword arguments."""
        logger = get_logger(__name__)
        logger.info("message", key="value", number=42)
        logger.error("error", exception_type="ValueError", details={"foo": "bar"})


class TestConfigureLogging:
    """Test configure_logging function."""

    def test_configure_with_json_format(self):
        """Test configuring with JSON format."""
        config = LogConfig(json_format=True)
        configure_logging(config)
        logger = get_logger(__name__)
        logger.info("test message")

    def test_configure_with_debug_level(self):
        """Test configuring with DEBUG level."""
        config = LogConfig(level=LogLevel.DEBUG)
        configure_logging(config)
        logger = get_logger(__name__)
        logger.debug("debug message")
