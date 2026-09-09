"""Unit tests for the toolchain-pin gate (#1136).

Two things these deliberately do NOT do, because the gate they cover exists
precisely because both are easy to fake:

- They do not assert against a hand-written imitation of a Dockerfile or a
  workflow. The parsing cases read the REAL workspace image Dockerfile and the
  real onboarding script, so a change to how a version is spelled there fails
  here rather than passing against a copy of my recollection of it.
- They do not stop at the parsers. `TestTheRepositoryItself` drives the actual
  repository through the actual comparison, which is the thing that was wrong
  before this gate existed: uv was installed at three versions in this repo and
  every test in the suite passed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts.check_toolchain_pins import (
    REPO_ROOT,
    Sighting,
    evaluate,
    installer_files,
    reference_dockerfiles,
    text_sightings,
    workflow_file_sightings,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: Versions no installer in this repo names, so a case built from them cannot
#: pass by agreeing with the real pin.
FAKE = "9.9.9"
OTHER_FAKE = "8.8.8"


def _agreeing(version: str = FAKE) -> list[Sighting]:
    """The minimum a passing run needs: both tools, referenced and matching."""
    return [
        Sighting("just", "image", version, reference=True),
        Sighting("just", "somewhere", version),
        Sighting("uv", "image", version, reference=True),
        Sighting("uv", "somewhere", version),
    ]


class TestTheRepositoryItself:
    """The gate's verdict on the real files, minus the two legs that cannot be
    asserted from a test: CI workflows (unpinned until the diff on #1136 is
    applied by hand) and the binaries on PATH (environment, not repository)."""

    def _repo_sightings(self) -> list[Sighting]:
        found: list[Sighting] = []
        for path in reference_dockerfiles(REPO_ROOT):
            found.extend(text_sightings(path, str(path.relative_to(REPO_ROOT)), reference=True))
        for path in installer_files(REPO_ROOT):
            found.extend(text_sightings(path, str(path.relative_to(REPO_ROOT))))
        return found

    def test_the_workspace_images_are_readable_at_all(self) -> None:
        """Without these the reference is missing and everything below is vacuous."""
        for path in reference_dockerfiles(REPO_ROOT):
            assert path.is_file(), f"{path} is missing; run: just submodules-init"

    def test_every_installer_in_this_repo_names_the_image_version(self) -> None:
        """The invariant, over the real repository.

        Fails on the tree before this change: syn-api pinned uv 0.10.6,
        syn-collector pinned uv:latest, and the onboarding script pinned
        neither tool.
        """
        sightings = self._repo_sightings()
        for tool in ("just", "uv"):
            mine = [s for s in sightings if s.tool == tool]
            reference = next(s.version for s in mine if s.reference and s.version)
            disagreeing = [f"{s.where} -> {s.stated}" for s in mine if s.version != reference]
            assert not disagreeing, f"{tool} should be {reference} everywhere: {disagreeing}"

    def test_the_onboarding_script_pins_both_tools(self) -> None:
        """A contributor's machine is one of the environments that must agree.

        The script installed both tools unpinned, and a version scanner saw
        nothing at all there - no wrong number, just no number.
        """
        script = REPO_ROOT / "infra" / "scripts" / "bootstrap.sh"
        found = text_sightings(script, "bootstrap.sh")
        pinned = {s.tool: s.version for s in found}
        assert pinned.keys() == {"just", "uv"}
        assert all(v is not None for v in pinned.values()), f"unpinned: {pinned}"

    def test_the_gate_finds_the_dockerfiles_and_shell_scripts_but_not_submodules(self) -> None:
        """Discovery, not a list: a new unpinned Dockerfile must be in scope."""
        names = {p.relative_to(REPO_ROOT).as_posix() for p in installer_files(REPO_ROOT)}
        assert "packages/syn-collector/Dockerfile" in names
        assert "infra/docker/images/syn-api/Dockerfile" in names
        assert "infra/scripts/bootstrap.sh" in names
        assert not [n for n in names if n.startswith("lib/")], "submodules are separate repos"


class TestTheRealWorkspaceImage:
    def test_both_tools_are_read_out_of_the_actual_dockerfile(self) -> None:
        path = REPO_ROOT / "lib/agentic-primitives/providers/workspaces/omni-agent/Dockerfile"
        by_tool = {s.tool: s.version for s in text_sightings(path, "omni", reference=True)}
        assert by_tool["just"] == "1.58.0"
        assert by_tool["uv"] == "0.11.8"

    def test_the_sightings_are_marked_as_the_reference(self) -> None:
        path = REPO_ROOT / "lib/agentic-primitives/providers/workspaces/omni-agent/Dockerfile"
        assert all(s.reference for s in text_sightings(path, "omni", reference=True))


class TestAnInstallWithNoVersion:
    """The half of this bug that is written in invisible ink."""

    def test_an_unpinned_installer_is_a_sighting_rather_than_a_silence(
        self, tmp_path: Path
    ) -> None:
        script = tmp_path / "install.sh"
        script.write_text("curl -LsSf https://astral.sh/uv/install.sh | sh\n")
        found = text_sightings(script, "install.sh")
        assert [(s.tool, s.version) for s in found] == [("uv", None)]

    def test_a_versioned_installer_url_is_read_as_the_version(self, tmp_path: Path) -> None:
        script = tmp_path / "install.sh"
        script.write_text(f"curl -LsSf https://astral.sh/uv/{FAKE}/install.sh | sh\n")
        assert [s.version for s in text_sightings(script, "install.sh")] == [FAKE]

    def test_a_floating_tag_counts_as_no_version(self, tmp_path: Path) -> None:
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv\n")
        assert [s.version for s in text_sightings(dockerfile, "Dockerfile")] == [None]

    def test_a_version_set_once_covers_the_install_below_it(self, tmp_path: Path) -> None:
        """A shell script names the version at the top and spends it later."""
        script = tmp_path / "install.sh"
        script.write_text(
            f'JUST_VERSION="{FAKE}"\n'
            'curl -fsSL https://just.systems/install.sh | sh -s -- --tag "$JUST_VERSION"\n'
        )
        assert [(s.tool, s.version) for s in text_sightings(script, "x")] == [("just", FAKE)]


class TestCiSteps:
    _STEP = """
