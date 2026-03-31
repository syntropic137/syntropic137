"""Pydantic models for workflow package format and installation tracking.

Defines the package detection, plugin manifest (``syntropic137.yaml``),
resolved workflow payloads, and the local installation registry
(``~/.syntropic137/workflows/installed.json``).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Package format detection
# ---------------------------------------------------------------------------


class PackageFormat(str, Enum):
    """Detected layout of a workflow package directory."""

    SINGLE_WORKFLOW = "single"  # workflow.yaml at root
    MULTI_WORKFLOW = "multi"  # workflows/*/workflow.yaml
    STANDALONE_YAML = "standalone"  # *.yaml files at root (legacy compat)


# ---------------------------------------------------------------------------
# Plugin manifest — syntropic137.yaml
# ---------------------------------------------------------------------------


class PluginManifest(BaseModel):
    """Plugin manifest parsed from ``syntropic137.yaml``.

    ``extra="ignore"`` ensures forward compatibility — unknown fields
    added in future manifest versions are silently skipped.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    manifest_version: int = 1
    name: str = Field(..., min_length=1)
    version: str = "0.1.0"
    description: str | None = None
    author: str | None = None
    license: str | None = None
    repository: str | None = None


# ---------------------------------------------------------------------------
# Resolved workflow — ready to POST to API
# ---------------------------------------------------------------------------


class ResolvedWorkflow(BaseModel):
    """A fully-resolved workflow definition ready to POST to the API.

    All ``prompt_file`` and ``shared://`` references have been resolved
    to inline ``prompt_template`` values.  This model mirrors the
    ``CreateWorkflowRequest`` API contract.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    workflow_type: str = "custom"
    classification: str = "standard"
    repository_url: str = "https://github.com/placeholder/not-configured"
    repository_ref: str = "main"
    description: str | None = None
    project_name: str | None = None
    phases: list[dict[str, object]] = Field(..., min_length=1)
    input_declarations: list[dict[str, object]] = Field(default_factory=list)
    source_path: str = ""  # Provenance — where the package was loaded from


# ---------------------------------------------------------------------------
# Installation tracking — ~/.syntropic137/workflows/installed.json
# ---------------------------------------------------------------------------


class InstalledWorkflowRef(BaseModel):
    """Reference to a single workflow created during installation."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str


class InstallationRecord(BaseModel):
    """Record of a single package installation."""

    model_config = ConfigDict(frozen=True)

    package_name: str
    package_version: str
    source: str
    source_ref: str
    installed_at: str  # ISO 8601
    format: str  # PackageFormat value
    workflows: list[InstalledWorkflowRef] = Field(default_factory=list)


class InstalledRegistry(BaseModel):
    """Local registry of installed workflow packages.

    Stored at ``~/.syntropic137/workflows/installed.json``.
    """

    model_config = ConfigDict(frozen=True)

    version: int = 1
    installations: list[InstallationRecord] = Field(default_factory=list)
