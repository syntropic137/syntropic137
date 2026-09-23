"""The object key and the index row must be derived from the same characters.

THE BUG THIS PINS. A conversation was uploaded to MinIO under a key built from
the RAW session id, while the Postgres index row naming it was built from the
SANITISED one. Nothing failed. The object landed under a name the index could
never point at, and the read reported that no conversation had ever been
recorded - the original crash turned into silent data loss, which is worse.

WHY THESE TESTS EXIST SEPARATELY FROM THE HOSTILE-INPUT SUITE. That suite
passes with the canonicalisation removed: mutating
`conversation_object_key` to interpolate the raw id leaves all of it green,
because nothing in it derives a key. A fix nothing can fail is a fix nobody
can trust, so the invariant gets its own tests, and they are written to die
under exactly that mutation.

`unit` marker per the repository convention: CI runs `pytest -m unit`, and an
unmarked module collects zero while the gate reports success.
"""

from __future__ import annotations

import pytest

from syn_adapters.conversations.object_key import conversation_object_key
from syn_adapters.postgres_text import pg_safe

pytestmark = pytest.mark.unit

#: A session id carrying the byte that started all of this.
_NUL_ID = "sess-\x00-9471"

#: Postgres refuses more than NUL in a text value; a lone surrogate is the
#: other one this codebase already sanitises.
_SURROGATE_ID = "sess-\ud800-9471"


@pytest.mark.parametrize("raw", [_NUL_ID, _SURROGATE_ID])
def test_a_writer_holding_the_raw_id_derives_the_same_key_as_one_holding_the_stored_id(
    raw: str,
) -> None:
    """The desync, stated as an equality.

    The uploader had the raw id and the index had the stored id. If those two
    produce different keys, the object is unreachable. This is the assertion
    that fails when the canonicalisation is removed.
    """
    from_raw = conversation_object_key(raw)
    from_stored = conversation_object_key(pg_safe(raw))

    assert from_raw == from_stored, (
        "a writer holding the raw id and one holding the stored id derived "
        "different object keys; the object would be filed under a name the "
        "index cannot point at, and the read would report no conversation"
    )


@pytest.mark.parametrize("raw", [_NUL_ID, _SURROGATE_ID])
def test_the_key_never_carries_a_character_the_index_cannot_store(raw: str) -> None:
    """A key holding a byte the index cannot hold is a key that cannot be looked up."""
    key = conversation_object_key(raw)

    assert "\x00" not in key
    assert key == pg_safe(key), (
        "the key contains a character that would be altered on its way into "
        "Postgres, so the stored key and the real key would differ"
    )


def test_canonicalising_twice_changes_nothing() -> None:
    """Idempotence is what lets a caller pass either form without knowing which.

    Without it, every caller would have to know whether the id it holds has
    already been through `pg_safe` - and the bug this file exists for was
    exactly a caller that did not know.
    """
    once = conversation_object_key(_NUL_ID)
    twice = conversation_object_key(pg_safe(pg_safe(_NUL_ID)))

    assert once == twice


def test_an_ordinary_id_is_untouched() -> None:
    """Canonicalisation must not rewrite ids that were already fine.

    Otherwise this fix would orphan every conversation written before it.
    """
    ordinary = "0001ee70-aa9c-45f4-b89e-c636be5be6f3"

    assert conversation_object_key(ordinary) == (f"sessions/{ordinary}/conversation.jsonl")
