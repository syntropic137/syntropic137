"""What a phase's workspace may do against the platform API (ADR-072, #1744).

Shared because two packages speak it: a phase DECLARES it in workflow YAML
(syn-domain), and the platform token minted for that phase CARRIES it
(syn-adapters). One enum means the word a workflow author writes is the word
the enforcer checks.
"""

from __future__ import annotations

from enum import StrEnum


class PlatformScope(StrEnum):
    """The one scope a workspace's platform token carries.

    ``READ`` is every phase's default: GET/HEAD on the read-only resources.
    ``EVAL`` is READ plus exactly two writes - launching a workflow run INTO a
    named eval, and scoring a run of an eval - and only a phase that declares
    ``platform_access: eval`` is given it. ADR-072 is the authority for what
    each scope reaches; ``syn_adapters.platform_access`` is the enforcement.
    """

    READ = "read"
    EVAL = "eval"
