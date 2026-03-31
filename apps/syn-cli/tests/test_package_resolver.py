"""Tests for workflow package resolver — detection, resolution, and scaffolding."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from syn_cli.commands._package_models import PackageFormat
from syn_cli.commands._package_resolver import (
    detect_format,
    load_manifest,
    parse_source,
    resolve_package,
    scaffold_multi_package,
    scaffold_single_package,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_path_factory_fn():
    """Yield a temp directory that is cleaned up after the test."""
    dirs: list[tempfile.TemporaryDirectory[str]] = []

    def _make() -> Path:
        d = tempfile.TemporaryDirectory(prefix="syn-test-pkg-")
        dirs.append(d)
        return Path(d.name)

    yield _make

    for d in dirs:
        d.cleanup()


def _write_workflow_yaml(directory: Path, workflow_id: str = "test-v1") -> None:
    """Write a minimal valid workflow.yaml into a directory."""
    (directory / "workflow.yaml").write_text(
        f"""\
id: {workflow_id}
name: Test Workflow
type: research
classification: standard

inputs:
  - name: task
    description: "Test task"
    required: true

phases:
  - id: phase-1
    name: Phase One
    order: 1
    execution_type: sequential
    prompt_template: "Do the thing: $ARGUMENTS"
""",
        encoding="utf-8",
    )


def _write_phase_md(directory: Path, name: str = "phase-1") -> None:
    """Write a minimal .md phase prompt file."""
    phases_dir = directory / "phases"
    phases_dir.mkdir(exist_ok=True)
    (phases_dir / f"{name}.md").write_text(
        """\
---
model: sonnet
max-tokens: 4096
---

Do the thing: $ARGUMENTS
""",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# detect_format
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectFormat:
    def test_single_workflow(self, tmp_path: Path) -> None:
        _write_workflow_yaml(tmp_path)
        assert detect_format(tmp_path) == PackageFormat.SINGLE_WORKFLOW

    def test_multi_workflow(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows" / "research"
        wf_dir.mkdir(parents=True)
        _write_workflow_yaml(wf_dir)
        assert detect_format(tmp_path) == PackageFormat.MULTI_WORKFLOW

    def test_standalone_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "my-workflow.yaml").write_text("id: test\nname: Test\ntype: custom\nclassification: simple\nphases:\n  - id: p1\n    name: P1\n    order: 1\n    prompt_template: hi\n")
        assert detect_format(tmp_path) == PackageFormat.STANDALONE_YAML

    def test_unknown_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="No workflow files found"):
            detect_format(tmp_path)

    def test_nonexistent_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            detect_format(Path("/nonexistent/path"))

    def test_file_not_dir_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello")
        with pytest.raises(ValueError, match="not a directory"):
            detect_format(f)


# ---------------------------------------------------------------------------
# parse_source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseSource:
    def test_https_url(self) -> None:
        source, is_remote = parse_source("https://github.com/org/repo.git")
        assert is_remote is True
        assert source == "https://github.com/org/repo.git"

    def test_ssh_url(self) -> None:
        source, is_remote = parse_source("git@github.com:org/repo.git")
        assert is_remote is True

    def test_github_shorthand(self) -> None:
        source, is_remote = parse_source("org/repo")
        assert is_remote is True
        assert source == "https://github.com/org/repo.git"

    def test_local_path(self, tmp_path: Path) -> None:
        source, is_remote = parse_source(str(tmp_path))
        assert is_remote is False

    def test_relative_path(self) -> None:
        source, is_remote = parse_source("./my-package")
        assert is_remote is False

    def test_dot_dot_path(self) -> None:
        source, is_remote = parse_source("../my-package")
        assert is_remote is False


# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadManifest:
    def test_manifest_present(self, tmp_path: Path) -> None:
        (tmp_path / "syntropic137.yaml").write_text(
            "manifest_version: 1\nname: test-plugin\nversion: '2.0.0'\n"
        )
        manifest = load_manifest(tmp_path)
        assert manifest is not None
        assert manifest.name == "test-plugin"
        assert manifest.version == "2.0.0"

    def test_manifest_missing(self, tmp_path: Path) -> None:
        assert load_manifest(tmp_path) is None

    def test_manifest_extra_fields_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "syntropic137.yaml").write_text(
            "manifest_version: 1\nname: test\nfuture_field: value\n"
        )
        manifest = load_manifest(tmp_path)
        assert manifest is not None
        assert manifest.name == "test"


# ---------------------------------------------------------------------------
# resolve_package — single workflow
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveSinglePackage:
    def test_resolve_with_inline_prompt(self, tmp_path: Path) -> None:
        _write_workflow_yaml(tmp_path)
        manifest, workflows = resolve_package(tmp_path)
        assert manifest is None
        assert len(workflows) == 1
        assert workflows[0].name == "Test Workflow"
        assert workflows[0].id == "test-v1"
        assert len(workflows[0].phases) == 1

    def test_resolve_with_prompt_file(self, tmp_path: Path) -> None:
        phases_dir = tmp_path / "phases"
        phases_dir.mkdir()
        (phases_dir / "discover.md").write_text(
            "---\nmodel: sonnet\nmax-tokens: 2048\n---\n\nDo research: $ARGUMENTS\n"
        )
        (tmp_path / "workflow.yaml").write_text(
            """\
