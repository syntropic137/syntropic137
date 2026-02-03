"""Domain layer for GitHub context.

Contains aggregates, queries, and read models.
"""

from aef_domain.contexts.github.domain.aggregate_installation.InstallationAggregate import (
    InstallationAggregate,
)

__all__ = [
    "InstallationAggregate",
]
