"""Fitness function: every path that builds syn-api ships the Docker CLI.

syn_adapters' ``image_verification`` resolves every workspace image through
``shutil.which("docker")`` and fails closed when it is absent. A syn-api image
built without the Docker CLI therefore passes /health, serves every read
endpoint, and fails EVERY workflow execution at bootstrap - so nothing short of
attempting an execution surfaces the defect (#1216).

Four things build that image: the compose stack, ``just release-local``, the
release workflow and the docker dry-run workflow. They agreed about the
``INCLUDE_DOCKER_CLI`` build arg everywhere except ``release-local``, which
passed no args at all and silently inherited a Dockerfile default of 0. This
test measures the EFFECTIVE value each build path produces - explicit arg where
one is given, Dockerfile default where none is - so a path that goes quiet
still gets counted.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

ARG = "INCLUDE_DOCKER_CLI"
SYN_API = "syn-api"
SYN_API_DOCKERFILE = "infra/docker/images/syn-api/Dockerfile"

# ``${{ matrix.image == 'syn-api' && '1' || '0' }}`` - the only GitHub
# expression any build arg in this repo uses. An unrecognised form is a hard
# failure, not a skip: a build arg this test cannot read is a build arg that
# can drift unobserved, which is the whole defect.
_MATRIX_TERNARY = re.compile(
    r"^\$\{\{\s*matrix\.image\s*==\s*'(?P<image>[\w-]+)'"
    r"\s*&&\s*'(?P<then>[^']*)'\s*\|\|\s*'(?P<otherwise>[^']*)'\s*\}\}$"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class BuildPath:
    """One place that builds an image, and what it declares for ``ARG``.

    ``declared`` is None when the path passes no build arg at all - which is
    not the same as passing 0, and is exactly the case that bit us.
    """

    source: str
    declared: str | None

    def effective(self, dockerfile_default: str) -> str:
        return self.declared if self.declared is not None else dockerfile_default


def _resolve_for_syn_api(raw: str, source: str) -> str | None:
    """Resolve a declared build-arg value as syn-api would see it."""
    value = raw.strip()
    ternary = _MATRIX_TERNARY.match(value)
    if ternary is not None:
        return ternary["then"] if ternary["image"] == SYN_API else ternary["otherwise"]
    if "${{" in value or "${" in value:
        pytest.fail(
            f"{source}: cannot resolve {ARG}={value!r}. Teach this test the new "
            f"form rather than leaving the value unmeasured."
        )
    return value


def _dockerfile_default() -> str:
    """The ARG default in the syn-api Dockerfile, which every silent path gets."""
    for line in (_repo_root() / SYN_API_DOCKERFILE).read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(f"ARG {ARG}"):
            _, _, default = stripped.partition("=")
            return default.strip()
    pytest.fail(f"{SYN_API_DOCKERFILE} declares no `ARG {ARG}`")


def _justfile_recipe_body(name: str) -> str:
    """Return the indented body of a justfile recipe, without its signature."""
    lines = (_repo_root() / "justfile").read_text().splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(rf"^{re.escape(name)}(\s|:)", line)),
        None,
    )
    assert start is not None, f"justfile has no recipe named `{name}`"
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


def _case_arms(body: str) -> dict[str, str]:
    """Map each image named by a shell `case` arm to that arm's text.

    Handles the ``a|b|c)`` form, so an arm covering five images registers all
    five rather than a made-up sixth name.
    """
    arms: dict[str, str] = {}
    for match in re.finditer(r"^\s*([\w|-]+)\)(.*?);;", body, re.DOTALL | re.MULTILINE):
        for image in match[1].split("|"):
            arms[image.strip()] = match[2]
    return arms


def _release_local_images() -> list[str]:
    match = re.search(r"for image in ([\w\s-]+); do", _justfile_recipe_body("release-local"))
    assert match is not None, "release-local no longer loops over an image list"
    return match[1].split()


def _compose_build_paths() -> list[BuildPath]:
    """Every compose file whose `api` service participates in building syn-api.

    Overlays inherit the base service's context and dockerfile, so they count
    as build paths even though only the base names the Dockerfile.
    """
    paths: list[BuildPath] = []
    for compose_file in sorted((_repo_root() / "docker").glob("docker-compose*.yaml")):
        config = yaml.safe_load(compose_file.read_text()) or {}
        service = (config.get("services") or {}).get("api")
        if not isinstance(service, dict):
            continue
        build = service.get("build")
        if not isinstance(build, dict):
            continue
        args = build.get("args") or {}
        declared = args.get(ARG) if isinstance(args, dict) else None
        paths.append(
            BuildPath(
                source=f"docker/{compose_file.name} (service api)",
                declared=None if declared is None else str(declared),
            )
        )
    return paths


def _release_local_build_path() -> BuildPath:
    arms = _case_arms(_justfile_recipe_body("release-local"))
    assert SYN_API in arms, "release-local no longer has a syn-api case arm"
    # Stop at the closing quote of `build_args="--build-arg ARG=1"`.
    match = re.search(rf"""--build-arg\s+{ARG}=([^\s"']+)""", arms[SYN_API])
    return BuildPath(
        source="justfile `release-local` (syn-api)",
        declared=None if match is None else match[1],
    )


def _workflow_build_paths() -> list[BuildPath]:
    """syn-api's build args in the two workflows that build container images.

    Read-only: this repo's App has no `workflows` permission, so these files
    are measured here rather than edited.
    """
    workflows = _repo_root() / ".github" / "workflows"
    paths: list[BuildPath] = []

    release = yaml.safe_load((workflows / "release-containers.yaml").read_text())
    for job_name, job in (release.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            args = (step.get("with") or {}).get("build-args")
            if not args:
                continue
            source = f"release-containers.yaml ({job_name})"
            paths.append(BuildPath(source, _declared_in_blob(str(args), source)))

    dry_run = yaml.safe_load((workflows / "_check-docker-dry-run.yml").read_text())
    for job_name, job in (dry_run.get("jobs") or {}).items():
        for entry in ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []:
            if entry.get("image") != SYN_API:
                continue
            source = f"_check-docker-dry-run.yml ({job_name}, {entry.get('arch')})"
            paths.append(
                BuildPath(source, _declared_in_blob(str(entry.get("build-args", "")), source))
            )

    assert paths, "found no workflow build paths - the parser has gone stale"
    return paths


def _declared_in_blob(blob: str, source: str) -> str | None:
    """Pull ARG's value out of a `KEY=VALUE` build-args blob, if it sets one."""
    match = re.search(rf"^\s*{ARG}=(.*)$", blob, re.MULTILINE)
    return None if match is None else _resolve_for_syn_api(match[1], source)


def _syn_api_build_paths() -> list[BuildPath]:
    return [
        *_compose_build_paths(),
        _release_local_build_path(),
        *_workflow_build_paths(),
    ]


@pytest.mark.architecture
def test_every_syn_api_build_path_includes_the_docker_cli() -> None:
    """No build path may produce a syn-api image that cannot start a workspace.

    A path that passes nothing is measured at the Dockerfile default, because
    that is what it actually builds.
    """
    default = _dockerfile_default()
    broken = [
        f"{path.source}: {ARG} resolves to {path.effective(default)!r}"
        for path in _syn_api_build_paths()
        if path.effective(default) != "1"
    ]
    assert not broken, (
        "These paths build a syn-api image with no Docker CLI. It answers /health "
        "and fails every workflow execution at bootstrap (#1216):\n"
        + "\n".join(f"  - {b}" for b in broken)
        + f"\n(Dockerfile default is {default!r}; a path listing no value inherits it.)"
    )


@pytest.mark.architecture
def test_release_local_verifies_every_image_it_builds() -> None:
    """Build args can drift again; the post-build assertion is what survives it.

    `release-local` must hand each image it pushes to
    `verify-image-capabilities`, and that recipe must have a capability list
    for it - an image it does not recognise is refused, not waved through.
    """
    release_local = _justfile_recipe_body("release-local")
    assert "verify-image-capabilities" in release_local, (
        "release-local pushes images without asserting they work. Passing the "
        "build arg is not enough: only inspecting the built image catches a "
        "binary that stopped being installed for some other reason."
    )

    known = _case_arms(_justfile_recipe_body("verify-image-capabilities"))
    unlisted = [image for image in _release_local_images() if image not in known]
    assert not unlisted, (
        f"release-local builds {unlisted} but verify-image-capabilities has no "
        "capability list for them."
    )


@pytest.mark.architecture
def test_syn_api_capabilities_cover_the_binaries_that_fail_closed() -> None:
    """The capability list must name the binaries whose absence stops executions.

    Both `docker` and `cosign` are looked up with shutil.which in
    image_verification.py and both fail closed. Verifying an image without
    checking them would pass on precisely the image that broke production.
    """
    arms = _case_arms(_justfile_recipe_body("verify-image-capabilities"))
    assert SYN_API in arms, "verify-image-capabilities has no syn-api arm"
    match = re.search(r'required="([^"]*)"', arms[SYN_API])
    assert match is not None, "syn-api arm sets no `required` list"
    required = set(match[1].split())
    assert {"docker", "cosign"} <= required, (
        f"syn-api must be verified for docker and cosign; got {sorted(required)}"
    )
