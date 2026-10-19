"""When a ticket is resolved (ADR-076-feedback-ticketing; plan decision D7, proposed default).

Pure. The Ticket aggregate asks it after every fact that could change the answer
and emits ``TicketResolved`` in the same command when it first says yes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.feedback._shared.value_objects import ResolutionRule

if TYPE_CHECKING:
    from collections.abc import Mapping, Set

    from syn_domain.contexts.feedback._shared.value_objects import FixObservation


class ResolutionPolicy:
    """A ticket resolves when (a) a published release contains the fix, or (b) every
    SIGNED source with a report on it has observed the fix in its own deployment.

    Anonymous reports, and sources that never call in again, resolve through (a).
    (b) exists because betas create no GitHub release, so a deployment on a beta
    can still resolve the tickets it reported. A ticket with no signed reporter
    never resolves through (b): an empty set is not "everyone observed it".
    """

    @staticmethod
    def decide(
        *,
        released: bool,
        signed_reporters: Set[str],
        observations: Mapping[str, FixObservation],
    ) -> ResolutionRule | None:
        if released:
            return ResolutionRule.RELEASED
        if not signed_reporters:
            return None
        if all(
            source in observations and observations[source].contains_fix
            for source in signed_reporters
        ):
            return ResolutionRule.ALL_REPORTERS_OBSERVED
        return None
