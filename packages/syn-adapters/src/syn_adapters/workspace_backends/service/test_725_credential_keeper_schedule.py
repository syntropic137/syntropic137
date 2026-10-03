"""The renewal schedule, on a clock that does not wait forty minutes (#725).

What is asserted is the sequence of sleeps the keeper asked for and the
renewals it made between them, because that sequence IS the schedule: first
renewal at T+40, every 40 after a success, every 3 after a failure, a lapse
reported when the token dies unrenewed, and nothing after the phase ends.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from syn_adapters.workspace_backends.service.credential_keeper import (
    FIRST_RENEWAL,
    RENEWAL_INTERVAL,
    RETRY_INTERVAL,
    CredentialLapse,
    keep_credential_fresh,
)

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
_MIN = timedelta(minutes=1)


class _Clock:
    """Every sleep advances ``now`` by exactly what was asked, instantly.

    After ``stop_after`` sleeps the next one parks forever, which is where the
    test observes the schedule and ends the block.
    """

    def __init__(self, *, stop_after: int) -> None:
        self.at = _T0
        self.slept: list[timedelta] = []
        self.parked = asyncio.Event()
        self._stop_after = stop_after

    def now(self) -> datetime:
        return self.at

    async def sleep(self, delay: timedelta) -> None:
        if len(self.slept) == self._stop_after:
            self.parked.set()
            await asyncio.Future()
        self.slept.append(delay)
        self.at += delay


class _Workspace:
    """Renews according to a script of outcomes; its token lives an hour from each success."""

    workspace_id = "ws-keeper"

    def __init__(self, clock: _Clock, outcomes: list[bool], *, expires_at: datetime | None) -> None:
        self._clock = clock
        self._outcomes = outcomes
        self.credential_expires_at = expires_at
        self.renewed_at: list[datetime] = []
        self.attempted_at: list[datetime] = []

    async def renew_git_credential(self) -> object:
        self.attempted_at.append(self._clock.at)
        succeeded = self._outcomes.pop(0) if self._outcomes else False
        if not succeeded:
            raise RuntimeError("GitHub said no")
        self.renewed_at.append(self._clock.at)
        self.credential_expires_at = self._clock.at + timedelta(hours=1)
        return ()


async def _run(clock: _Clock, workspace: _Workspace) -> list[CredentialLapse]:
    lapses: list[CredentialLapse] = []

    async def on_lapse(lapse: CredentialLapse) -> None:
        lapses.append(lapse)

    async with keep_credential_fresh(
        workspace, on_lapse=on_lapse, now=clock.now, sleep=clock.sleep
    ):
        await asyncio.wait_for(clock.parked.wait(), timeout=10)
    return lapses


class TestTheSchedule:
    async def test_first_renewal_at_forty_minutes_then_every_forty(self) -> None:
        clock = _Clock(stop_after=3)
        workspace = _Workspace(clock, [True, True, True, True], expires_at=_T0 + timedelta(hours=1))

        lapses = await _run(clock, workspace)

        assert clock.slept == [FIRST_RENEWAL, RENEWAL_INTERVAL, RENEWAL_INTERVAL]
        assert workspace.renewed_at == [_T0 + 40 * _MIN, _T0 + 80 * _MIN, _T0 + 120 * _MIN]
        assert lapses == []

    async def test_a_failed_renewal_is_retried_every_three_minutes(self) -> None:
        clock = _Clock(stop_after=4)
        workspace = _Workspace(
            clock, [False, False, True, True], expires_at=_T0 + timedelta(hours=1)
        )

        lapses = await _run(clock, workspace)

        assert clock.slept == [FIRST_RENEWAL, RETRY_INTERVAL, RETRY_INTERVAL, RENEWAL_INTERVAL]
        assert workspace.attempted_at == [
            _T0 + 40 * _MIN,
            _T0 + 43 * _MIN,
            _T0 + 46 * _MIN,
            _T0 + 86 * _MIN,
        ]
        assert lapses == []

    async def test_nothing_is_renewed_once_the_phase_has_ended(self) -> None:
        clock = _Clock(stop_after=0)
        workspace = _Workspace(clock, [True], expires_at=_T0 + timedelta(hours=1))

        await _run(clock, workspace)
        for _ in range(5):
            await asyncio.sleep(0)

        assert workspace.attempted_at == []


class TestALapseIsNeverSilent:
    async def test_expiry_without_a_renewal_is_reported_once_at_expiry(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        expires = _T0 + timedelta(hours=1)
        # 40 min, six retries to 58, then a sleep to 60, then back to the cadence.
        clock = _Clock(stop_after=9)
        workspace = _Workspace(clock, [], expires_at=expires)

        lapses = await _run(clock, workspace)

        assert lapses == [
            CredentialLapse(expired_at=expires, attempts=7, last_error="GitHub said no")
        ]
        assert clock.slept == [FIRST_RENEWAL, *[RETRY_INTERVAL] * 6, 2 * _MIN, RENEWAL_INTERVAL]
        assert "EXPIRED" in caplog.text

    async def test_a_reporter_that_fails_does_not_stop_the_schedule(self) -> None:
        clock = _Clock(stop_after=10)
        workspace = _Workspace(clock, [False] * 7 + [True], expires_at=_T0 + timedelta(hours=1))

        async def broken(_lapse: CredentialLapse) -> None:
            raise RuntimeError("the collector is down")

        async with keep_credential_fresh(
            workspace, on_lapse=broken, now=clock.now, sleep=clock.sleep
        ):
            await asyncio.wait_for(clock.parked.wait(), timeout=10)

        assert workspace.renewed_at == [_T0 + 100 * _MIN], (
            "after the lapse the schedule goes on, and a later renewal rescues the phase"
        )
