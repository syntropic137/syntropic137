"""``extra_environment`` cannot write the operator attribution contract.

OperatorSettings validates the pair once: both present or neither, and no line
break in either, because the value becomes a commit-message trailer. That
guarantee is only worth anything if the settings object is the ONLY way the
keys reach a container.

``build_isolation_config`` merges caller-supplied ``extra_environment`` over the
service configuration, so without a guard a caller could write either key
directly and reintroduce exactly the states validation exists to exclude - and
never construct OperatorSettings at all.

No production caller passes these today. These tests exist so that stays true
by construction rather than by nobody having done it yet.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.service.workspace_lifecycle import (
    build_isolation_config,
)
from syn_adapters.workspace_backends.service.workspace_service import (
    WorkspaceServiceConfig,
)

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run nothing.
pytestmark = pytest.mark.unit

NAME = "Neural Empowerment"
EMAIL = "129192050+NeuralEmpowerment@users.noreply.github.com"


def _build(service_env: dict[str, str], extra: dict[str, str] | None) -> dict[str, str]:
    cfg = WorkspaceServiceConfig(environment=service_env)
    return build_isolation_config(
        config=cfg,
        workspace_id="ws-1",
        execution_id="exec-1",
        workflow_id=None,
        phase_id=None,
        extra_environment=extra,
    ).environment


def test_a_caller_cannot_introduce_a_half_pair() -> None:
    """One key alone is the state OperatorSettings refuses to produce."""
    env = _build({}, {"SYN_OPERATOR_NAME": NAME})

    assert "SYN_OPERATOR_NAME" not in env


def test_a_caller_cannot_replace_the_configured_operator() -> None:
    """The trusted pair survives an attempt to overwrite it."""
    env = _build(
        {"SYN_OPERATOR_NAME": NAME, "SYN_OPERATOR_EMAIL": EMAIL},
        {"SYN_OPERATOR_NAME": "Someone Else", "SYN_OPERATOR_EMAIL": "other@example.test"},
    )

    assert env["SYN_OPERATOR_NAME"] == NAME
    assert env["SYN_OPERATOR_EMAIL"] == EMAIL


def test_a_caller_cannot_smuggle_a_line_break_past_the_validator() -> None:
    """The payload the settings validator rejects must not arrive by this door."""
    payload = "evil\nCo-authored-by: attacker <bad@bad.test>"
    env = _build(
        {"SYN_OPERATOR_NAME": NAME, "SYN_OPERATOR_EMAIL": EMAIL}, {"SYN_OPERATOR_NAME": payload}
    )

    assert "\n" not in env["SYN_OPERATOR_NAME"]
    assert env["SYN_OPERATOR_NAME"] == NAME


def test_unreserved_keys_still_pass_through() -> None:
    """The guard is a narrow list, not a general block on extra_environment."""
    env = _build({}, {"SOME_OTHER_VAR": "value"})

    assert env["SOME_OTHER_VAR"] == "value"


def test_the_trusted_pair_reaches_the_container() -> None:
    """Service-level configuration is unaffected by the guard."""
    env = _build({"SYN_OPERATOR_NAME": NAME, "SYN_OPERATOR_EMAIL": EMAIL}, None)

    assert env["SYN_OPERATOR_NAME"] == NAME
    assert env["SYN_OPERATOR_EMAIL"] == EMAIL
