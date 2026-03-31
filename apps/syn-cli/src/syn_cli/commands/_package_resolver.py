"""Workflow package resolver — detection, resolution, and git download.

Detects the package format (single workflow, multi-workflow plugin, or
standalone YAML), resolves all ``prompt_file`` and ``shared://``
references, and produces :class:`ResolvedWorkflow` payloads ready to
POST to the Syntropic137 API.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from syn_cli.commands._package_models import (
    InstallationRecord,
    InstalledRegistry,
    InstalledWorkflowRef,
    PackageFormat,
    PluginManifest,
    ResolvedWorkflow,
)

# ---------------------------------------------------------------------------
# Installed registry I/O
# ---------------------------------------------------------------------------

_INSTALLED_DIR = Path.home() / ".syntropic137" / "workflows"
_INSTALLED_PATH = _INSTALLED_DIR / "installed.json"


def load_installed() -> InstalledRegistry:
    """Load the local installation registry, creating a default if absent."""
    if not _INSTALLED_PATH.exists():
        return InstalledRegistry()
    return InstalledRegistry.model_validate_json(_INSTALLED_PATH.read_text(encoding="utf-8"))


def save_installed(registry: InstalledRegistry) -> None:
    """Persist the installation registry to disk."""
    _INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
    _INSTALLED_PATH.write_text(
        registry.model_dump_json(indent=2),
        encoding="utf-8",
    )


def record_installation(
    *,
    package_name: str,
    package_version: str,
    source: str,
    source_ref: str,
    fmt: PackageFormat,
    workflows: list[InstalledWorkflowRef],
) -> None:
    """Append an installation record and persist."""
    registry = load_installed()
    record = InstallationRecord(
        package_name=package_name,
        package_version=package_version,
        source=source,
        source_ref=source_ref,
        installed_at=datetime.now(tz=UTC).isoformat(),
        format=fmt.value,
        workflows=workflows,
    )
    updated = InstalledRegistry(
        version=registry.version,
        installations=[*registry.installations, record],
    )
    save_installed(updated)


# ---------------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------------


def parse_source(source: str) -> tuple[str, bool]:
    """Classify a source string as local path or remote.

    Returns:
        (resolved_source, is_remote) where resolved_source is the
        original path or a full git URL.
    """
    # Explicit URLs
    if source.startswith(("https://", "http://", "git@", "ssh://")):
        return (source, True)

    # Local paths (absolute, relative with ./ or ../, or contains os separator)
    path = Path(source)
    if path.exists() or source.startswith((".", "/")):
        return (source, False)

    # GitHub shorthand: org/repo (use --ref flag for branch/tag)
    if "/" in source and "@" not in source and not source.startswith("."):
        return (f"https://github.com/{source}.git", True)

    # Fallback: treat as local path (will fail gracefully at detection)
    return (source, False)


# ---------------------------------------------------------------------------
# Package format detection
# ---------------------------------------------------------------------------


def _validate_package_path(path: Path) -> None:
    """Validate that a path exists and is a directory."""
    if not path.exists():
        msg = f"Package path does not exist: {path}"
        raise FileNotFoundError(msg)
    if not path.is_dir():
        msg = f"Package path is not a directory: {path}"
        raise ValueError(msg)


def _has_multi_workflow_layout(path: Path) -> bool:
    """Check if directory has workflows/*/workflow.yaml structure."""
    workflows_dir = path / "workflows"
    if not workflows_dir.is_dir():
        return False
    return any((d / "workflow.yaml").exists() for d in workflows_dir.iterdir() if d.is_dir())


def detect_format(path: Path) -> PackageFormat:
    """Detect the package format of a directory.

    Raises:
        FileNotFoundError: If path doesn't exist.
        ValueError: If no recognizable package format is found.
    """
    _validate_package_path(path)

    if _has_multi_workflow_layout(path):
        return PackageFormat.MULTI_WORKFLOW

    if (path / "workflow.yaml").exists():
        return PackageFormat.SINGLE_WORKFLOW

    yaml_files = list(path.glob("*.yaml")) + list(path.glob("*.yml"))
    if yaml_files:
        return PackageFormat.STANDALONE_YAML

    msg = (
        f"No workflow files found in {path}\n"
        "Expected: workflow.yaml, workflows/*/workflow.yaml, or *.yaml files"
    )
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> PluginManifest | None:
    """Load ``syntropic137.yaml`` manifest from a package directory.

    Returns None if the manifest file doesn't exist.
    """
    manifest_path = path / "syntropic137.yaml"
    if not manifest_path.exists():
        return None

    content = manifest_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        msg = f"syntropic137.yaml must be a YAML mapping, got {type(data).__name__}"
        raise ValueError(msg)

    return PluginManifest.model_validate(data)


