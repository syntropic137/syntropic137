"""Fitness: GitHub adapters explicitly subclass their domain ports.

If anyone "decouples" by removing the explicit Protocol inheritance,
this fitness fails. Combined with the typing system, this makes a
domain service that depends on the port unable to silently degrade
to depending on the concrete adapter.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import pytest


@pytest.mark.architecture
class TestEventsAPIPortAdoption:
    def test_client_implements_port(self) -> None:
        from syn_adapters.github.events_api_client import GitHubEventsAPIClient
        from syn_domain.contexts.github.slices.event_pipeline.ports import (
            GitHubEventsAPIPort,
        )

        # Protocols are not @runtime_checkable; check explicit inheritance via MRO.
        mro_names = {cls.__name__ for cls in GitHubEventsAPIClient.__mro__}
        assert GitHubEventsAPIPort.__name__ in mro_names, (
            "GitHubEventsAPIClient must explicitly inherit GitHubEventsAPIPort "
            "so the hexagonal boundary survives accidental refactors."
        )


@pytest.mark.architecture
class TestChecksAPIPortAdoption:
    def test_client_implements_port(self) -> None:
        from syn_adapters.github.checks_api_client import GitHubChecksAPIClient
        from syn_domain.contexts.github.slices.event_pipeline.ports import (
            GitHubChecksAPIPort,
        )

        mro_names = {cls.__name__ for cls in GitHubChecksAPIClient.__mro__}
        assert GitHubChecksAPIPort.__name__ in mro_names, (
            "GitHubChecksAPIClient must explicitly inherit GitHubChecksAPIPort."
        )
