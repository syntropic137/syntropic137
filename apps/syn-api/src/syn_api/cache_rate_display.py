"""Server-side labels for how cache tokens are billed relative to fresh input.

The dashboard's Token Usage card hard-coded "0.1x rate" and "1.25x rate". Both
are properties of a model's price, not constants: Opus 5.5 reads cache at 0.05x
of input, and a scope that ran two models with different read rates has no
single read rate at all. The multiplier math lives in ``syn_shared.pricing``
(``cache_rate_multipliers``); this module only renders it, once, for every
route that serves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from syn_shared.pricing import cache_rate_multipliers

if TYPE_CHECKING:
    from collections.abc import Iterable

_MULTIPLIER_QUANTUM = Decimal("0.0001")
"""Precision a multiplier is shown at. Every rate in the table today is an
exact two-decimal ratio (0.05, 0.1, 1.25); this only bounds a future ratio
such as 1/3 to something a label can hold."""


@dataclass(frozen=True)
class CacheRateDisplay:
    """The two labels, each ``None`` when no single multiplier is true for the scope."""

    cache_read_rate_display: str | None
    cache_write_rate_display: str | None


def format_rate_multiplier(multiplier: Decimal) -> str:
    """``Decimal("0.05")`` -> ``"0.05x rate"``, ``Decimal("2.00")`` -> ``"2x rate"``.

    Plain positional notation always: ``Decimal.normalize()`` alone would turn
    ``10`` into ``1E+1``.
    """
    normalized = multiplier.quantize(_MULTIPLIER_QUANTUM).normalize()
    return f"{normalized:f}x rate"


def cache_rate_display(models: Iterable[str]) -> CacheRateDisplay:
    """Labels for a scope that ran ``models``.

    ``None`` for a label whenever ``cache_rate_multipliers`` has no single
    answer: no models, a model without a rate (including the
    unattributed-model bucket), a zero input rate, or models that disagree.
    """
    rates = cache_rate_multipliers(models)
    return CacheRateDisplay(
        cache_read_rate_display=(
            None if rates.cache_read is None else format_rate_multiplier(rates.cache_read)
        ),
        cache_write_rate_display=(
            None if rates.cache_write is None else format_rate_multiplier(rates.cache_write)
        ),
    )
