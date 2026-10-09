"""Configuration for UI Feedback API."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str | None = None  # If None, uses in-memory storage
    use_memory_storage: bool = False  # Force in-memory storage even with database_url

    # File upload limits
    max_file_size: int = 10 * 1024 * 1024  # 10MB default

    # CORS
    cors_origins: str = "*"

    # Server
    host: str = "0.0.0.0"
    port: int = 8001

    model_config = {
        "env_prefix": "UI_FEEDBACK_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # This package is mounted inside syn-api and shares its .env. Without
        # this, pydantic-settings rejects every SYN_* key in that file as an
        # extra input and create_app() fails on any machine with a .env.
        "extra": "ignore",
    }


settings = Settings()
