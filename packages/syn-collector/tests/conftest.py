"""Shared fixtures for syn-collector tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _test_environment() -> None:
    """Ensure APP_ENVIRONMENT=test for all collector tests.

    This prevents InMemoryObservabilityStore from raising
    InMemoryStorageError during test runs.
    """
    os.environ["APP_ENVIRONMENT"] = "test"
