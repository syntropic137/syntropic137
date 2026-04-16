"""Fitness function: HistoricalPoller structural invariants.

Validates that HistoricalPoller subclasses preserve the cold-start fence
by not overriding @final methods (poll, _prime, _persist_cursor).

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
See also: ADR-060 section 6 (Cold-Start Fence / HistoricalPoller)
"""

from __future__ import annotations

import pytest
from event_sourcing.fitness import check_historical_poller_structure


@pytest.mark.architecture
class TestHistoricalPollerAdoption:
    """HistoricalPoller subclasses must not bypass the cold-start fence."""

    def test_github_repo_poller_preserves_cold_start_fence(self) -> None:
        """GitHubRepoIngestionService must pass ESP's structural fitness check.

        The cold-start fence (poll() is @final) prevents subclasses from
        bypassing timestamp filtering on fresh install. This test ensures
        the fence is structurally intact.
        """
        from syn_domain.contexts.github.services import GitHubRepoIngestionService

        violations = check_historical_poller_structure(GitHubRepoIngestionService)
        assert violations == [], (
            f"GitHubRepoIngestionService violates HistoricalPoller structure: {violations}"
        )

    def test_check_run_poller_is_not_historical(self) -> None:
        """CheckRunPoller is reactive (not historical) -- must NOT extend HistoricalPoller.

        CheckRunPoller only polls SHAs registered by incoming PR events,
        so it doesn't need cold-start protection. If someone changes it
        to extend HistoricalPoller, this test will catch it and prompt
        a review of whether that's the right pattern.
        """
        from event_sourcing.core.historical_poller import HistoricalPoller

        from syn_api.services.check_run_poller import CheckRunPoller

        assert not issubclass(CheckRunPoller, HistoricalPoller), (
            "CheckRunPoller should NOT extend HistoricalPoller -- "
            "it is reactive (polls registered SHAs), not historical"
        )
