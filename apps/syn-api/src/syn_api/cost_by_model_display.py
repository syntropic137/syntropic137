"""Per-model cost text for the model breakdown card, built once on the server (#897).

The dashboard's ``ModelBreakdown`` card summed each phase's ``cost_by_model``
in the browser, reconciled the sum against the scope's total to find what was
"not yet attributed", and formatted every row itself. This module is that
arithmetic, moved behind the API so every client reads the same figures:

- ``sum_cost_by_model`` is ``aggregateCostByModel`` in
  ``apps/syn-dashboard-ui/src/pages/ExecutionDetail/ExecutionDetail.tsx``;
- ``cost_by_model_display`` is the reconciliation in
  ``apps/syn-dashboard-ui/src/components/ModelBreakdown.tsx``, rendered with
  ``format_cost``.

Both work in exact decimal, as the TypeScript does: amounts are read the way
``parseExactUsd`` (``utils/exactUsd.ts``) reads them, to 18 decimal places,
because float sums of exactly-attributed totals are what printed a phantom
"not yet attributed" row (#1048).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import TYPE_CHECKING

from syn_shared.display.formatters import format_cost

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syn_api.model_identity import CostModelKey

_ATTO_USD = Decimal("1E-18")
"""The resolution amounts are held at: ``parseExactUsd``'s 18 decimal places."""

_PRECISION = 60
"""Significant digits for the arithmetic: 18 places after the point leaves 42
before it, far past any cost, so no sum here is rounded by the context."""

_DECIMAL = re.compile(r"^([+-])?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$", re.ASCII)
"""``DECIMAL_RE`` from ``exactUsd.ts``. ``Decimal()`` alone is wider: it takes
``NaN``, ``Infinity``, ``1_000`` and non-ASCII digits, all of which the
TypeScript refuses."""

COST_DISPLAY_RESOLUTION = Decimal("0.0000005")
"""The smallest remainder that gets a "not yet attributed" figure.

``COST_DISPLAY_RESOLUTION`` from ``exactUsd.ts``: half a micro-dollar. Below it
the card shows no row, and a server that printed ``"<$0.01"`` there would
contradict it. A remainder that small is rounding between two sums of the same
money, not unattributed spend (#1048)."""


def _exact_usd(value: Decimal | str) -> Decimal | None:
    """``value`` to 18 decimal places, half away from zero; ``None`` if it is not a finite decimal."""
    text = value if isinstance(value, str) else format(value, "f")
    match = _DECIMAL.match(text.strip())
    if match is None or (not match.group(2) and not match.group(3)):
        return None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        try:
            return Decimal(match.group(0)).quantize(_ATTO_USD, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None


def _exact_usd_text(value: Decimal) -> str:
    """``exactUsdToString``: plain decimal, no trailing zeros, ``"0"`` for zero."""
    if value == 0:
        return "0"
    return format(value, "f").rstrip("0").rstrip(".")


def sum_cost_by_model(maps: Iterable[Mapping[CostModelKey, str]]) -> dict[CostModelKey, str]:
    """Per-model costs summed across ``maps``, exactly, as decimal strings.

    The rule is ``aggregateCostByModel``'s, so the server and the card agree on
    every input: a value that is not a finite decimal is skipped, never read as
    zero; zero and negative values are kept and summed; a model appears once,
    in the order it was first seen.

    This is the per-model split of the phases that have one, NOT the scope's
    cost. A running phase's map is empty, so mid-run the sum accounts for less
    than the total, and ``cost_by_model_display`` reports the difference.
    """
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        totals: dict[CostModelKey, Decimal] = {}
        for costs in maps:
            for model, text in costs.items():
                cost = _exact_usd(text)
                if cost is None:
                    continue
                totals[model] = totals.get(model, Decimal(0)) + cost
    return {model: _exact_usd_text(total) for model, total in totals.items()}


@dataclass(frozen=True)
class CostByModelDisplay:
    """The text a model breakdown card shows beside its bars."""

    cost_by_model_display: dict[CostModelKey, str]
    """``format_cost`` of each value, priced spend only, keyed as the map it was
    built from; a value that is not a finite decimal gets no entry. The card
    draws a row only for a positive cost."""
    unattributed_cost_display: str | None
    """What the total holds that no model accounts for, or ``None`` when that
    is nothing the card would show. See ``cost_by_model_display``."""


def cost_by_model_display(
    cost_by_model: Mapping[CostModelKey, Decimal] | Mapping[CostModelKey, str],
    total_cost_usd: Decimal,
) -> CostByModelDisplay:
    """Render a scope's per-model split, and what its total holds beyond it.

    The "not yet attributed" rule is ``ModelBreakdown``'s, in exact decimal:

    - ``attributed`` is the sum of the POSITIVE per-model costs (the card's
      rows; an unparseable, zero or negative value draws none);
    - ``basis`` is ``max(total_cost_usd, attributed)``, so a total below what
      the rows account for never produces a negative remainder;
    - the remainder is ``basis - attributed``, rendered with ``format_cost``
      when it is at least ``COST_DISPLAY_RESOLUTION``, else ``None``.

    So a positive difference is a string, zero or negative is ``None``, and so
    is a positive difference under half a micro-dollar, which the card hides.
    """
    exact = {model: _exact_usd(cost) for model, cost in cost_by_model.items()}
    displays = {model: format_cost(cost) for model, cost in exact.items() if cost is not None}
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        attributed = sum((c for c in exact.values() if c is not None and c > 0), Decimal(0))
        total = _exact_usd(total_cost_usd)
        basis = total if total is not None and total > attributed else attributed
        remainder = basis - attributed
    return CostByModelDisplay(
        cost_by_model_display=displays,
        unattributed_cost_display=(
            format_cost(remainder) if remainder >= COST_DISPLAY_RESOLUTION else None
        ),
    )
