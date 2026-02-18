"""Pytest configuration for all tests in the Syntropic137 project.

Sets APP_ENVIRONMENT=test to ensure in-memory storage is used during testing.

Test Infrastructure (ADR-034):
    - test_infrastructure: Auto-detects test-stack or uses testcontainers
    - db_pool: Database connection pool
"""

from __future__ import annotations

import os

# Set test environment BEFORE any imports that might read settings
os.environ["APP_ENVIRONMENT"] = "test"


import pytest

from syn_adapters.storage import reset_storage

# Register test infrastructure fixtures (ADR-034)
pytest_plugins = [
    "syn_tests.fixtures.infrastructure",
]


@pytest.fixture(autouse=True)
def reset_storage_between_tests() -> None:
    """Reset all storage before each test for isolation."""
    reset_storage()
