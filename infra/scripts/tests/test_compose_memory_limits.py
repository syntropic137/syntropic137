"""One resource ceiling per service, stated identically everywhere it is declared.

A container gets whatever limit the path that started it resolved, and this repo
declares each default in five places: the selfhost overlay, the published
standalone compose, the ``InfraSettings`` field the env templates are generated
from, and the two env templates operators copy. Compose reads
``${COLLECTOR_MEMORY_LIMIT:-96m}``, so a value in an operator's ``infra/.env``
wins over the compose default silently - raising the compose default alone
leaves everyone who copied ``infra/.env.example`` on the old number, and nothing
anywhere reports the difference.

That is not hypothetical. On 2026-06-17 the collector's compose default was
tuned to 96m and the templates were left at 256m, so the repo shipped two
different "defaults" for the same variable for three months. Issue #1093 then
measured the collector at 90.55MiB under 8 concurrent executions - 94% of the
96m cap, on the event ingestion path, where an OOM kill surfaces as missing
telemetry rather than as a memory error.

So: every declaration of a limit must agree with every other one, and the two
services #1093 measured must sit above a floor taken from that measurement.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syn_shared.settings.infra import InfraSettings

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCKER_DIR = _REPO_ROOT / "docker"

#: Every variable naming a container resource ceiling.
_VAR = r"[A-Z0-9_]+_(?:MEMORY|CPU)_LIMIT"

#: Floors for the two services measured in #1093, with the peak that justifies
#: them. Their load scales with concurrent executions while the limit does not,
#: so the ceiling has to leave room for more concurrency than was measured.
_FLOORS = {
    "COLLECTOR_MEMORY_LIMIT": ("512m", "peaked at 90.55MiB under 8 concurrent executions"),
    "MINIO_MEMORY_LIMIT": ("1g", "peaked at 227.60MiB under 8 concurrent executions"),
}

_SIZE_UNITS = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def _to_bytes(value: str) -> int:
    """Parse a Docker size string (``512m``, ``1g``, ``1gb``) into bytes."""
    match = re.fullmatch(r"(\d+)\s*([bkmg])b?", value.strip().lower())
    assert match, f"{value!r} is not a Docker size string"
    return int(match.group(1)) * _SIZE_UNITS[match.group(2)]


def _from_compose(path: Path) -> dict[str, str]:
    """Defaults in ``${VAR:-default}`` interpolations."""
    return dict(re.findall(rf"\$\{{({_VAR}):-([^}}]+)\}}", path.read_text()))


def _from_env_template(path: Path) -> dict[str, str]:
    """Assignments in a ``.env`` template, commented-out ones included.

    A commented line is still a declared default: it is what an operator
    uncomments, and uncommenting it must not change the deployed limit.
    """
    pattern = rf"^#?\s*({_VAR})\s*=\s*['\"]?([^'\"\s#]+)"
    return dict(re.findall(pattern, path.read_text(), re.M))


def _from_markdown_table(path: Path) -> dict[str, str]:
    """Rows of the documented ``| variable | default | description |`` table."""
    pattern = rf"^\|\s*`({_VAR})`\s*\|\s*`([^`]+)`\s*\|"
    return dict(re.findall(pattern, path.read_text(), re.M))


def _from_infra_settings() -> dict[str, str]:
    """The Pydantic fields the env templates are generated from."""
    declared: dict[str, str] = {}
    for name, field in InfraSettings.model_fields.items():
        var = name.upper()
        if re.fullmatch(_VAR, var) and isinstance(field.default, str):
            declared[var] = field.default
    return declared


def _declarations() -> dict[str, dict[str, str]]:
    """Map each variable to ``{where it is declared: the default declared}``."""
    sources: dict[str, dict[str, str]] = {"InfraSettings (infra.py)": _from_infra_settings()}
    for compose in sorted(_DOCKER_DIR.glob("docker-compose*.yaml")):
        sources[f"docker/{compose.name}"] = _from_compose(compose)
    for template in (_DOCKER_DIR / "selfhost.env.example", _REPO_ROOT / "infra/.env.example"):
        sources[str(template.relative_to(_REPO_ROOT))] = _from_env_template(template)
    readme = _REPO_ROOT / "infra/README.md"
    sources[str(readme.relative_to(_REPO_ROOT))] = _from_markdown_table(readme)

    declarations: dict[str, dict[str, str]] = {}
    for where, declared in sources.items():
        for var, value in declared.items():
            declarations.setdefault(var, {})[where] = value
    return declarations


_DECLARATIONS = _declarations()
_MULTIPLY_DECLARED = sorted(var for var, found in _DECLARATIONS.items() if len(found) > 1)


@pytest.mark.unit
def test_the_limits_are_found_at_all() -> None:
    """Guard the regexes: a parser that silently matches nothing proves nothing."""
    assert set(_FLOORS) <= set(_MULTIPLY_DECLARED), (
        f"expected {sorted(_FLOORS)} to be declared in more than one place, found "
        f"{ {var: sorted(_DECLARATIONS.get(var, {})) for var in _FLOORS} }. "
        f"If a file moved or changed shape, the extractor here needs updating - "
        f"otherwise this suite passes by looking at nothing."
    )


@pytest.mark.unit
@pytest.mark.parametrize("var", _MULTIPLY_DECLARED)
def test_every_declaration_of_a_limit_agrees(var: str) -> None:
    """Two files declaring different defaults for one variable is a live bug."""
    declared = _DECLARATIONS[var]
    assert len(set(declared.values())) == 1, (
        f"{var} is declared with conflicting defaults: "
        + ", ".join(f"{where}={value}" for where, value in sorted(declared.items()))
        + ". Which one a container gets depends on whether the operator copied an "
        "env template, and nothing reports the difference."
    )


@pytest.mark.unit
@pytest.mark.parametrize("var", sorted(_FLOORS))
def test_measured_services_keep_their_headroom(var: str) -> None:
    """#1093: these two were measured near their ceilings under load."""
    floor, measurement = _FLOORS[var]
    for where, value in sorted(_DECLARATIONS[var].items()):
        assert _to_bytes(value) >= _to_bytes(floor), (
            f"{where} declares {var}={value}, below the {floor} floor. "
            f"This service {measurement} (#1093) and its load scales with "
            f"concurrency while this limit does not."
        )
