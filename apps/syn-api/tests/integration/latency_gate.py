"""How the dashboard latency gates measure p95: rounds, interleaved, median.

One round of 20 timed requests makes "p95" the 19th of 20: effectively the
second-worst single request. On a shared CI runner one GC pause or noisy
neighbour moved /metrics from about 95ms to 110ms against a 100ms budget
(main 7507a6fb4, eaac1e808, ca5404096), with the code unchanged.

So each endpoint is timed in ROUNDS rounds of RUNS_PER_ROUND requests, the
endpoints taking turns request by request so a stall lands on all of them
rather than on whichever one happened to be running. Each round gives a p95,
and the gate reads the MEDIAN of the round p95s: one bad round cannot fail
it, two can. The budgets are unchanged. The regression the gates exist for, a
whole-history read, is five or more times a budget in every round.
"""

from __future__ import annotations

import math
import statistics
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

ROUNDS = 3
RUNS_PER_ROUND = 20
WARMUP = 2


class GatedEndpoint(Protocol):
    """What the gate needs from an endpoint description."""

    @property
    def name(self) -> str: ...
    @property
    def path(self) -> str: ...
    @property
    def params(self) -> Mapping[str, str]: ...
    @property
    def budget_ms(self) -> float: ...


#: Issues one request and raises if it did not succeed.
Request = Callable[[str, Mapping[str, str]], Awaitable[None]]


@dataclass(frozen=True)
class Measured:
    """One endpoint's p95 in each round, and the median the gate reads."""

    round_p95s: tuple[float, ...]

    @property
    def p95(self) -> float:
        return statistics.median(self.round_p95s)


def p95_of(samples: Sequence[float]) -> float:
    """The nearest-rank 95th percentile of ``samples``."""
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


async def measure(
    request: Request,
    endpoints: Sequence[GatedEndpoint],
    *,
    rounds: int = ROUNDS,
    runs_per_round: int = RUNS_PER_ROUND,
    warmup: int = WARMUP,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Measured]:
    """Time every endpoint in interleaved rounds and return each one's round p95s."""
    for endpoint in endpoints:
        for _ in range(warmup):
            await request(endpoint.path, endpoint.params)
    round_p95s: dict[str, list[float]] = {e.name: [] for e in endpoints}
    for _ in range(rounds):
        samples: dict[str, list[float]] = {e.name: [] for e in endpoints}
        for _ in range(runs_per_round):
            for endpoint in endpoints:
                started = clock()
                await request(endpoint.path, endpoint.params)
                samples[endpoint.name].append((clock() - started) * 1000)
        for name, taken in samples.items():
            round_p95s[name].append(p95_of(taken))
    return {name: Measured(tuple(p95s)) for name, p95s in round_p95s.items()}


def report(title: str, endpoints: Sequence[GatedEndpoint], measured: Mapping[str, Measured]) -> str:
    """The table a CI log carries: every round's p95, the median, the budget."""
    lines = [
        f"{title} ({ROUNDS} interleaved rounds of {RUNS_PER_ROUND}, gate = median of round p95s):"
    ]
    for e in endpoints:
        rounds = " ".join(f"{p:7.1f}" for p in measured[e.name].round_p95s)
        lines.append(
            f"  {e.name:<32} rounds {rounds} ms   median {measured[e.name].p95:7.1f} ms"
            f"   budget {e.budget_ms:5.0f} ms"
        )
    return "\n".join(lines)


def over_budget(endpoints: Sequence[GatedEndpoint], measured: Mapping[str, Measured]) -> list[str]:
    """Endpoints whose median round p95 is over their budget."""
    return [e.name for e in endpoints if measured[e.name].p95 > e.budget_ms]
