"""Structured logging implementation using structlog."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

from syn_shared.logging.config import LogConfig, LogLevel
from syn_shared.logging.interface import Logger

if TYPE_CHECKING:
    from structlog.types import Processor

# Global config
_config: LogConfig | None = None


def _get_log_level(level: LogLevel) -> int:
    """Convert LogLevel enum to logging level int."""
    level_int: int = getattr(logging, level.value)
    return level_int


def configure_logging(config: LogConfig) -> None:
    """Configure structlog with the given configuration."""
    global _config
    _config = config

    # Build processor chain
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
    ]

    if config.include_timestamp:
        processors.append(structlog.processors.TimeStamper(fmt="iso"))

    processors.extend(
        [
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
        ]
    )

    if config.json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(_get_log_level(config.level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Logger:
    """Get a logger instance for the given name."""
    if _config is None:
        configure_logging(LogConfig())

    return Logger(structlog.get_logger(name))