# ---------------------------------------------------------------------------
# Single workflow resolution
# ---------------------------------------------------------------------------


def _resolve_single_workflow(
    workflow_dir: Path,
    *,
    phase_library_dir: Path | None = None,
    source_path: str = "",
) -> ResolvedWorkflow:
    """Load and fully resolve a single workflow package directory.

    Reads ``workflow.yaml``, resolves all ``prompt_file`` and
    ``shared://`` references, and returns a :class:`ResolvedWorkflow`
    ready to POST.
    """
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        WorkflowDefinition,
    )

    yaml_path = workflow_dir / "workflow.yaml"
    if not yaml_path.exists():
        msg = f"workflow.yaml not found in {workflow_dir}"
        raise FileNotFoundError(msg)

    definition = WorkflowDefinition.from_file(
        yaml_path,
        phase_library_dir=phase_library_dir,
    )

    # Convert phases to dicts for the API payload.
    phases: list[dict[str, object]] = [_phase_to_dict(p.to_domain()) for p in definition.phases]

    # Convert input declarations to dicts.
    input_decls: list[dict[str, object]] = [
        {"name": i.name, "description": i.description, "required": i.required, "default": i.default}
        for i in definition.inputs
    ]

    repo_url = (
        definition.repository.url
        if definition.repository
        else "https://github.com/placeholder/not-configured"
    )
    repo_ref = definition.repository.ref if definition.repository else "main"

    return ResolvedWorkflow(
        id=definition.id,
        name=definition.name,
        workflow_type=definition.type.value,
        classification=definition.classification.value,
        repository_url=repo_url,
        repository_ref=repo_ref,
        description=definition.description,
        project_name=definition.project_name,
        phases=phases,
        input_declarations=input_decls,
        source_path=source_path,
    )


def _phase_to_dict(phase: Any) -> dict[str, object]:
    """Convert a domain PhaseDefinition to a dict for the API payload."""
    return {
        "phase_id": phase.phase_id,
        "name": phase.name,
        "order": phase.order,
        "execution_type": phase.execution_type.value
        if hasattr(phase.execution_type, "value")
        else str(phase.execution_type),
        "description": phase.description,
        "input_artifact_types": phase.input_artifact_types,
        "output_artifact_types": phase.output_artifact_types,
        "prompt_template": phase.prompt_template,
        "max_tokens": phase.max_tokens,
        "timeout_seconds": phase.timeout_seconds,
        "allowed_tools": phase.allowed_tools,
        "argument_hint": phase.argument_hint,
        "model": phase.model,
    }


# ---------------------------------------------------------------------------
# Package resolution (all formats)
# ---------------------------------------------------------------------------


def _resolve_multi_workflow(path: Path, source: str) -> list[ResolvedWorkflow]:
    """Resolve all workflows in a multi-workflow plugin directory."""
    phase_library_dir = path / "phase-library"
    lib_dir = phase_library_dir if phase_library_dir.is_dir() else None

    workflows_dir = path / "workflows"
    resolved: list[ResolvedWorkflow] = []
    for subdir in sorted(workflows_dir.iterdir()):
        if subdir.is_dir() and (subdir / "workflow.yaml").exists():
            wf = _resolve_single_workflow(
                workflow_dir=subdir,
                phase_library_dir=lib_dir,
                source_path=source,
            )
            resolved.append(wf)
    return resolved


