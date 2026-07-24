"""Register Skill slice (issue #772).

Heavy-lifting command slice: caller-uploaded tree -> sha -> storage upload ->
aggregate register. Used directly by ``syn skill add`` and indirectly by
skill resolution during workflow installation. Mirrors
``register_claude_plugin`` (issue #726).
"""

from __future__ import annotations

from .projection import SkillLockEntry, SkillLockProjection
from .RegisterSkillHandler import (
    RegisterSkillHandler,
    RegisterSkillResult,
)

__all__ = [
    "RegisterSkillHandler",
    "RegisterSkillResult",
    "SkillLockEntry",
    "SkillLockProjection",
]
