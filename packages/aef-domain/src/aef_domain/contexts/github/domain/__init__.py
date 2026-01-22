"""Domain layer for GitHub context.

Contains aggregates, queries, and read models.
"""

from aef_domain.contexts.github.domain.InstallationAggregate import (
    InstallationAggregate,
)

__all__ = [
    "InstallationAggregate",
]
