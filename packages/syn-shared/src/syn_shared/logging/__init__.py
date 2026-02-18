"""Centralized logging infrastructure with DI support."""

from syn_shared.logging.config import LogConfig, LogLevel
from syn_shared.logging.interface import Logger, LoggerProtocol
from syn_shared.logging.structured import configure_logging, get_logger

__all__ = [
    "LogConfig",
    "LogLevel",
    "Logger",
    "LoggerProtocol",
    "configure_logging",
    "get_logger",
]
