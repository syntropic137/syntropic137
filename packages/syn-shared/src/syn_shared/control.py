"""Control-plane signal vocabulary.

WHY THIS LIVES IN syn_shared RATHER THAN syn_adapters.

``ControlSignalType`` names a domain concept: what an operator can ask a
running execution to do. Slice code has to compare against it to decide
whether to interrupt an agent, so the domain genuinely depends on the
vocabulary - but the domain must not depend on the adapter layer (VSA206,
ADR-001 hexagonal boundary).

It previously lived in ``syn_adapters.control.commands``, which forced
``CancelSignalPoller`` to reach across the boundary with a function-local
import to dodge module-level import analysis. That hid the coupling from
readers without removing it, and it was one of the violations budgeted in
issue #817.

Moving the enum here inverts the dependency: the adapter imports the
vocabulary from shared, the domain imports the same vocabulary from shared,
and neither imports the other. The enum is a pure ``StrEnum`` with no
dependencies of its own, so nothing else moves with it.

``syn_adapters.control.commands`` re-exports this name, so existing adapter
imports keep working and there remains exactly ONE definition.
"""

from __future__ import annotations

from enum import StrEnum


class ControlSignalType(StrEnum):
    """Types of control signals an operator can send to an execution."""

    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    INJECT = "inject"
