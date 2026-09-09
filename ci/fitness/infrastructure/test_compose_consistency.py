"""Fitness function: Docker Compose file consistency.

Validates:
1. All docker-compose*.yaml files are valid YAML (parse without error).
2. Build args declared in compose files are a subset of ARGs in the corresponding
   Dockerfile -- build-args that don't exist in the Dockerfile are silently ignored
   by Docker, masking configuration drift.
3. Every `${X_MEMORY_LIMIT:-default}` / `${X_CPU_LIMIT:-default}` fallback in a
   compose file equals `InfraSettings.x_memory_limit` / `.x_cpu_limit` -- the
   fallback is what an operator who never wrote infra/.env actually runs with,
   so a fallback that disagrees with the declared default is a limit the project
   documents nowhere (#1093).

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from syn_shared.settings.infra import InfraSettings


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _docker_dir() -> Path:
    return _repo_root() / "docker"


def _compose_files() -> list[Path]:
    return sorted(_docker_dir().glob("docker-compose*.yaml"))


def _dockerfile_args(dockerfile: Path) -> set[str]:
    """Extract all ARG names declared in a Dockerfile."""
    args: set[str] = set()
    for line in dockerfile.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("ARG "):
            # ARG FOO or ARG FOO=default
            name = stripped[4:].split("=")[0].strip()
            if name:
                args.add(name)
    return args


@pytest.mark.architecture
@pytest.mark.parametrize("compose_file", _compose_files(), ids=[f.name for f in _compose_files()])
def test_compose_file_is_valid_yaml(compose_file: Path) -> None:
    """Each docker-compose*.yaml must parse without error."""
    content = compose_file.read_text()
    parsed = yaml.safe_load(content)
    assert parsed is not None, f"{compose_file.name} parsed as empty/null"
    assert "services" in parsed or compose_file.name.endswith("cloudflare.yaml"), (
        f"{compose_file.name} has no 'services' key"
    )


@pytest.mark.architecture
def test_compose_build_args_match_dockerfile_args() -> None:
    """Build args in compose files must be declared as ARGs in the corresponding Dockerfile.

    Docker silently ignores build-args that don't exist in the Dockerfile.
    This creates a false sense of security: a compose file might pass
    INCLUDE_DOCKER_CLI=1 but if the Dockerfile ARG is renamed, the binary
    never gets installed and no error is raised.
    """
    # Only the base compose defines builds — overlays inherit them
    base_compose = _docker_dir() / "docker-compose.yaml"
    selfhost_compose = _docker_dir() / "docker-compose.selfhost.yaml"

    violations: list[str] = []

    for compose_file in [base_compose, selfhost_compose]:
        if not compose_file.exists():
            continue
        config = yaml.safe_load(compose_file.read_text()) or {}
        services = config.get("services", {})

        for service_name, service_def in services.items():
            if not isinstance(service_def, dict):
                continue
            build = service_def.get("build", {})
            if not isinstance(build, dict):
                continue

            build_args = build.get("args", {})
            if not build_args:
                continue

            # Resolve Dockerfile path
            context = build.get("context", ".")
            dockerfile_rel = build.get("dockerfile", "Dockerfile")
            dockerfile = (_docker_dir() / context / dockerfile_rel).resolve()
            if not dockerfile.exists():
                # Try relative to repo root
                dockerfile = (_repo_root() / context / dockerfile_rel).resolve()
            if not dockerfile.exists():
                continue

            declared_args = _dockerfile_args(dockerfile)
            if not declared_args:
                continue

            # build_args can be a dict or list
            if isinstance(build_args, dict):
                passed_arg_names = set(build_args.keys())
            else:
                passed_arg_names = {a.split("=")[0] for a in build_args if isinstance(a, str)}

            # Strip env var interpolation (e.g. ${INCLUDE_OP_CLI:-0} -> INCLUDE_OP_CLI)
            cleaned: set[str] = set()
            for arg in passed_arg_names:
                match = re.match(r"\$\{?([A-Z_]+)", arg)
                if match:
                    cleaned.add(match.group(1))
                else:
                    cleaned.add(arg)
            passed_arg_names = cleaned

            unknown = passed_arg_names - declared_args
            if unknown:
                violations.append(
                    f"{compose_file.name} service '{service_name}': "
                    f"build args {sorted(unknown)} not declared as ARG in {dockerfile.relative_to(_repo_root())}"
                )

    assert not violations, (
        "Build arg mismatches found (Docker silently ignores unknown build-args):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Resource-limit fallbacks vs. declared defaults
# ---------------------------------------------------------------------------

_LIMIT_FALLBACK = re.compile(r"^\$\{([A-Z0-9_]+_(?:MEMORY|CPU)_LIMIT):-(.+)\}$")

# Limit vars carried by compose but never declared as an InfraSettings field.
# Listed so that a NEWLY added undeclared limit var fails this test rather than
# passing unmeasured -- naming the known gaps is what keeps the check from
# silently shrinking to whatever subset happens to be declared.
_UNDECLARED_LIMIT_VARS = frozenset(
    {
        "ENVOY_MEMORY_LIMIT",
        "ENVOY_CPU_LIMIT",
        "TOKEN_INJECTOR_MEMORY_LIMIT",
        "TOKEN_INJECTOR_CPU_LIMIT",
    }
)


def _limit_fallbacks(compose_file: Path) -> list[tuple[str, str, str]]:
    """Return (service, env_var, fallback) for each deploy.resources.limits entry."""
    config = yaml.safe_load(compose_file.read_text()) or {}
    found: list[tuple[str, str, str]] = []
    for service_name, service_def in (config.get("services") or {}).items():
        if not isinstance(service_def, dict):
            continue
        limits = (service_def.get("deploy") or {}).get("resources", {}).get("limits", {})
        if not isinstance(limits, dict):
            continue
        for value in limits.values():
            match = _LIMIT_FALLBACK.match(str(value).strip())
            if match:
                found.append((service_name, match.group(1), match.group(2)))
    return found


@pytest.mark.architecture
def test_compose_limit_fallbacks_match_infra_settings() -> None:
    """Compose resource-limit fallbacks must equal their InfraSettings default.

    `${COLLECTOR_MEMORY_LIMIT:-96m}` is the value an operator gets when they have
    not written infra/.env -- which is the default onboarding path. When it
    disagrees with InfraSettings, infra/.env.example and infra/README.md (which
    are generated from InfraSettings) all describe a limit the deployment is not
    running under, and nothing reconciles the two. That is how the collector came
    to ship a 96m ceiling below its own measured 132MB peak (#1093).
    """
    fields = InfraSettings.model_fields
    violations: list[str] = []

    for compose_file in _compose_files():
        for service_name, env_var, fallback in _limit_fallbacks(compose_file):
            field = fields.get(env_var.lower())
            if field is None:
                if env_var not in _UNDECLARED_LIMIT_VARS:
                    violations.append(
                        f"{compose_file.name} service '{service_name}': {env_var} has no "
                        f"InfraSettings field, so its fallback {fallback!r} is declared nowhere"
                    )
                continue
            if fallback != field.default:
                violations.append(
                    f"{compose_file.name} service '{service_name}': "
                    f"{env_var} falls back to {fallback!r} but "
                    f"InfraSettings.{env_var.lower()} declares {field.default!r}"
                )

    assert not violations, (
        "Compose resource-limit fallbacks disagree with their declared defaults:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
