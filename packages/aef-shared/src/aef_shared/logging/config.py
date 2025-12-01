"""Logging configuration."""

from enum import Enum

from pydantic import BaseModel, Field


class LogLevel(str, Enum):
    """Log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogConfig(BaseModel):
    """Configuration for logging."""

    level: LogLevel = Field(default=LogLevel.INFO, description="Default log level")
    json_format: bool = Field(default=False, description="Use JSON format for logs")
    include_timestamp: bool = Field(default=True, description="Include timestamp in logs")
    include_module: bool = Field(default=True, description="Include module name in logs")
    include_correlation_id: bool = Field(default=True, description="Include correlation ID in logs")

    model_config = {"frozen": True}
