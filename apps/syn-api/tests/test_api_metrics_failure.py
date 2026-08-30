"""A failed metrics query must not render as zero usage.

`_canonical_totals` caught every exception and returned empty totals, so a
Timescale outage produced HTTP 200 with 0 tokens, $0.00 and 0 sessions
alongside populated workflow and artifact counts. On a dashboard that reads
as "you did no work", which is indistinguishable from the truth and worse
than an error: the whole point of this change was that a silently-cheap
number is the dangerous kind.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _Boom(Exception):
    pass


async def test_canonical_query_failure_is_not_reported_as_zero_usage() -> None:
    from syn_api.routes import metrics

    with (
        patch.object(metrics, "get_canonical_usage_query", side_effect=_Boom("db down")),
        pytest.raises(metrics.MetricsUnavailableError),
    ):
        await metrics._canonical_totals(None)


async def test_the_error_names_the_failure_rather_than_implying_no_activity() -> None:
    from syn_api.routes import metrics

    with patch.object(metrics, "get_canonical_usage_query", side_effect=_Boom("db down")):
        try:
            await metrics._canonical_totals(None)
        except metrics.MetricsUnavailableError as exc:
            assert "unavailable" in str(exc).lower()
        else:  # pragma: no cover - the call above must raise
            pytest.fail("expected MetricsUnavailableError")
