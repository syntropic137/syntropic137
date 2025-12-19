"""Tests for cancellation module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from aef_agent_runner.cancellation import (
    CancellationError,
    CancellationToken,
    check_cancellation,
)


@pytest.mark.unit
class TestCancellationToken:
    """Tests for CancellationToken class."""

    def test_not_cancelled_initially(self, tmp_path: Path) -> None:
        """Token should not be cancelled initially."""
        cancel_path = tmp_path / ".cancel"
        token = CancellationToken(cancel_path)

        assert token.is_cancelled is False

    def test_cancelled_when_file_exists(self, tmp_path: Path) -> None:
        """Token should be cancelled when file exists."""
        cancel_path = tmp_path / ".cancel"
        cancel_path.touch()  # Create the file

        token = CancellationToken(cancel_path)

        assert token.is_cancelled is True

    def test_cancel_method(self, tmp_path: Path) -> None:
        """cancel() should mark token as cancelled."""
        cancel_path = tmp_path / ".cancel"
        token = CancellationToken(cancel_path)

        token.cancel()

        assert token.is_cancelled is True

    def test_context_manager(self, tmp_path: Path) -> None:
        """Should work as context manager."""
        cancel_path = tmp_path / ".cancel"

        with CancellationToken(cancel_path) as token:
            assert token.is_cancelled is False

    @pytest.mark.asyncio
    async def test_async_context_manager(self, tmp_path: Path) -> None:
        """Should work as async context manager."""
        cancel_path = tmp_path / ".cancel"

        async with CancellationToken(cancel_path, poll_interval=0.1) as token:
            assert token.is_cancelled is False

            # Create cancel file
            cancel_path.touch()

            # Wait a bit for polling to detect
            await asyncio.sleep(0.2)

            assert token.is_cancelled is True

    @pytest.mark.asyncio
    async def test_polling_detects_file(self, tmp_path: Path) -> None:
        """Polling should detect cancel file creation."""
        cancel_path = tmp_path / ".cancel"
        token = CancellationToken(cancel_path, poll_interval=0.05)

        await token.start_polling()

        try:
            # Initially not cancelled
            assert token.is_cancelled is False

            # Create the file
            cancel_path.touch()

            # Wait for polling to detect
            await asyncio.sleep(0.1)

            assert token.is_cancelled is True
        finally:
            await token.stop_polling()


class TestCheckCancellation:
    """Tests for check_cancellation function."""

    def test_raises_when_cancelled(self, tmp_path: Path) -> None:
        """Should raise CancellationError when cancelled."""
        cancel_path = tmp_path / ".cancel"
        cancel_path.touch()
        token = CancellationToken(cancel_path)

        with pytest.raises(CancellationError):
            check_cancellation(token)

    def test_no_raise_when_not_cancelled(self, tmp_path: Path) -> None:
        """Should not raise when not cancelled."""
        cancel_path = tmp_path / ".cancel"
        token = CancellationToken(cancel_path)

        # Should not raise
        check_cancellation(token)
