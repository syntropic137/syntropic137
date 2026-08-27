"""The port syn137 depends on for harness-native delegate identity (#895).

The double here uses a DELIBERATELY SYNTHETIC line format. It is not codex's
schema and not Claude's, because encoding a real CLI's format in a domain test
would make these tests stale when that CLI changes, which is the coupling the
port exists to prevent. What is asserted is the CONTRACT: what a conforming
adapter must return, and for which inputs.

The corresponding correctness test, that each REAL adapter returns the right id
from recorded CLI output containing malformed lines and misleading id-shaped
fields, belongs in agentic-primitives, because it changes with CLI formats.
"""

from __future__ import annotations

import json

import pytest

from syn_domain.contexts.agent_sessions.ports.DelegateIdentityPort import (
    DelegateIdentityPort,
)

_IDENTITY_KIND = "identity-announcement"
_OTHER_KIND = "some-other-event"
_NATIVE_ID = "native-session-id-0001"


class _ConformingAdapter:
    """A minimal adapter that honours the whole contract.

    Its format is invented for this test. Any real harness shape is one of
    agentic-primitives' concerns.
    """

    def native_session_id_from_stream(self, line: str) -> str | None:
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # The contract says never raise: a delegate's stream is not
            # guaranteed well-formed, and a line that will not parse was
            # never going to announce identity.
            return None
        if not isinstance(payload, dict) or payload.get("kind") != _IDENTITY_KIND:
            return None
        native_id = payload.get("id")
        return native_id if isinstance(native_id, str) and native_id else None


def _line(**fields: object) -> str:
    return json.dumps(fields)


@pytest.mark.unit
def test_returns_the_id_from_an_identity_line() -> None:
    adapter: DelegateIdentityPort = _ConformingAdapter()

    result = adapter.native_session_id_from_stream(_line(kind=_IDENTITY_KIND, id=_NATIVE_ID))

    assert result == _NATIVE_ID


@pytest.mark.unit
def test_only_an_identity_line_is_trusted() -> None:
    """A non-identity line yields nothing EVEN WHEN it carries an id-shaped
    field. agentic-primitives found that reading an id off any line let an
    unrelated session's id through (#792), binding a child to the wrong parent
    while looking like it worked.
    """
    adapter: DelegateIdentityPort = _ConformingAdapter()

    result = adapter.native_session_id_from_stream(
        _line(kind=_OTHER_KIND, id="a-different-session")
    )

    assert result is None


@pytest.mark.unit
def test_an_empty_id_is_not_an_id() -> None:
    """It would bind the child to nothing while reporting success."""
    adapter: DelegateIdentityPort = _ConformingAdapter()

    assert adapter.native_session_id_from_stream(_line(kind=_IDENTITY_KIND, id="")) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "line",
    ["not json at all", "", "{unclosed", '"a bare string"', "[1, 2, 3]", "null"],
    ids=["garbage", "empty", "truncated", "bare-string", "array", "null"],
)
def test_a_malformed_line_yields_none_rather_than_raising(line: str) -> None:
    """The contract forbids raising, and a double that raises would be STRICTER
    than the contract: it would pass an implementation that violates the
    contract in the other direction, which is the failure mode a test double is
    most likely to hide.
    """
    adapter: DelegateIdentityPort = _ConformingAdapter()

    assert adapter.native_session_id_from_stream(line) is None


@pytest.mark.unit
def test_runtime_check_catches_a_missing_method() -> None:
    """The ONLY thing runtime_checkable buys: wiring fails at startup rather
    than at delegation time, when a child is already running.
    """

    class _MissingTheMethod:
        pass

    assert isinstance(_ConformingAdapter(), DelegateIdentityPort)
    assert not isinstance(_MissingTheMethod(), DelegateIdentityPort)


@pytest.mark.unit
def test_the_runtime_check_does_not_prove_a_usable_adapter() -> None:
    """Documents the limit rather than implying a guarantee.

    isinstance on a Protocol checks the NAME only, so this passes for an
    attribute that is not even callable. Anything relying on that check for
    more than a missing-method guard is relying on something that is not there.
    """

    class _NotCallable:
        native_session_id_from_stream = 42

    assert isinstance(_NotCallable(), DelegateIdentityPort)
