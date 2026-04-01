"""Marketplace client — fetch, cache, and search marketplace indexes.

Pure-function module with no CLI concerns.  Fetches ``marketplace.json``
from GitHub repositories, caches locally, and provides discovery
functions for searching across registered marketplaces.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from syn_cli.commands._marketplace_models import (
    CachedMarketplace,
    MarketplaceIndex,
    MarketplacePluginEntry,
    RegistryConfig,
    RegistryEntry,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SYN_DIR = Path.home() / ".syntropic137"
_REGISTRIES_PATH = _SYN_DIR / "registries.json"
_CACHE_DIR = _SYN_DIR / "marketplace" / "cache"
_CACHE_TTL = timedelta(hours=4)


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------


def load_registries() -> RegistryConfig:
    """Load the registry configuration, creating a default if absent."""
    if not _REGISTRIES_PATH.exists():
        return RegistryConfig()
    return RegistryConfig.model_validate_json(
        _REGISTRIES_PATH.read_text(encoding="utf-8"),
    )


def save_registries(config: RegistryConfig) -> None:
    """Persist the registry configuration to disk."""
    _SYN_DIR.mkdir(parents=True, exist_ok=True)
    _REGISTRIES_PATH.write_text(
        config.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------


def load_cached_index(registry_name: str) -> CachedMarketplace | None:
    """Load a cached marketplace index by registry name."""
    cache_path = _CACHE_DIR / f"{registry_name}.json"
    if not cache_path.exists():
        return None
    try:
        return CachedMarketplace.model_validate_json(
            cache_path.read_text(encoding="utf-8"),
        )
    except (json.JSONDecodeError, ValueError):
        return None


def save_cached_index(registry_name: str, cached: CachedMarketplace) -> None:
    """Persist a cached marketplace index to disk."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _CACHE_DIR / f"{registry_name}.json"
    cache_path.write_text(
        cached.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def is_cache_stale(cached: CachedMarketplace) -> bool:
    """Check whether a cached index has exceeded the TTL."""
    fetched = datetime.fromisoformat(cached.fetched_at)
    return datetime.now(tz=UTC) - fetched > _CACHE_TTL


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def fetch_marketplace_json(repo: str, ref: str = "main") -> MarketplaceIndex:
    """Fetch and parse ``marketplace.json`` from a GitHub repository.

    Uses a shallow git clone (same pattern as
    :func:`~syn_cli.commands._package_resolver.resolve_from_git`).

    Args:
        repo: GitHub repo in ``org/repo`` format.
        ref: Git branch or tag (default ``main``).

    Raises:
        RuntimeError: If git clone fails or marketplace.json is invalid.
    """
    url = f"https://github.com/{repo}.git"
    tmpdir = Path(tempfile.mkdtemp(prefix="syn-mkt-"))
    try:
        result = subprocess.run(
            ["git", "clone", "--depth=1", "--branch", ref, url, str(tmpdir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            msg = f"git clone failed for {repo}: {result.stderr.strip()}"
            raise RuntimeError(msg)

        marketplace_path = tmpdir / "marketplace.json"
        if not marketplace_path.exists():
            msg = f"No marketplace.json found in {repo}"
            raise RuntimeError(msg)

        data = json.loads(marketplace_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            msg = f"marketplace.json must be a JSON object, got {type(data).__name__}"
            raise RuntimeError(msg)

        index = MarketplaceIndex.model_validate(data)

        # Validate the syntropic137 marker
        if index.syntropic137.type != "workflow-marketplace":
            msg = (
                f"Expected syntropic137.type='workflow-marketplace', "
                f"got '{index.syntropic137.type}'"
            )
            raise RuntimeError(msg)

        return index
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def refresh_index(
    registry_name: str,
    entry: RegistryEntry,
    *,
    force: bool = False,
) -> MarketplaceIndex:
    """Refresh a marketplace index, using cache when fresh.

    Args:
        registry_name: Key in the registry config.
        entry: The registry entry with repo and ref.
        force: Skip cache and always fetch.

    Returns:
        The (possibly cached) marketplace index.
    """
    if not force:
        cached = load_cached_index(registry_name)
        if cached is not None and not is_cache_stale(cached):
            return cached.index

    index = fetch_marketplace_json(entry.repo, entry.ref)
    save_cached_index(
        registry_name,
        CachedMarketplace(
            fetched_at=datetime.now(tz=UTC).isoformat(),
            index=index,
        ),
    )
    return index


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _matches_query(
    plugin: MarketplacePluginEntry,
    query: str,
) -> bool:
    """Check if a plugin matches a search query (case-insensitive)."""
    if not query:
        return True
    q = query.lower()
    return (
        q in plugin.name.lower()
        or q in plugin.description.lower()
        or q in plugin.category.lower()
        or any(q in tag.lower() for tag in plugin.tags)
    )


def search_all_registries(
    query: str = "",
    *,
    category: str | None = None,
    tag: str | None = None,
) -> list[tuple[str, MarketplacePluginEntry]]:
    """Search across all registered marketplaces.

    Returns a list of ``(registry_name, plugin_entry)`` tuples matching
    the query, category, and/or tag filters.
    """
    config = load_registries()
    results: list[tuple[str, MarketplacePluginEntry]] = []

    for name, entry in config.registries.items():
        try:
            index = refresh_index(name, entry)
        except RuntimeError:
            continue  # skip unreachable registries

        for plugin in index.plugins:
            if not _matches_query(plugin, query):
                continue
            if category and plugin.category.lower() != category.lower():
                continue
            if tag and not any(t.lower() == tag.lower() for t in plugin.tags):
                continue
            results.append((name, plugin))

    return results


def resolve_plugin_by_name(
    name: str,
    *,
    registry: str | None = None,
) -> tuple[str, RegistryEntry, MarketplacePluginEntry] | None:
    """Find a plugin by exact name across registered marketplaces.

    Args:
        name: Plugin name to look up.
        registry: Optional registry name to restrict search.

    Returns:
        ``(registry_name, registry_entry, plugin_entry)`` or ``None``.
    """
    config = load_registries()

    registries = config.registries.items()
    if registry:
        if registry not in config.registries:
            return None
        registries = [(registry, config.registries[registry])]

    for reg_name, entry in registries:
        try:
            index = refresh_index(reg_name, entry)
        except RuntimeError:
            continue

        for plugin in index.plugins:
            if plugin.name == name:
                return (reg_name, entry, plugin)

    return None


def get_git_head_sha(repo: str, ref: str = "main") -> str | None:
    """Get the current HEAD SHA for a repo ref without cloning.

    Uses ``git ls-remote``.  Returns ``None`` on failure.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{repo}.git", ref],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        # Output format: "<sha>\t<ref>"
        line = result.stdout.strip().split("\n")[0]
        if "\t" in line:
            return line.split("\t")[0]
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None
