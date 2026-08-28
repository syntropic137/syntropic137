"""Value objects an orchestration domain EVENT may reference.

Events must be pure data. VSA028 enforces that by rejecting imports from general
`_shared` modules, which may carry parsing, validation, or service logic -
anything an event replay should not depend on. The rule recognises a
`.value_objects`-shaped path as the declared exception.

``ClaudePluginRef`` and ``SkillRef`` are genuine value objects (frozen models
describing a reference), so events may legitimately carry them. This module is
the seam that says so in a way the validator can see, without duplicating the
definitions into the event layer or moving them away from the code that parses
them.

Add re-exports here only for types that are truly inert data. If something with
behaviour ever needs to reach an event, the event is wrong, not this file.

Note this is deliberately NOT named ``value_objects.py``: that name is already
taken in this package by the cost value objects (``CostAmount``, ``TokenCount``,
``ModelPricing``).
"""

from __future__ import annotations

from syn_domain.contexts.orchestration._shared.claude_plugin_ref import ClaudePluginRef
from syn_domain.contexts.orchestration._shared.skill_ref import SkillManifest, SkillRef

__all__ = [
    "ClaudePluginRef",
    "SkillManifest",
    "SkillRef",
]
