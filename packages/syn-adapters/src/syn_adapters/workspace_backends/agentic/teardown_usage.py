"""Mapping the provider's teardown report onto the domain's `WorkspaceUsage`.

The provider (agentic-workspace's `WorkspaceDockerProvider`) owns HOW usage is
measured - which cgroup files, which exec, which delete - and returns a
`TeardownReport` from `destroy()`. This module owns only the SHAPE Syntropic137
depends on, as a Protocol, so the domain never imports a harness format and a
provider that measures nothing (None, or an older one returning no report)
maps to None rather than to a usage of zeroes.

The field names match `WorkspaceUsage` one for one, on purpose. Today nothing
checks the provider against `TeardownReportLike` statically: the pinned
provider's `destroy` is annotated `-> None`, so the adapter receives the report
as `object`. Until agentic-workspace types `destroy` against this Protocol, a
provider-side rename is caught at runtime here instead: a report that is not
None but lacks a field is logged with the missing names, and the fields it
does carry are still mapped.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Protocol, runtime_checkable

from syn_domain.contexts.orchestration import WorkspaceUsage

logger = logging.getLogger(__name__)

#: The one list of field names. The Protocol below must expose exactly these;
#: a unit test pins the two together.
USAGE_FIELDS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(WorkspaceUsage))


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
    """The domain's view of a provider report, or None when there is none.

    None in is None out, silently: the provider measured nothing. Anything
    that lacks a `TeardownReportLike` field is a contract mismatch, never
    silent: it is logged with the report's type and the missing field names,
    and whatever fields it does carry are still mapped. Teardown is never
    failed by it.
    """
    if report is None:
        return None
    missing = [name for name in USAGE_FIELDS if not hasattr(report, name)]
    if missing:
        logger.warning(
            "Provider teardown report %s does not match TeardownReportLike; "
            "missing fields %s are recorded as unknown",
            type(report).__qualname__,
            missing,
        )
    if len(missing) == len(USAGE_FIELDS):
        return None
    usage = WorkspaceUsage(**{name: getattr(report, name, None) for name in USAGE_FIELDS})
    if usage.delete_failures is not None:
        usage = dataclasses.replace(usage, delete_failures=tuple(usage.delete_failures))
    return usage
