"""Fitness function: Docker Compose file consistency.

Validates:
1. All docker-compose*.yaml files are valid YAML (parse without error).
2. Build args declared in compose files are a subset of ARGs in the corresponding
   Dockerfile -- build-args that don't exist in the Dockerfile are silently ignored
   by Docker, masking configuration drift.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


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
