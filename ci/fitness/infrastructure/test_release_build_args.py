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

Measuring a path means reading whatever grammar it is written in. Compose
accepts ``args`` as a mapping OR as a list of ``KEY=VALUE`` strings; reading
only the mapping scored the list form as "declares nothing", which inherits the
safe default, which passes - a check that could not fail for a legal input it
claimed to cover. So every reader here refuses a shape it cannot parse rather
than skipping it, and the tests at the bottom of this file pin that: a silent
skip makes the collection under test exactly the collection that passes.

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
#: The compose file that names the syn-api Dockerfile. Every other compose
#: file overlays this one, so a scan that stops seeing it measures nothing.
BASE_COMPOSE = "docker-compose.yaml"

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


def _compose_args(raw: object, source: str) -> dict[str, str]:
    """Normalise a compose `build.args` value to a mapping of what it declares.

    Compose accepts two spellings and they build the same image::

        args:                         args:
          INCLUDE_DOCKER_CLI: "1"       - INCLUDE_DOCKER_CLI=1

    Reading only the first is how a check ends up unable to fail. `.get()` on
    the list form finds nothing, the path scores as "declares no value", and a
    path declaring no value inherits the Dockerfile default of 1 - so a path
    setting the arg to 0 in list form passed the invariant that exists to
    catch an arg set to 0.

    A bare `- KEY` (and its mapping twin, `KEY:` with no value) tells compose
    to take the value from the builder's environment, which is exactly what
    `KEY: ${KEY}` means. Spelling it that way leaves ONE unresolvable-value
    path rather than two: `_resolve_for_syn_api` already refuses `${...}`.
    """
    if raw is None:
        return {}

    pairs: list[tuple[str, str | None]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            pairs.append((str(key), None if value is None else str(value)))
    elif isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, str):
                pytest.fail(
                    f"{source}: build.args list entry {entry!r} is not a `KEY=VALUE` "
                    f"string. Teach this test the shape rather than leaving the "
                    f"path unmeasured."
                )
            key, assigned, value = entry.partition("=")
            pairs.append((key, value if assigned else None))
    else:
        pytest.fail(
            f"{source}: build.args is {type(raw).__name__}, neither a mapping nor a "
            f"`KEY=VALUE` list. A shape this test cannot read is a build arg that "
            f"can drift unobserved, which is the whole defect."
        )

    return {key: f"${{{key}}}" if value is None else value for key, value in pairs}


def _compose_build_path(config: object, source: str) -> BuildPath | None:
    """What one compose document declares about building syn-api.

    None means the document builds no `api` service at all - a true negative,
    not an omission: an overlay that only sets environment inherits the base
    file's build, and the base file is measured in its own right.

    Everything else is either a measurement or a loud failure. A shape this
    function cannot read is reported, never skipped, because a silent skip
    makes the set of measured paths exactly the set that passes.
    """
    if config is None:  # an empty document declares no services
        return None
    if not isinstance(config, dict):
        pytest.fail(f"{source}: not a YAML mapping ({type(config).__name__})")

    services = config.get("services") or {}
    if not isinstance(services, dict):
        pytest.fail(f"{source}: `services` is {type(services).__name__}, not a mapping")
    if "api" not in services:
        return None

    service = services["api"]
    if not isinstance(service, dict):
        pytest.fail(f"{source}: service `api` is {type(service).__name__}, not a mapping")
    if "build" not in service:
        return None

    build = service["build"]
    if isinstance(build, str):
        # Compose's short form: a context and no args, so this path builds at
        # the Dockerfile default like any other path that declares nothing.
        args: object = None
    elif isinstance(build, dict):
        args = build.get("args")
    else:
        pytest.fail(
            f"{source}: `build` is {type(build).__name__}, neither a mapping nor a context path"
        )

    declared = _compose_args(args, source).get(ARG)
    return BuildPath(source, None if declared is None else _resolve_for_syn_api(declared, source))