jobs:
  build:
    steps:
      - uses: extractions/setup-just@dd310ad # v2
{pin}
"""

    def test_a_step_with_no_version_input_is_reported_as_floating(self) -> None:
        found = workflow_file_sightings(self._STEP.format(pin=""), "ci.yml")
        assert [(s.tool, s.version) for s in found] == [("just", None)]

    def test_a_pinned_step_is_reported_at_its_version(self) -> None:
        pin = f'        with:\n          just-version: "{FAKE}"'
        found = workflow_file_sightings(self._STEP.format(pin=pin), "ci.yml")
        assert [s.version for s in found] == [FAKE]

    def test_an_unquoted_version_is_compared_by_meaning_not_by_yaml_type(self) -> None:
        """`just-version: 1.58` parses as a float and is NOT 1.58.0."""
        found = workflow_file_sightings(
            self._STEP.format(pin="        with:\n          just-version: 1.58"), "ci.yml"
        )
        assert [s.version for s in found] == ["1.58"]

    def test_a_composite_action_is_read_as_well_as_a_workflow(self) -> None:
        """Where an unpinned installer hides best."""
        document = "runs:\n  using: composite\n  steps:\n    - uses: astral-sh/setup-uv@v4\n"
        found = workflow_file_sightings(document, "actions/setup-x")
        assert [(s.tool, s.version, s.where) for s in found] == [
            ("uv", None, "actions/setup-x:runs (astral-sh/setup-uv)")
        ]

    def test_an_unrelated_action_is_not_a_sighting(self) -> None:
        document = "jobs:\n  b:\n    steps:\n      - uses: actions/checkout@v4\n"
        assert workflow_file_sightings(document, "ci.yml") == []


class TestVerdict:
    def test_agreement_passes(self) -> None:
        code, _ = evaluate(_agreeing())
        assert code == 0

    def test_one_disagreeing_installer_fails(self) -> None:
        code, lines = evaluate([*_agreeing(), Sighting("uv", "ci.yml:x", OTHER_FAKE)])
        assert code == 1
        assert any("ci.yml:x" in line for line in lines)
        assert any(OTHER_FAKE in line for line in lines)

    def test_an_unpinned_installer_fails_even_though_it_names_no_wrong_version(self) -> None:
        code, lines = evaluate([*_agreeing(), Sighting("just", "ci.yml:y", None)])
        assert code == 1
        assert any("<floating>" in line for line in lines)

    def test_a_tool_nothing_installs_fails_rather_than_passing_vacuously(self) -> None:
        just_only = [s for s in _agreeing() if s.tool == "just"]
        code, lines = evaluate(just_only)
        assert code == 1
        assert any("uv: no installer found" in line for line in lines)

    def test_a_reference_that_states_no_version_fails(self) -> None:
        """Otherwise a repo where NOTHING is pinned agrees with itself."""
        code, lines = evaluate(
            [
                Sighting("just", "image", None, reference=True),
                Sighting("just", "ci", None),
                Sighting("uv", "image", None, reference=True),
                Sighting("uv", "ci", None),
            ]
        )
        assert code == 1
        assert any("states no fixed version" in line for line in lines)

    def test_the_failure_names_the_version_to_install_and_the_ci_input(self) -> None:
        _, lines = evaluate([*_agreeing(), Sighting("just", "ci.yml:z", None)])
        report = "\n".join(lines)
        assert f'just-version: "{FAKE}"' in report
        assert f"--tag {FAKE}" in report

    def test_a_passing_run_reports_what_it_covered(self) -> None:
        """A green line that names no installers is a green line that checked none."""
        report = "\n".join(evaluate(_agreeing())[1])
        assert f"just {FAKE} (workspace image), 2 installer(s)" in report
        assert "somewhere" in report
