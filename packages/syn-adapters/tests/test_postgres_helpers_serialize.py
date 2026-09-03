"""serialize() must strip NUL bytes: Postgres jsonb cannot store a NUL character.

Regression for the artifact_summaries crash observed live 2026-07-25 — a codex
artifact whose content contained a NUL byte raised
asyncpg.exceptions.UntranslatableCharacterError and wedged the projection.
serialize() is the single boundary every projection's data crosses on the way to
a `$1::jsonb` write, so the guard lives there and protects all projections.
"""

import json

import pytest

from syn_adapters.projection_stores.postgres_helpers import serialize

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


NUL = chr(0)  # the actual NUL character jsonb rejects
ESCAPED_NUL = chr(92) + "u0000"  # 6 literal chars: backslash u 0 0 0 0


def test_serialize_strips_nul_byte_in_string_value() -> None:
    out = serialize({"content": "hello" + NUL + "world"})
    assert ESCAPED_NUL not in out
    assert json.loads(out)["content"] == "helloworld"


def test_serialize_strips_nul_in_nested_and_list() -> None:
    out = serialize({"a": {"b": "x" + NUL + "y"}, "c": ["p" + NUL + "q", "r"]})
    assert ESCAPED_NUL not in out
    parsed = json.loads(out)
    assert parsed["a"]["b"] == "xy"
    assert parsed["c"] == ["pq", "r"]


def test_serialize_preserves_literal_backslash_u_sequence() -> None:
    # A genuine string containing the 6 chars "backslash u 0000" (no real NUL)
    # must survive round-trip, proving we strip real NUL bytes, not the text.
    original = "a" + ESCAPED_NUL + "b"
    out = serialize({"text": original})
    assert json.loads(out)["text"] == original
