"""The startup reap must name the signal that killed its docker client (#1295).

Same defect, same class of process as the one #1295 was filed about: the exit
code this reports belongs to the orchestrator's OWN ``docker`` subprocess, not
to anything inside a workspace container. So when that client is killed by a
signal the reap reports ``exited -11``, and the operator reading
``CleanupResult.failures`` - the string that says containers may still be
running - has to decode it unaided.

Asserts the reason string the caller actually stores, not the formatter.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.services.reconciliation import _docker_rm

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


async def _reap_reason(rm_returncode: int | None) -> str | None:
    """Run the reap with a ``docker rm -f`` that exits ``rm_returncode``."""
    ps_proc = MagicMock()
    ps_proc.communicate = AsyncMock(return_value=(b"c0ffee\n", b""))

    rm_proc = MagicMock()
    rm_proc.wait = AsyncMock(return_value=rm_returncode)
    rm_proc.returncode = rm_returncode

    with (
        patch(
            "syn_api.services.reconciliation.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[ps_proc, rm_proc]),
        ),
        patch(
            "syn_api.services.reconciliation._docker_stop_bounded",
            new=AsyncMock(),
        ),
    ):
        return await _docker_rm("label=syn", "workspace")


async def test_a_segfaulted_docker_client_is_named_in_the_reap_failure() -> None:
    reason = await _reap_reason(-11)

    assert reason is not None
    assert "exited -11 (SIGSEGV: Segmentation fault)" in reason


async def test_an_unreaped_docker_client_is_not_named_a_signal() -> None:
    """``returncode`` is ``None`` until the process is reaped - not signal 0."""
    reason = await _reap_reason(None)

    assert reason is not None
    assert "SIG" not in reason
    assert "no exit status" in reason


async def test_an_ordinary_nonzero_reap_still_reads_as_a_plain_number() -> None:
    reason = await _reap_reason(1)

    assert reason is not None
    assert "exited 1" in reason
    assert "SIG" not in reason
