"""Logger interface for dependency injection."""

from __future__ import annotations

from typing import Any, Protocol


class LoggerProtocol(Protocol):
    """Protocol for logger implementations."""

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        ...

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        ...

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        ...

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        ...

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message."""
        ...

    def bind(self, **kwargs: Any) -> LoggerProtocol:
        """Return a new logger with bound context."""
        ...


class Logger:
    """Wrapper around structlog logger implementing LoggerProtocol."""

    def __init__(self, logger: LoggerProtocol) -> None:
        """Initialize with a structlog logger."""
        self._logger = logger

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self._logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self._logger.error(message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message."""
        self._logger.critical(message, **kwargs)

    def bind(self, **kwargs: Any) -> Logger:
        """Return a new logger with bound context."""
        return Logger(self._logger.bind(**kwargs))
