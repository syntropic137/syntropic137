"""ScreeningPort: one classifier pass over Screened Text (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.feedback.domain.ScreenedText import ScreenedText
    from syn_domain.contexts.feedback.domain.ScreeningPolicy import ScreeningResult


class ScreeningPort(Protocol):
    """Classifies text. Never decides what happens to it: ``ScreeningPolicy`` does.

    A reply that cannot be parsed must come back as a quarantine verdict, not
    as ``clean`` and not as an exception the caller could swallow.
    """

    async def screen(self, text: ScreenedText) -> ScreeningResult: ...