def _resolve_standalone_yaml(path: Path, source: str) -> list[ResolvedWorkflow]:
    """Resolve standalone YAML workflow files (legacy format)."""
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        load_workflow_definitions,
    )

    definitions = load_workflow_definitions(path)
    return [_definition_to_resolved(defn, source) for defn in definitions]


def _definition_to_resolved(defn: Any, source: str) -> ResolvedWorkflow:
    """Convert a WorkflowDefinition to a ResolvedWorkflow."""
    phases = [_phase_to_dict(p.to_domain()) for p in defn.phases]
    input_decls: list[dict[str, object]] = [
        {
            "name": i.name,
            "description": i.description,
            "required": i.required,
            "default": i.default,
        }
        for i in defn.inputs
    ]
    repo_url = (
        defn.repository.url if defn.repository else "https://github.com/placeholder/not-configured"
    )
    repo_ref = defn.repository.ref if defn.repository else "main"
    return ResolvedWorkflow(
        id=defn.id,
        name=defn.name,
        workflow_type=defn.type.value,
        classification=defn.classification.value,
        repository_url=repo_url,
        repository_ref=repo_ref,
        description=defn.description,
        project_name=defn.project_name,
        phases=phases,
        input_declarations=input_decls,
        source_path=source,
    )


def resolve_package(
    path: Path,
) -> tuple[PluginManifest | None, list[ResolvedWorkflow]]:
    """Detect format and resolve all workflows in a package directory.

    Returns:
        (manifest_or_none, list_of_resolved_workflows)
    """
    fmt = detect_format(path)
    manifest = load_manifest(path)
    source = str(path)

    if fmt == PackageFormat.SINGLE_WORKFLOW:
        workflow = _resolve_single_workflow(workflow_dir=path, source_path=source)
        return (manifest, [workflow])

    if fmt == PackageFormat.MULTI_WORKFLOW:
        return (manifest, _resolve_multi_workflow(path, source))

    if fmt == PackageFormat.STANDALONE_YAML:
        return (manifest, _resolve_standalone_yaml(path, source))

    msg = f"Unsupported package format: {fmt}"
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Git source resolution
# ---------------------------------------------------------------------------


def resolve_from_git(
    url: str,
    *,
    ref: str = "main",
) -> tuple[Path, PluginManifest | None, list[ResolvedWorkflow]]:
    """Clone a git repository and resolve its workflow packages.

    Returns:
        (tmpdir_path, manifest_or_none, resolved_workflows)

    The caller is responsible for cleaning up the temp directory.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="syn-pkg-"))
    cmd = ["git", "clone", "--depth=1", "--branch", ref, url, str(tmpdir)]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        msg = f"git clone failed: {result.stderr.strip()}"
        raise RuntimeError(msg)

    manifest, workflows = resolve_package(tmpdir)
    return (tmpdir, manifest, workflows)


# ---------------------------------------------------------------------------
# Scaffolding helpers for `syn workflow init`
# ---------------------------------------------------------------------------

_PHASE_MD_TEMPLATE = """\
---
model: sonnet
argument-hint: "[topic]"
allowed-tools: Read,Glob,Grep,Bash
max-tokens: 4096
timeout-seconds: 300
---

You are an AI assistant working on phase {phase_num}: {phase_name}.

Your task: $ARGUMENTS

Work thoroughly and report your findings.
"""

_WORKFLOW_YAML_TEMPLATE = """\
id: {workflow_id}
name: {workflow_name}
description: "{description}"
type: {workflow_type}
classification: standard

inputs:
  - name: task
    description: "The primary task to accomplish"
    required: true

phases:
{phases_yaml}"""

_README_TEMPLATE = """\
# {name}

{description}

## Usage

```bash
syn workflow install ./{dir_name}/
syn workflow run {workflow_id} --task "Your task here"
```

## Phases

