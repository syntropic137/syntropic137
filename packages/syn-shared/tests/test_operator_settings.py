"""Operator co-authorship settings.

The property under test is not "the fields parse". It is that a HALF
configuration produces NOTHING, and that a value which could inject a second
commit trailer is refused rather than quietly repaired. Both are the difference
between attribution that works and attribution that only looks configured.
"""

from __future__ import annotations

import pytest

from syn_shared.settings.git_identity import OperatorSettings

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run nothing.
pytestmark = pytest.mark.unit

NAME = "Neural Empowerment"
EMAIL = "129192050+NeuralEmpowerment@users.noreply.github.com"


@pytest.fixture(autouse=True)
def _no_ambient_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the real variables from the process environment.

    `_env_file=None` stops pydantic-settings reading a .env file. It does NOT
    stop it reading the PROCESS ENVIRONMENT, which sits above the file and below
    init kwargs in precedence. So on any machine where attribution is actually
    configured - every workspace container, and any developer who set it up -
    a test that passes only `name` still received `email` from the environment,
    and the half-configuration cases silently became full ones.

    That is a test which passes everywhere EXCEPT where the feature is switched
    on, which is the worst possible place to be wrong. Found by a real workspace
    run on 2026-09-10, not by CI, because CI has no reason to set these.
    """
    monkeypatch.delenv("SYN_OPERATOR_NAME", raising=False)
    monkeypatch.delenv("SYN_OPERATOR_EMAIL", raising=False)


def _settings(**kw: str) -> OperatorSettings:
    """Build settings without reading the developer's own .env."""
    return OperatorSettings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_both_values_produce_the_hook_contract_exactly() -> None:
    """The keys are the hook's published names, not this class's prefix.

    agentic-primitives' prepare-commit-msg reads SYN_OPERATOR_NAME and
    SYN_OPERATOR_EMAIL. Renaming either would disable attribution in silence,
    because the hook's response to an unknown variable is to exit 0.
    """
    env = _settings(name=NAME, email=EMAIL).attribution_env

    assert env == {"SYN_OPERATOR_NAME": NAME, "SYN_OPERATOR_EMAIL": EMAIL}


@pytest.mark.parametrize(
    ("kwargs", "what_is_set"),
    [
        ({"name": NAME}, "name only"),
        ({"email": EMAIL}, "email only"),
        ({}, "neither"),
    ],
)
def test_a_half_configuration_emits_nothing(kwargs: dict[str, str], what_is_set: str) -> None:
    """One of the pair is worse than none: it looks configured and does nothing.

    The hook exits at its first guard unless BOTH are present, so forwarding a
    lone variable buys no attribution while making the deployment appear set up.
    """
    assert _settings(**kwargs).attribution_env == {}, what_is_set


@pytest.mark.parametrize("field", ["name", "email"])
@pytest.mark.parametrize("break_char", ["\n", "\r"])
def test_a_line_break_is_refused_not_stripped(field: str, break_char: str) -> None:
    """A break would end the trailer and start an attacker-chosen second one.

    The hook defends itself by stripping CR/LF. That makes this defence in
    depth rather than the only guard - but a value that could only arrive by
    mistake or by attack should fail loudly here, not be silently rewritten two
    layers away in a shell script.
    """
    payload = f"evil{break_char}Co-authored-by: attacker <bad@bad.test>"

    with pytest.raises(ValueError, match="line break"):
        _settings(**{field: payload})


def test_is_configured_agrees_with_what_is_emitted() -> None:
    """The predicate and the payload must never disagree.

    A caller that logs "attribution enabled" from is_configured while
    attribution_env returns {} would report success for work not being done.
    """
    for kwargs in ({"name": NAME, "email": EMAIL}, {"name": NAME}, {"email": EMAIL}, {}):
        s = _settings(**kwargs)
        assert s.is_configured == bool(s.attribution_env)
