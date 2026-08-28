"""The platform session id a delegated harness session imports as (#895).

Idempotency rests entirely on this. The import processor runs more than once -
it retries under a bound, and it re-runs after a crash - so "have I already
imported this delegate?" must be answerable without asking anything. Deriving
the id makes the answer structural: a second import addresses the SAME
aggregate as the first, so it cannot create a second session carrying the same
tokens.

The alternative, minting a uuid4 and recording the mapping, needs that mapping
written in the same transaction as the session or the crash window reopens.
Deriving the id removes the mapping and the window together.

The derivation is uuid5, which is a pure function of a namespace and a name: no
clock, no randomness, no counter, and identical across processes and restarts.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

#: Namespace for platform session ids derived from harness session ids.
#:
#: Fixed forever. Changing it would re-derive every delegate to a NEW platform
#: session, and since the old ones already carry token_usage rows, the same
#: tokens would then exist under two sessions - the double count this design
#: exists to prevent, arriving by a migration instead of a bug.
_DELEGATE_NAMESPACE: UUID = uuid5(NAMESPACE_URL, "https://syntropic137.dev/delegate-session")


def platform_session_id_for(harness_session_id: str) -> str:
    """The platform session id that this harness session imports as.

    Args:
        harness_session_id: The id the HARNESS chose, as the session store
            records it. A different namespace from platform ids, which is why
            this derives rather than reuses: two harnesses could mint the same
            id, and a harness id masquerading as a platform-issued one would
            be worse than a collision.

    Raises:
        ValueError: If the harness id is blank. Every blank string would derive
            the same id, so two unrelated delegates would import into one
            session and their tokens would merge.
    """
    if not harness_session_id.strip():
        msg = "harness session id must not be blank"
        raise ValueError(msg)

    return str(uuid5(_DELEGATE_NAMESPACE, harness_session_id))
