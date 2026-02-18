"""Test infrastructure constants.

This is the SINGLE SOURCE OF TRUTH for test environment configuration.
All test fixtures and CI configs MUST use these constants.

If you change port mappings:
1. Update constants here
2. Update docker/docker-compose.test.yaml
3. Update .github/workflows/ci.yml
"""

from __future__ import annotations

# =============================================================================
# Environment Variable Names
# =============================================================================
# Use these instead of hardcoded strings in fixtures and CI

# Database connection (full URL or components)
ENV_TEST_DATABASE_URL = "TEST_DATABASE_URL"
ENV_TEST_TIMESCALEDB_HOST = "TEST_TIMESCALEDB_HOST"
ENV_TEST_TIMESCALEDB_PORT = "TEST_TIMESCALEDB_PORT"

# EventStore gRPC
ENV_TEST_EVENTSTORE_HOST = "TEST_EVENTSTORE_HOST"
ENV_TEST_EVENTSTORE_PORT = "TEST_EVENTSTORE_PORT"

# Other services
ENV_TEST_COLLECTOR_URL = "TEST_COLLECTOR_URL"
ENV_TEST_MINIO_URL = "TEST_MINIO_URL"
ENV_TEST_REDIS_URL = "TEST_REDIS_URL"

# =============================================================================
# Port Mappings
# =============================================================================
# Test stack uses offset +10000 from dev to allow parallel running

# Test stack ports (just test-stack)
TEST_STACK_PORTS = {
    "timescaledb": 15432,
    "eventstore": 55051,
    "collector": 18080,
    "minio_api": 19000,
    "minio_console": 19001,
    "redis": 16379,
}

# Dev stack ports (for reference, used by just dev)
DEV_STACK_PORTS = {
    "timescaledb": 5432,
    "eventstore": 50051,
    "collector": 8080,
    "minio_api": 9000,
    "minio_console": 9001,
    "redis": 6379,
}

# =============================================================================
# Default Connection Values
# =============================================================================
# Used when env vars are not set

DEFAULT_DB_USER = "syn"
DEFAULT_DB_PASSWORD = "syn_dev_password"  # Not a real production password
DEFAULT_DB_NAME = "syn"  # Must match docker-compose.yaml
DEFAULT_HOST = "localhost"


def get_test_timescaledb_url(
    host: str = DEFAULT_HOST,
    port: int = TEST_STACK_PORTS["timescaledb"],
    user: str = DEFAULT_DB_USER,
    password: str = DEFAULT_DB_PASSWORD,
    database: str = DEFAULT_DB_NAME,
) -> str:
    """Build TimescaleDB connection URL for tests."""
    return f"postgres://{user}:{password}@{host}:{port}/{database}"


__all__ = [
    "DEFAULT_DB_NAME",
    "DEFAULT_DB_PASSWORD",
    "DEFAULT_DB_USER",
    "DEFAULT_HOST",
    "DEV_STACK_PORTS",
    "ENV_TEST_COLLECTOR_URL",
    "ENV_TEST_DATABASE_URL",
    "ENV_TEST_EVENTSTORE_HOST",
    "ENV_TEST_EVENTSTORE_PORT",
    "ENV_TEST_MINIO_URL",
    "ENV_TEST_REDIS_URL",
    "ENV_TEST_TIMESCALEDB_HOST",
    "ENV_TEST_TIMESCALEDB_PORT",
    "TEST_STACK_PORTS",
    "get_test_timescaledb_url",
]