id: prompt-file-test-v1
name: Prompt File Test
type: research
classification: standard
phases:
  - id: discover
    name: Discover
    order: 1
    prompt_file: phases/discover.md
"""
        )
        _manifest, workflows = resolve_package(tmp_path)
        assert len(workflows) == 1
        wf = workflows[0]
        assert wf.phases[0]["prompt_template"] == "Do research: $ARGUMENTS"
        assert wf.phases[0]["max_tokens"] == 2048


# ---------------------------------------------------------------------------
# resolve_package — multi-workflow with shared://
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveMultiPackage:
    def test_resolve_multi_with_shared_phase(self, tmp_path: Path) -> None:
        # phase-library/
        lib_dir = tmp_path / "phase-library"
        lib_dir.mkdir()
        (lib_dir / "summarize.md").write_text(
            "---\nmodel: sonnet\n---\n\nSummarize the work.\n"
        )

        # workflows/research/
        wf_dir = tmp_path / "workflows" / "research"
        wf_dir.mkdir(parents=True)
        phases_dir = wf_dir / "phases"
        phases_dir.mkdir()
        (phases_dir / "investigate.md").write_text(
            "---\nmodel: opus\n---\n\nInvestigate: $ARGUMENTS\n"
        )
        (wf_dir / "workflow.yaml").write_text(
            """\
id: multi-research-v1
name: Multi Research
type: research
classification: standard
phases:
  - id: investigate
    name: Investigate
    order: 1
    prompt_file: phases/investigate.md
  - id: summarize
    name: Summarize
    order: 2
    prompt_file: shared://summarize
"""
        )

        _manifest, workflows = resolve_package(tmp_path)
        assert len(workflows) == 1
        wf = workflows[0]
        assert len(wf.phases) == 2
        assert wf.phases[0]["prompt_template"] == "Investigate: $ARGUMENTS"
        assert wf.phases[1]["prompt_template"] == "Summarize the work."


# ---------------------------------------------------------------------------
# shared:// security
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSharedSecurity:
    def test_shared_traversal_rejected(self, tmp_path: Path) -> None:
        """shared:// paths must not escape the phase-library directory."""
        lib_dir = tmp_path / "phase-library"
        lib_dir.mkdir()

        wf_dir = tmp_path / "workflows" / "evil"
        wf_dir.mkdir(parents=True)
        (wf_dir / "workflow.yaml").write_text(
            """\
id: evil-v1
name: Evil
type: custom
classification: simple
phases:
  - id: escape
    name: Escape
    order: 1
    prompt_file: shared://../../etc/passwd
"""
        )

        with pytest.raises(ValueError, match="escapes phase-library"):
            resolve_package(tmp_path)


# ---------------------------------------------------------------------------
# scaffold_single_package
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScaffoldSingle:
    def test_creates_valid_structure(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "my-workflow"
        scaffold_single_package(pkg_dir, name="My Workflow", num_phases=2)

        assert (pkg_dir / "workflow.yaml").exists()
        assert (pkg_dir / "README.md").exists()
        assert (pkg_dir / "phases").is_dir()
        # Should have 2 phase files
        phase_files = list((pkg_dir / "phases").glob("*.md"))
        assert len(phase_files) == 2

    def test_scaffolded_package_detects_as_single(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "test-pkg"
        scaffold_single_package(pkg_dir, name="Test")
        assert detect_format(pkg_dir) == PackageFormat.SINGLE_WORKFLOW


# ---------------------------------------------------------------------------
# scaffold_multi_package
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScaffoldMulti:
    def test_creates_valid_structure(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "my-plugin"
        scaffold_multi_package(pkg_dir, name="My Plugin", num_phases=2)

        assert (pkg_dir / "syntropic137.yaml").exists()
        assert (pkg_dir / "README.md").exists()
        assert (pkg_dir / "phase-library").is_dir()
        assert (pkg_dir / "workflows").is_dir()

    def test_scaffolded_package_detects_as_multi(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "test-plugin"
        scaffold_multi_package(pkg_dir, name="Test")
        assert detect_format(pkg_dir) == PackageFormat.MULTI_WORKFLOW