{phase_list}
"""

_MANIFEST_TEMPLATE = """\
manifest_version: 1
name: {name}
version: "0.1.0"
description: "{description}"
"""


def scaffold_single_package(
    directory: Path,
    *,
    name: str,
    workflow_type: str = "research",
    num_phases: int = 3,
) -> None:
    """Scaffold a single-workflow package directory."""
    directory.mkdir(parents=True, exist_ok=True)
    phases_dir = directory / "phases"
    phases_dir.mkdir(exist_ok=True)

    workflow_id = name.lower().replace(" ", "-") + "-v1"
    phase_names = _generate_phase_names(workflow_type, num_phases)

    # Generate phase .md files
    phases_yaml_lines: list[str] = []
    for i, phase_name in enumerate(phase_names, start=1):
        phase_id = phase_name.lower().replace(" ", "-")
        md_path = phases_dir / f"{phase_id}.md"
        md_path.write_text(
            _PHASE_MD_TEMPLATE.format(phase_num=i, phase_name=phase_name),
            encoding="utf-8",
        )
        phases_yaml_lines.append(
            f"  - id: {phase_id}\n"
            f"    name: {phase_name}\n"
            f"    order: {i}\n"
            f"    execution_type: sequential\n"
            f"    prompt_file: phases/{phase_id}.md\n"
            f"    output_artifacts: [{phase_id}_output]"
        )

    # workflow.yaml
    workflow_yaml = _WORKFLOW_YAML_TEMPLATE.format(
        workflow_id=workflow_id,
        workflow_name=name,
        description=f"{name} workflow",
        workflow_type=workflow_type,
        phases_yaml="\n".join(phases_yaml_lines),
    )
    (directory / "workflow.yaml").write_text(workflow_yaml, encoding="utf-8")

    # README.md
    phase_list = "\n".join(f"- **Phase {i}:** {pn}" for i, pn in enumerate(phase_names, 1))
    readme = _README_TEMPLATE.format(
        name=name,
        description=f"{name} workflow",
        dir_name=directory.name,
        workflow_id=workflow_id,
        phase_list=phase_list,
    )
    (directory / "README.md").write_text(readme, encoding="utf-8")


def scaffold_multi_package(
    directory: Path,
    *,
    name: str,
    workflow_type: str = "research",
    num_phases: int = 3,
) -> None:
    """Scaffold a multi-workflow plugin package directory."""
    directory.mkdir(parents=True, exist_ok=True)

    # syntropic137.yaml manifest
    manifest = _MANIFEST_TEMPLATE.format(
        name=name.lower().replace(" ", "-"),
        description=f"{name} plugin",
    )
    (directory / "syntropic137.yaml").write_text(manifest, encoding="utf-8")

    # phase-library/ with a shared phase
    lib_dir = directory / "phase-library"
    lib_dir.mkdir(exist_ok=True)
    (lib_dir / "summarize.md").write_text(
        _PHASE_MD_TEMPLATE.format(phase_num="N", phase_name="Summarize"),
        encoding="utf-8",
    )

    # workflows/<name>/ — one starter workflow
    wf_name = name.lower().replace(" ", "-")
    wf_dir = directory / "workflows" / wf_name
    scaffold_single_package(
        wf_dir,
        name=name,
        workflow_type=workflow_type,
        num_phases=num_phases,
    )

    # README.md for the plugin
    readme = _README_TEMPLATE.format(
        name=f"{name} Plugin",
        description=f"Plugin containing {name} workflows and shared phases",
        dir_name=directory.name,
        workflow_id=wf_name + "-v1",
        phase_list=f"- **{name}** — {num_phases} phases",
    )
    (directory / "README.md").write_text(readme, encoding="utf-8")


def _generate_phase_names(workflow_type: str, count: int) -> list[str]:
    """Generate sensible default phase names based on workflow type."""
    presets: dict[str, list[str]] = {
        "research": ["Discovery", "Deep Dive", "Synthesis"],
        "implementation": ["Research", "Plan", "Execute", "Review", "Ship"],
        "review": ["Analyze", "Evaluate", "Report"],
        "planning": ["Gather Context", "Design", "Validate"],
        "deployment": ["Prepare", "Deploy", "Verify"],
    }
    names = presets.get(workflow_type, [])
    if len(names) >= count:
        return names[:count]
    # Pad with generic names
    while len(names) < count:
        names.append(f"Phase {len(names) + 1}")
    return names
