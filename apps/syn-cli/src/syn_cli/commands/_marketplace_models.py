"""Pydantic models for the workflow marketplace system.

Defines the marketplace index (``marketplace.json``), per-plugin
manifest (``syntropic137-plugin.json``), registry configuration, and
cache metadata.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# marketplace.json — marketplace index (repo root)
# ---------------------------------------------------------------------------


class SyntropicMarker(BaseModel):
    """The ``syntropic137`` key in ``marketplace.json``.

    Identifies a GitHub repo as a Syntropic137 workflow marketplace.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str  # "workflow-marketplace"
    min_platform_version: str = "0.0.0"


class MarketplacePluginEntry(BaseModel):
    """A single plugin listed in ``marketplace.json``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = Field(..., min_length=1)
    source: str  # relative path within repo, e.g. "./plugins/research-toolkit"
    version: str = "0.1.0"
    description: str = ""
    category: str = ""
    tags: list[str] = Field(default_factory=list)


class MarketplaceIndex(BaseModel):
    """Parsed ``marketplace.json`` from a marketplace repository."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = Field(..., min_length=1)
    syntropic137: SyntropicMarker
    plugins: list[MarketplacePluginEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Registry configuration — ~/.syntropic137/registries.json
# ---------------------------------------------------------------------------


class RegistryEntry(BaseModel):
    """A registered marketplace source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str  # "syntropic137/workflow-library"
    ref: str = "main"
    added_at: str  # ISO 8601


class RegistryConfig(BaseModel):
    """Local registry of known marketplace sources.

    Stored at ``~/.syntropic137/registries.json``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    registries: dict[str, RegistryEntry] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cache metadata
# ---------------------------------------------------------------------------


class CachedMarketplace(BaseModel):
    """Cached marketplace index with freshness metadata.

    Stored at ``~/.syntropic137/marketplace/cache/<name>.json``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fetched_at: str  # ISO 8601
    index: MarketplaceIndex
