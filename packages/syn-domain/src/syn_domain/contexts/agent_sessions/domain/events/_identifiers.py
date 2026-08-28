"""Shared identifier type for the delegation edge events (issue #895).

WHY this exists rather than ``Field(min_length=1)`` on each field: min_length
counts characters, so a whitespace-only id passes it. A blank id is worse than
a missing one, because it satisfies every None check downstream while linking
to nothing, and the resulting orphan looks like a successful binding.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

NonBlankId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""An identifier that is present in fact, not merely non-None."""
