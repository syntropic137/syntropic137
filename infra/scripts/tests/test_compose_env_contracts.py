"""Every stack that runs an API must pass on the variables its features need.

A compose stack that omits a variable does not fail. Compose simply drops the
key, the feature reads an unset value, and an unset value is a legitimate
configuration meaning "this is deliberately off". A misconfigured stack is
therefore indistinguishable from an opted-out one, and nothing anywhere says so.

That has now happened twice.

**2026-08-21, session capture.** The variables were declared only in
``docker-compose.selfhost.yaml`` and the generated
``docker-compose.syntropic137.yaml``. The vault resolved both values and
``just dev`` exported them, but the dev and ondemand API services never named
them, so compose dropped them. Capture could not work on either stack.

**2026-09-09, operator attribution (#1265).** The mirror image: the Python
wiring was correct and the dev stacks worked, because they use
``env_file: ../.env``. The published and self-hosted stacks pass only
explicitly listed variables, and neither listed these - so the deployment that
actually matters would have produced commits with no trailer and no error. It
was caught in review, not by a test, because the test that existed knew about
one feature rather than about the shape of the mistake.

So this module is written per CONTRACT rather than per feature. Adding a new
group to ``_CONTRACTS`` gets it every check below. The fix in both cases is the
same: declare it once in ``docker-compose.yaml``, which every stack layers on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

_DOCKER_DIR = Path(__file__).resolve().parents[3] / "docker"
_BASE = _DOCKER_DIR / "docker-compose.yaml"


@dataclass(frozen=True)
class EnvContract:
    """A group of variables an API stack must be able to see, and why."""

    name: str
    variables: tuple[str, ...]
    #: What silently breaks when a stack does not pass them on. Quoted back in
    #: assertion messages, because the whole hazard is that nothing else says.
    consequence: str


_CONTRACTS: tuple[EnvContract, ...] = (
    EnvContract(
        name="session capture",
        variables=("SYN_SESSION_STORE_URL", "SYN_SESSION_STORE_AUTH_TOKEN"),
        consequence=(
            "session capture is off on that stack, and an empty URL reads as "
            "'capture deliberately disabled', so the misconfiguration is "
            "indistinguishable from the intended state"
        ),
    ),
    EnvContract(
        name="operator attribution",
        variables=("SYN_OPERATOR_NAME", "SYN_OPERATOR_EMAIL"),
        consequence=(
            "the workspace image's prepare-commit-msg hook exits without "
            "writing a trailer, so agent commits carry no co-author and the "
            "sponsoring human silently earns no contribution (#1265)"
        ),
    ),
)

#: Flattened for tests that do not care which contract a variable belongs to.
_ALL_VARS: tuple[tuple[EnvContract, str], ...] = tuple(
    (contract, var) for contract in _CONTRACTS for var in contract.variables
)


def _var_id(param: object) -> str:
    return param if isinstance(param, str) else ""


#: Standalone: published for consumers who do not have the base file, so it
#: must carry its own declaration rather than inherit one.
_STANDALONE = {"docker-compose.syntropic137.yaml"}


def _defines_api_service(text: str) -> bool:
    return bool(re.search(r"^\s{2}api:\s*$", text, re.M))


def _compose_files() -> list[Path]:
    return sorted(_DOCKER_DIR.glob("docker-compose*.yaml"))


@pytest.mark.unit
class TestBaseDeclaresEveryContract:
    """The base owns the declaration; everything else inherits it."""

    def test_base_file_exists(self) -> None:
        assert _BASE.is_file(), f"missing {_BASE}"

    @pytest.mark.parametrize(("contract", "var"), _ALL_VARS, ids=lambda p: _var_id(p))
    def test_base_declares(self, contract: EnvContract, var: str) -> None:
        text = _BASE.read_text()
        assert var in text, (
            f"{_BASE.name} does not pass {var} to the api service. Every stack "
            f"layers on this file, so removing it breaks {contract.name} "
            f"everywhere at once - silently, because {contract.consequence}."
        )

    @pytest.mark.parametrize(("contract", "var"), _ALL_VARS, ids=lambda p: _var_id(p))
    def test_base_passes_through_rather_than_hardcoding(
        self, contract: EnvContract, var: str
    ) -> None:
        """It must interpolate from the environment, not carry a literal."""
        text = _BASE.read_text()
        assert re.search(rf"{var}:\s*\$\{{{var}:-\}}", text), (
            f"{var} in {_BASE.name} must be `{var}: ${{{var}:-}}` so the value "
            f"comes from the resolved environment and an unset value is empty "
            f"rather than a literal string."
        )


@pytest.mark.unit
class TestStandaloneStacksCarryTheirOwn:
    """A stack shipped without the base must declare the variables itself.

    This is the check that would have caught #1265: the published compose is
    what self-hosters actually run, and it inherits nothing.
    """

    @pytest.mark.parametrize("name", sorted(_STANDALONE))
    @pytest.mark.parametrize("contract", _CONTRACTS, ids=lambda c: c.name)
    def test_standalone_declares(self, contract: EnvContract, name: str) -> None:
        path = _DOCKER_DIR / name
        if not path.is_file():
            pytest.skip(f"{name} not generated in this checkout")
        text = path.read_text()
        for var in contract.variables:
            assert var in text, (
                f"{name} is published standalone (consumers do not have "
                f"docker-compose.yaml), so it must declare {var} itself. "
                f"Without it, {contract.consequence}."
            )


@pytest.mark.unit
class TestOverlaysDoNotShadowItAway:
    """An overlay may add to the api environment; it must not blank these.

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
        for contract in _CONTRACTS:
            for var in contract.variables:
                # `VAR: ""` or `- VAR=` with nothing after it would override
                # the base with an empty value.
                blanked = re.search(rf'^\s*-?\s*{var}[:=]\s*(""|\'\')?\s*$', text, re.M)
                assert not blanked, (
                    f"{path.name} sets {var} to an empty literal, which "
                    f"overrides the base with no error: {contract.consequence}. "
                    f"Omit the key entirely to inherit from docker-compose.yaml."
                )


@pytest.mark.unit
@pytest.mark.parametrize("contract", _CONTRACTS, ids=lambda c: c.name)
def test_no_api_stack_is_silently_missing_a_contract(contract: EnvContract) -> None:
    """The whole point, stated once per contract."""
    base_text = _BASE.read_text()
    base_ok = all(v in base_text for v in contract.variables)

    uncovered: list[str] = []
    for path in _compose_files():
        text = path.read_text()
        if not _defines_api_service(text):
            continue
        declares_own = all(v in text for v in contract.variables)
        if path.name in _STANDALONE:
            if not declares_own:
                uncovered.append(f"{path.name} (standalone, declares nothing)")
        elif not (base_ok or declares_own):
            uncovered.append(path.name)

    assert not uncovered, (
        f"these stacks run an API that cannot see the {contract.name} "
        f"variables: {uncovered}. On them, {contract.consequence}."
    )
