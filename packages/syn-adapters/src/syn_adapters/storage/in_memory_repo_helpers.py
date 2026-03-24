"""In-memory repository helpers — complex repositories extracted from in_memory_repositories.py.

WARNING: These repositories are for unit/integration tests only.

InMemoryWorkflowRepository has been moved to in_memory_workflow_repo.py.
This module re-exports it for backward compatibility.
"""

from __future__ import annotations

from syn_adapters.storage.in_memory_workflow_repo import InMemoryWorkflowRepository

__all__ = ["InMemoryWorkflowRepository"]
