"""NonceLedger: replay rejection for signed submissions (ADR-076-feedback-ticketing).

Feedback's own port, not github's ``DedupPort``: rejecting a replayed request
and deduplicating a GitHub event change for different reasons. The signature
is kept identical so ``RedisDedupAdapter`` satisfies it structurally.
"""

from __future__ import annotations

from typing import Protocol


class NonceLedger(Protocol):
    async def is_duplicate(self, dedup_key: str) -> bool:
        """True if the nonce was seen; otherwise atomically records it and returns False."""
        ...
