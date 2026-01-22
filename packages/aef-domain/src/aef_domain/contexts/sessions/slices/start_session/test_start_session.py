"""Tests for StartSession handler - VSA compliance."""

import pytest

from aef_domain.contexts.sessions.domain.commands.StartSessionCommand import StartSessionCommand

from .StartSessionHandler import StartSessionHandler


@pytest.mark.unit
def test_handler_exists() -> None:
    """VSA requires handler exists."""
    assert StartSessionHandler is not None


@pytest.mark.unit
def test_command_exists() -> None:
    """VSA requires command exists."""
    assert StartSessionCommand is not None


# TODO(#55): Add integration tests
