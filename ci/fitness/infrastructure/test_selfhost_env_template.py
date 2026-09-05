"""The released operator template must document what the published stack reads.

``docker/selfhost.env.example`` is the file an operator actually gets: the
release workflow uploads it as a release asset and syncs it to the npx setup
package as ``templates/selfhost.env.example``. ``infra/.env.example`` is a
different file for a different audience -- the repo's own dev workflow -- and
``syn_shared.doctor`` documents it as INERT with respect to the settings path
the published stack uses.

Nothing kept the two in step, and it cost a release: ``SYN_GATEWAY_BIND`` was
added to ``InfraSettings``, wired into the published compose file, and
documented in ``infra/.env.example`` -- so it worked, and an operator following
the shipped template had no way to discover it existed. Hand-editing the
generated compose file was the only route, and the next ``setup update``
silently reverted it.

The invariant is narrow on purpose: if the published stack interpolates a
setting out of the operator's ``.env``, the operator's template has to name it.
Settings the published compose never reads are deliberately NOT required here --
documenting a knob the stack ignores is its own kind of lie.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syn_shared.settings.infra import InfraSettings

pytestmark = pytest.mark.architecture

_ROOT = Path(__file__).resolve().parents[3]
_PUBLISHED_COMPOSE = _ROOT / "docker" / "docker-compose.syntropic137.yaml"
_RELEASED_TEMPLATE = _ROOT / "docker" / "selfhost.env.example"

#: Set inside the container by ``docker/selfhost-entrypoint.sh``, which reads
#: ``/run/secrets/db_password``. It is interpolated by the compose file but is
#: not an ``.env`` knob, and inviting an operator to set it there would let them
#: disagree with the secret Postgres actually initialised itself with.
_SUPPLIED_OUTSIDE_ENV = frozenset({"POSTGRES_PASSWORD"})


def _interpolated_by_published_compose() -> set[str]:
    """Variable names the published compose file expands, e.g. ``${FOO:-bar}``."""
    return set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", _PUBLISHED_COMPOSE.read_text()))


def _documented_by_released_template() -> set[str]:
    """Names the template assigns, whether live or commented out as an example."""
    return set(
        re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", _RELEASED_TEMPLATE.read_text(), re.MULTILINE)
    )


def _operator_settings() -> set[str]:
    """Settings the published stack reads from the operator's ``.env``."""
    fields = {name.upper() for name in InfraSettings.model_fields}
    return (fields & _interpolated_by_published_compose()) - _SUPPLIED_OUTSIDE_ENV


def test_every_operator_setting_the_published_stack_reads_is_in_the_template() -> None:
    """Otherwise the knob exists, works, and cannot be found."""
    missing = sorted(_operator_settings() - _documented_by_released_template())

    assert not missing, (
        f"{_RELEASED_TEMPLATE.relative_to(_ROOT)} is the file operators receive, and it "
        f"does not mention {missing}. The published compose file expands each of them "
        f"out of the operator's .env, so the setting works but is undiscoverable, and "
        f"hand-editing the generated compose file is reverted by the next update."
    )


def test_the_gate_is_reading_a_template_that_still_exists() -> None:
    """A guard on the guard.

    Both halves are derived by pattern-matching files. If either file moves or
    is renamed, every set above goes empty and the check above passes on
    nothing at all -- silently, and exactly when it matters most.
    """
    assert _RELEASED_TEMPLATE.is_file(), f"{_RELEASED_TEMPLATE} is gone; this gate is now inert"
    assert "CANONICAL SOURCE" in _RELEASED_TEMPLATE.read_text(), (
        "the template no longer declares itself the canonical released source; "
        "confirm the release workflow still ships this file before trusting this gate"
    )
    assert _operator_settings(), "no operator settings found at all -- the parsing has broken"
