"""Artifact collection is bounded by SYN_EXECUTION_COLLECTION_MAX_MB (#1552).

Collection runs inside the API process, which hosts every in-process
execution, so one collection past its share of API memory kills every run.
The cap is a setting sized to the per-run allowance, and both read paths take
it: the provider read (Docker, E2B) is handed it as `ReadLimits`, and the
bind-mount walk refuses a file over it before reading a byte of it.

Each test sets the cap to 1MiB, a value no default produces, and uses files
that the old 200MiB / 50MiB caps would have read whole.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic import adapter_copy
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_shared.settings.execution import (
    API_BASELINE_MEMORY_MIB,
    COLLECTION_MEMORY_MIB,
    EXECUTION_API_MEMORY_MIB,
    ExecutionSettings,
)
from syn_shared.settings.infra import InfraSettings

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_MIB = 1024 * 1024
_OUTPUT = "artifacts/output"


@pytest.fixture
def one_mib_cap(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setenv("SYN_EXECUTION_COLLECTION_MAX_MB", "1")
    return _MIB


def _write(root: Path, name: str, size: int) -> bytes:
    content = (name.encode() * (size // len(name) + 1))[:size]
    path = root / _OUTPUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _collect(root: Path) -> list[tuple[str, bytes]]:
    handle = IsolationHandle(
        isolation_id="ws-1552", isolation_type="docker", host_workspace_path=str(root)
    )
    return adapter_copy._copy_from_workspace_blocking(handle, [f"{_OUTPUT}/*"])


def _record_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The bytes each `os.read` brought into memory, so a test sees what was loaded."""
    requested: list[int] = []
    real_read = os.read

    def _read(fd: int, n: int) -> bytes:
        chunk = real_read(fd, n)
        if chunk:
            requested.append(len(chunk))
        return chunk

    monkeypatch.setattr(adapter_copy.os, "read", _read)
    return requested


def test_the_provider_read_is_handed_the_configured_cap(one_mib_cap: int) -> None:
    """The provider sizes files in the workspace and refuses past these limits."""
    limits = adapter_copy.collection_read_limits()

    assert limits.max_total_bytes == one_mib_cap
    assert limits.max_file_bytes == one_mib_cap


def test_an_oversized_file_is_never_read_into_memory(
    tmp_path: Path, one_mib_cap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "big.bin", 2 * one_mib_cap)
    requested = _record_reads(monkeypatch)

    collected = _collect(tmp_path)

    assert collected == []
    assert requested == [], "a file over the cap was read"


def test_collection_stops_before_the_sum_passes_the_cap(
    tmp_path: Path, one_mib_cap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.bin", "b.bin", "c.bin"):
        _write(tmp_path, name, 600 * 1024)
    requested = _record_reads(monkeypatch)

    collected = _collect(tmp_path)

    assert len(collected) == 1, "only one 600KiB file fits a 1MiB collection"
    assert sum(requested) <= one_mib_cap, "read past the collection cap"


def test_below_the_caps_collection_is_unchanged(tmp_path: Path, one_mib_cap: int) -> None:
    small = {
        name: _write(tmp_path, name, 1000 * (i + 1)) for i, name in enumerate(("x.md", "y.md"))
    }

    collected = _collect(tmp_path)

    assert sorted(collected) == sorted((f"{_OUTPUT}/{n}", c) for n, c in small.items())
    assert sum(len(c) for _, c in collected) < one_mib_cap


def test_the_default_cap_fits_every_run_of_the_default_api_limit() -> None:
    """The arithmetic in execution.py: ~55MiB measured per run, collected bytes held twice."""
    measured_per_run_mib = 55
    cap_mib = ExecutionSettings().collection_max_mb
    limit = InfraSettings().api_memory_limit
    limit_mib = int(limit[:-1]) * (1024 if limit.endswith("g") else 1)
    runs = (limit_mib - API_BASELINE_MEMORY_MIB) // EXECUTION_API_MEMORY_MIB

    assert cap_mib == COLLECTION_MEMORY_MIB
    assert measured_per_run_mib + 2 * cap_mib <= EXECUTION_API_MEMORY_MIB
    assert API_BASELINE_MEMORY_MIB + runs * (measured_per_run_mib + 2 * cap_mib) <= limit_mib
