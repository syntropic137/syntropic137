"""Mapping the provider's teardown report onto the domain's `WorkspaceUsage`.

The provider (agentic-workspace's `WorkspaceDockerProvider`) owns HOW usage is
measured - which cgroup files, which exec, which delete - and returns a
`TeardownReport` from `destroy()`. This module owns only the SHAPE Syntropic137
depends on, as a Protocol, so the domain never imports a harness format and a
provider that measures nothing (None, or an older one returning no report)
maps to None rather than to a usage of zeroes.

The field names match `WorkspaceUsage` one for one, on purpose: a rename on
either side shows up here as a pyright error, not as a field silently None.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from syn_domain.contexts.orchestration import WorkspaceUsage


@runtime_checkable
class TeardownReportLike(Protocol):
    """What a provider's teardown report must expose. Every field may be None."""

    @property
    def cpu_usage_seconds(self) -> float | None: ...
    @property
    def cpu_throttled_seconds(self) -> float | None: ...
    @property
    def nr_throttled(self) -> int | None: ...
    @property
    def memory_peak_bytes(self) -> int | None: ...
    @property
    def oom_kills(self) -> int | None: ...
    @property
    def disk_bytes_at_teardown(self) -> int | None: ...
    @property
    def delete_failures(self) -> tuple[str, ...] | None: ...
    @property
    def net_rx_bytes(self) -> int | None: ...
    @property
    def net_tx_bytes(self) -> int | None: ...


def usage_from_report(report: object) -> WorkspaceUsage | None:
    """The domain's view of a provider report, or None when there is none."""
    if not isinstance(report, TeardownReportLike):
        return None
    return WorkspaceUsage(
        cpu_usage_seconds=report.cpu_usage_seconds,
        cpu_throttled_seconds=report.cpu_throttled_seconds,
        nr_throttled=report.nr_throttled,
        memory_peak_bytes=report.memory_peak_bytes,
        oom_kills=report.oom_kills,
        disk_bytes_at_teardown=report.disk_bytes_at_teardown,
        delete_failures=(
            tuple(report.delete_failures) if report.delete_failures is not None else None
        ),
        net_rx_bytes=report.net_rx_bytes,
        net_tx_bytes=report.net_tx_bytes,
    )
