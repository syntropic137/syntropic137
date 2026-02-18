"""Tests for RecordOperation handler - VSA compliance."""

import pytest

from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
    RecordOperationCommand,
)

from .RecordOperationHandler import RecordOperationHandler


@pytest.mark.unit
def test_handler_exists() -> None:
    """VSA requires handler exists."""
    assert RecordOperationHandler is not None


@pytest.mark.unit
def test_command_exists() -> None:
    """VSA requires command exists."""
    assert RecordOperationCommand is not None


# TODO(#55): Add integration tests
