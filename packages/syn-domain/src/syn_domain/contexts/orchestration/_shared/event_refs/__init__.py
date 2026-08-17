"""Value objects that orchestration domain events may carry."""

from syn_domain.contexts.orchestration._shared.event_refs.value_objects import (
    ClaudePluginRef,
    SkillRef,
)

__all__ = ["ClaudePluginRef", "SkillRef"]