def _compose_build_paths() -> list[BuildPath]:
    """Every compose file whose `api` service participates in building syn-api.

    Overlays inherit the base service's context and dockerfile, so they count
    as build paths even though only the base names the Dockerfile.
    """
    paths: list[BuildPath] = []
    for compose_file in sorted((_repo_root() / "docker").glob("docker-compose*.yaml")):
        source = f"docker/{compose_file.name} (service api)"
        path = _compose_build_path(yaml.safe_load(compose_file.read_text()), source)
        if path is not None:
            paths.append(path)
    assert any(BASE_COMPOSE in path.source for path in paths), (
        f"docker/{BASE_COMPOSE} is the compose file that names the syn-api "
        "Dockerfile, so it must always be among the measured paths. A scan that "
        "no longer sees it is measuring nothing and would pass on anything."
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
            paths.append(BuildPath(source, _declared_in_blob(args, source)))

    dry_run = yaml.safe_load((workflows / "_check-docker-dry-run.yml").read_text())
    for job_name, job in (dry_run.get("jobs") or {}).items():
        for entry in ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []:
            if entry.get("image") != SYN_API:
                continue
            source = f"_check-docker-dry-run.yml ({job_name}, {entry.get('arch')})"
            paths.append(BuildPath(source, _declared_in_blob(entry.get("build-args"), source)))

    assert paths, "found no workflow build paths - the parser has gone stale"
    return paths


def _declared_in_blob(blob: object, source: str) -> str | None:
    """Pull ARG's value out of a `KEY=VALUE` build-args blob, if it sets one.

    `build-args` is a newline-separated string in both workflows, and anything
    else is refused rather than coerced. This used to read `str(blob)`, which
    turns a YAML list into `"['KEY=1']"` - a string the regex below does not
    match, scoring the path as "declares nothing". That is the same silent
    miss the compose list form had, one file over.
    """
    if blob is None:
        return None
    if not isinstance(blob, str):
        pytest.fail(
            f"{source}: build-args is {type(blob).__name__}, not a newline-separated "
            f"`KEY=VALUE` string. Teach this test the shape rather than leaving the "
            f"path unmeasured."
        )
    match = re.search(rf"^\s*{ARG}=(.*)$", blob, re.MULTILINE)
    return None if match is None else _resolve_for_syn_api(match[1], source)


def _syn_api_build_paths() -> list[BuildPath]:
    return [
        *_compose_build_paths(),
        _release_local_build_path(),
        *_workflow_build_paths(),
    ]


def _paths_missing_the_docker_cli(paths: list[BuildPath], default: str) -> list[str]:
    """The build paths that would produce an image with no Docker CLI.

    Named so the tests below can drive the invariant's own predicate instead
    of a copy of it: a fixture checked against a reimplementation only ever
    proves the fixture.
    """
    return [
        f"{path.source}: {ARG} resolves to {path.effective(default)!r}"
        for path in paths
        if path.effective(default) != "1"
    ]


@pytest.mark.architecture
def test_every_syn_api_build_path_includes_the_docker_cli() -> None:
    """No build path may produce a syn-api image that cannot start a workspace.

    A path that passes nothing is measured at the Dockerfile default, because
    that is what it actually builds.
    """
    default = _dockerfile_default()
    broken = _paths_missing_the_docker_cli(_syn_api_build_paths(), default)
    assert not broken, (
        "These paths build a syn-api image with no Docker CLI. It answers /health "
        "and fails every workflow execution at bootstrap (#1216):\n"
        + "\n".join(f"  - {b}" for b in broken)
        + f"\n(Dockerfile default is {default!r}; a path listing no value inherits it.)"
    )


# ---------------------------------------------------------------------------
# The invariant above is worth exactly as much as the parser underneath it. It
# read one of Compose's two `build.args` spellings, so a path setting the arg
# to 0 in the other spelling scored as "declares nothing", inherited the safe
# Dockerfile default, and passed. These pin the parser against documents built
# in the test, since the repository has no file in the shape that got through -
# which is the point: the check must fail for input it claims to cover whether
# or not that input happens to exist today.
#
# They carry `architecture` because that is the marker `just fitness-invariants`
# selects (`pytest ci/fitness/ -m architecture`), and it is the only runner this
# directory has. An unmarked test here is collected by no CI job at all.
# ---------------------------------------------------------------------------


def _compose_doc(args: object) -> dict[str, object]:
    """A minimal compose document whose `api` service declares `args`."""
    return {"services": {"api": {"build": {"context": "..", "args": args}}}}


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("spelling", "args"),
    [("mapping", {ARG: "0"}), ("list", [f"{ARG}=0"])],
)
def test_a_path_that_disables_the_docker_cli_is_caught_in_either_spelling(
    spelling: str, args: object
) -> None:
    """Compose's two spellings build the same image and must measure the same.

    The list form is the one that got through. `args.get(ARG)` on a list finds
    nothing, so the path scored as "declares no value", and a path declaring no
    value inherits the Dockerfile default of 1 - meaning an explicit 0 passed
    the check whose entire purpose is to catch an explicit 0.
    """
    path = _compose_build_path(_compose_doc(args), f"{spelling}.yaml")
    assert path is not None, f"{spelling} form was not seen as a build path at all"
    assert path.declared == "0", f"{spelling} form read as {path.declared!r}, not '0'"
    assert _paths_missing_the_docker_cli([path], "1") == [f"{spelling}.yaml: {ARG} resolves to '0'"]


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("spelling", "args"),
    [
        ("mapping", {ARG: "1"}),
        ("mapping beside another arg", {"INCLUDE_OP_CLI": "0", ARG: "1"}),
        ("list", [f"{ARG}=1"]),
        ("list beside another arg", ["INCLUDE_OP_CLI=0", f"{ARG}=1"]),
        ("list with an = in the value", [f"{ARG}=1", "LABEL=a=b"]),
    ],
)
def test_a_correctly_configured_path_passes_in_either_spelling(spelling: str, args: object) -> None:
    """Reading both spellings must not turn every list-form path into a failure.

    Measured against a Dockerfile default of 0, so the pass can only come from
    the declared value. Asserting a default in its own direction proves nothing.
    """
    path = _compose_build_path(_compose_doc(args), f"{spelling}.yaml")
    assert path is not None, f"{spelling} form was not seen as a build path at all"
    assert path.declared == "1", f"{spelling} form read as {path.declared!r}, not '1'"
    assert _paths_missing_the_docker_cli([path], "0") == []


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("shape", "document"),
    [
        ("build.args as a bare string", _compose_doc(f"{ARG}=1")),
        ("build.args as a list of pairs", _compose_doc([[ARG, "1"]])),
        ("build.args as a number", _compose_doc(1)),
        ("build as a list", {"services": {"api": {"build": ["context: .."]}}}),
        ("service api as a string", {"services": {"api": "api"}}),
        ("services as a list", {"services": ["api"]}),
        ("the document as a list", ["services"]),
    ],
)
def test_an_unreadable_build_path_is_reported_not_skipped(shape: str, document: object) -> None:
    """A path this test cannot read must fail loudly, naming the file.

    Scoring it as "declares nothing" instead is what let the list form through:
    it makes the collection under test exactly the collection that passes, so
    the check cannot fail for a whole class of input it claims to cover.
    """
    with pytest.raises(pytest.fail.Exception) as failure:
        _compose_build_path(document, "unreadable.yaml")
    assert "unreadable.yaml" in str(failure.value), f"{shape} was reported without naming the file"


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("spelling", "args"),
    [("bare list entry", [ARG]), ("valueless mapping key", {ARG: None})],
)
def test_a_value_taken_from_the_builder_environment_is_reported(
    spelling: str, args: object
) -> None:
    """`- KEY` and `KEY:` both mean "whatever the builder's environment holds".

    That is not a value this repository can read, and scoring it as "declares
    nothing" would credit it with a Dockerfile default it may well not get.
    """
    with pytest.raises(pytest.fail.Exception) as failure:
        _compose_build_path(_compose_doc(args), f"{spelling}.yaml")
    assert "cannot resolve" in str(failure.value)


