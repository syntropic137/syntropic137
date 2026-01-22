"""Tests for CompleteSession handler - VSA compliance."""

import pytest

from aef_domain.contexts.sessions.domain.commands.CompleteSessionCommand import (
    CompleteSessionCommand,
)

from .CompleteSessionHandler import CompleteSessionHandler


@pytest.mark.unit
def test_handler_exists() -> None:
    """VSA requires handler exists."""
    assert CompleteSessionHandler is not None


@pytest.mark.unit
def test_command_exists() -> None:
    """VSA requires command exists."""
    assert CompleteSessionCommand is not None


# TODO(#55): Add integration tests
