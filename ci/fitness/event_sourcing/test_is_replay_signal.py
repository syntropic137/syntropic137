"""Fitness: ESP HistoricalPoller propagates is_replay to subclasses.

Layer 4 of the #694 defense (ADR-060 Section 9). The is_replay signal
flows directly from poll() to process() so cold-start replay events
can be marked source_primed=False without relying on the dead-code
primed_sources state check.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import inspect

import pytest


@pytest.mark.architecture
class TestHistoricalPollerIsReplay:
    def test_process_accepts_is_replay_kwarg(self) -> None:
        from event_sourcing.core.historical_poller import HistoricalPoller

        sig = inspect.signature(HistoricalPoller.process)
        params = sig.parameters
        assert "is_replay" in params, (
            "ESP HistoricalPoller.process() must accept is_replay kwarg "
            "for cold-start replay safety (ADR-060 Section 9 Layer 4)."
        )
        assert params["is_replay"].default is False

    def test_repo_ingestion_service_uses_is_replay(self) -> None:
        from syn_domain.contexts.github.services.event_ingestion import (
            GitHubRepoIngestionService,
        )

        sig = inspect.signature(GitHubRepoIngestionService.process)
        assert "is_replay" in sig.parameters, (
            "GitHubRepoIngestionService.process() must accept is_replay kwarg "
            "to honor the ESP cold-start replay signal."
        )
