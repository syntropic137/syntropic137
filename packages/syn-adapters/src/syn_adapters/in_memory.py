"""Re-export of the in-memory adapter guard (ADR-060).

The guard lives in ``syn_shared.in_memory`` so that packages which cannot
depend on syn-adapters (syn-domain, syn-tokens) can use it too.
"""

from syn_shared.in_memory import InMemoryAdapter, InMemoryAdapterError, assert_test_only

__all__ = ["InMemoryAdapter", "InMemoryAdapterError", "assert_test_only"]
