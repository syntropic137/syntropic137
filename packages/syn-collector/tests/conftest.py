"""Shared fixtures for syn-collector tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True, scope="session")
def _test_environment() -> Iterator[None]:
    """Ensure APP_ENVIRONMENT=test for all collector tests.

    Saves and restores the previous value to avoid leaking
    into other test suites in the same process.
    """
    previous_value = os.environ.get("APP_ENVIRONMENT")
    os.environ["APP_ENVIRONMENT"] = "test"
    try:
        yield
    finally:
        if previous_value is None:
            os.environ.pop("APP_ENVIRONMENT", None)
        else:
            os.environ["APP_ENVIRONMENT"] = previous_value
