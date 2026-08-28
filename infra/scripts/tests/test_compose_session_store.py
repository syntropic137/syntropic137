"""Every stack that runs an API must be able to reach the session store.

Session capture is enabled by two variables. If a compose stack does not pass
them to its API service, capture is off on that stack and NOTHING SAYS SO: an
empty ``SYN_SESSION_STORE_URL`` means "deliberately disabled", which is a
legitimate configuration. A misconfigured stack is therefore indistinguishable
from an opted-out one.

That is not hypothetical. On 2026-08-21 the variables were declared only in
``docker-compose.selfhost.yaml`` and the generated
``docker-compose.syntropic137.yaml``. The vault resolved both values and
``just dev`` exported them into the compose environment, but the dev and
ondemand API services never named them, so compose dropped them. Capture could
not work on either stack, and no error was produced anywhere.

The fix is a single declaration in ``docker-compose.yaml``, which every stack
layers on. These tests keep it that way: they fail if the base stops declaring
the variables, or if an overlay defines an API service that shadows the base
``environment`` without carrying them forward.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_DOCKER_DIR = Path(__file__).resolve().parents[3] / "docker"
_BASE = _DOCKER_DIR / "docker-compose.yaml"

#: Both are required for capture to function. LABEL is optional at runtime but
#: is declared alongside them so the trio stays together.
_REQUIRED = ("SYN_SESSION_STORE_URL", "SYN_SESSION_STORE_AUTH_TOKEN")

#: Standalone: published for consumers who do not have the base file, so it
#: must carry its own declaration rather than inherit one.
_STANDALONE = {"docker-compose.syntropic137.yaml"}


def _defines_api_service(text: str) -> bool:
    return bool(re.search(r"^\s{2}api:\s*$", text, re.M))


def _compose_files() -> list[Path]:
    return sorted(_DOCKER_DIR.glob("docker-compose*.yaml"))


@pytest.mark.unit
class TestBaseDeclaresSessionStore:
    """The base owns the declaration; everything else inherits it."""

    def test_base_file_exists(self) -> None:
        assert _BASE.is_file(), f"missing {_BASE}"

    @pytest.mark.parametrize("var", _REQUIRED)
    def test_base_declares(self, var: str) -> None:
        text = _BASE.read_text()
        assert var in text, (
            f"{_BASE.name} does not pass {var} to the api service. Every stack "
            f"layers on this file, so removing it disables session capture "
            f"everywhere at once - silently, because an empty URL reads as "
            f"'capture deliberately off'."
        )

    @pytest.mark.parametrize("var", _REQUIRED)
    def test_base_passes_through_rather_than_hardcoding(self, var: str) -> None:
        """It must interpolate from the environment, not carry a literal."""
        text = _BASE.read_text()
        assert re.search(rf"{var}:\s*\$\{{{var}:-\}}", text), (
            f"{var} in {_BASE.name} must be `{var}: ${{{var}:-}}` so the value "
            f"comes from the resolved environment and an unset value is empty "
            f"rather than a literal string."
        )


@pytest.mark.unit
class TestStandaloneStacksCarryTheirOwn:
    """A stack shipped without the base must declare the variables itself."""

    @pytest.mark.parametrize("name", sorted(_STANDALONE))
    def test_standalone_declares(self, name: str) -> None:
        path = _DOCKER_DIR / name
        if not path.is_file():
            pytest.skip(f"{name} not generated in this checkout")
        text = path.read_text()
        for var in _REQUIRED:
            assert var in text, (
                f"{name} is published standalone (consumers do not have "
                f"docker-compose.yaml), so it must declare {var} itself."
            )


@pytest.mark.unit
class TestOverlaysDoNotShadowItAway:
    """An overlay may add to the api environment; it must not drop these.

    Compose merges ``environment`` maps rather than replacing them, so an
    overlay that simply omits these keys is fine - the base still supplies
    them. What is NOT fine is an overlay redefining them to an empty literal,
    which silently wins over the base.
    """

    @pytest.mark.parametrize("path", _compose_files(), ids=lambda p: p.name)
    def test_no_overlay_blanks_the_values(self, path: Path) -> None:
        text = path.read_text()
        if not _defines_api_service(text):
            pytest.skip(f"{path.name} defines no api service")
        for var in _REQUIRED:
            # `VAR: ""` or `- VAR=` with nothing after it would override the
            # base with an empty value and disable capture on that stack.
            blanked = re.search(rf'^\s*-?\s*{var}[:=]\s*(""|\'\')?\s*$', text, re.M)
            assert not blanked, (
                f"{path.name} sets {var} to an empty literal, which overrides "
                f"the base and disables capture on this stack with no error. "
                f"Omit the key entirely to inherit from docker-compose.yaml."
            )


@pytest.mark.unit
def test_every_api_stack_can_reach_the_store() -> None:
    """The whole point, stated once: no API stack may be silently uncapturable."""
    base_text = _BASE.read_text()
    base_ok = all(v in base_text for v in _REQUIRED)

    uncovered: list[str] = []
    for path in _compose_files():
        text = path.read_text()
        if not _defines_api_service(text):
            continue
        declares_own = all(v in text for v in _REQUIRED)
        if path.name in _STANDALONE:
            if not declares_own:
                uncovered.append(f"{path.name} (standalone, declares nothing)")
        elif not (base_ok or declares_own):
            uncovered.append(path.name)

    assert not uncovered, (
        "these stacks run an API that cannot reach the session store: "
        f"{uncovered}. Capture would be off on them, indistinguishable from "
        "being deliberately disabled."
    )
