"""Pytest configuration for all tests in the AEF project.

Sets APP_ENVIRONMENT=test to ensure in-memory storage is used during testing.
"""

from __future__ import annotations

import os

# Set test environment BEFORE any imports that might read settings
os.environ["APP_ENVIRONMENT"] = "test"


import pytest

from aef_adapters.storage import reset_storage


@pytest.fixture(autouse=True)
def reset_storage_between_tests() -> None:
    """Reset all storage before each test for isolation."""
    reset_storage()
