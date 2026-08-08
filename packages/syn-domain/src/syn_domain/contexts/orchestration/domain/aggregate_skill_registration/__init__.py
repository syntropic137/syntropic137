"""SkillRegistration aggregate (issue #772).

One stream per (source_url, version, skill_name). Stream id is sha256-derived
so concurrent registers of the same skill reference collide via
ExpectedVersion.NoStream.
"""

from __future__ import annotations

from syn_domain.contexts.orchestration.domain.aggregate_skill_registration.SkillRegistrationAggregate import (
    SkillRegistrationAggregate,
    compute_skill_stream_id,
)

__all__ = [
    "SkillRegistrationAggregate",
    "compute_skill_stream_id",
]