@pytest.mark.architecture
def test_the_short_form_build_is_measured_rather_than_skipped() -> None:
    """`build: ./context` is a real build path that declares no args.

    Requiring `build` to be a mapping dropped it from the measurement
    entirely - the same silent omission as the list form, one key up.
    """
    path = _compose_build_path({"services": {"api": {"build": ".."}}}, "short-form.yaml")
    assert path is not None, "the short form was skipped, not measured"
    assert path.declared is None
    assert _paths_missing_the_docker_cli([path], "0") == [f"short-form.yaml: {ARG} resolves to '0'"]


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("shape", "document"),
    [
        ("an overlay that only sets environment", {"services": {"api": {"environment": {}}}}),
        ("a file with no api service", {"services": {"cloudflared": {"image": "x"}}}),
        ("an empty document", None),
    ],
)
def test_a_document_that_builds_no_api_service_is_not_a_build_path(
    shape: str, document: object
) -> None:
    """Not every compose file builds syn-api, and that is a true negative.

    docker-compose.syntropic137.yaml overrides the api service's environment
    and declares no `build`; the base file it layers onto is measured on its
    own. The staleness guard in `_compose_build_paths` is what stops this
    branch from quietly swallowing every file.
    """
    assert _compose_build_path(document, f"{shape}.yaml") is None


@pytest.mark.architecture
def test_a_workflow_build_args_block_that_is_not_a_string_is_reported() -> None:
    """The workflow reader refuses the same shape the compose reader does.

    `str()` on a list yields `"['KEY=0']"`, which the `KEY=VALUE` regex misses,
    scoring an explicit 0 as "declares nothing" - the compose defect exactly,
    in the other parser.
    """
    with pytest.raises(pytest.fail.Exception) as failure:
        _declared_in_blob([f"{ARG}=0"], "some-workflow.yml (job)")
    assert "some-workflow.yml" in str(failure.value)


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
