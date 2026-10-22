"""The Executor's claim loop over the Run Queue (ADR-072 D3-D5, #1310 1.5).

``ExecutionHost`` is the only public piece: ``join()`` registers it into its
Executor Pool and ``leave()`` deregisters it, ``run_until_drained()`` claims, drains, renews and reconciles
until the host is told to drain, and ``drain()`` tells it. What it drives is reached through the ports in ``ports``.
"""

from syn_adapters.execution_host.host import ExecutionHost, HostTiming
from syn_adapters.execution_host.interrupter import AggregateRunInterrupter
from syn_adapters.execution_host.ports import ClaimedRunDrainer, RunReaper, RunInterrupter

__all__ = [
    "AggregateRunInterrupter",
    "ClaimedRunDrainer",
    "RunReaper",
    "ExecutionHost",
    "HostTiming",
    "RunInterrupter",
]
