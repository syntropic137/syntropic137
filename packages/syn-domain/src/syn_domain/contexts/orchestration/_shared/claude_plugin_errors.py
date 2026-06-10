# See ADR-066: typed domain errors live in syn-domain because they are part of
# the application contract; only manifest validation and registry-lookup errors
# remain after Phase A (#726). Source/version/auth fetch errors are CLI-tier
# concerns now (the API does no git work) and were dropped from this module.
"""Typed errors for the claude-plugin injection feature (issue #726).

After the #726 Phase A redesign, only two error families remain at the API
tier:

- Manifest validation errors raised by ``RegisterClaudePluginHandler`` when
  the uploaded tree is missing or has a malformed ``.claude-plugin/plugin.json``.
- ``ClaudePluginNotRegistered`` raised by ``AddGlobalClaudePluginHandler`` and
  ``ClaudePluginResolutionService`` when a referenced plugin has not yet been
  registered via ``POST /claude-plugins/registrations``.

The previous ``ClaudePluginSourceUnreachable`` / ``ClaudePluginVersionNotFound``
/ ``ClaudePluginAuthRequired`` errors were CLI-emitted (git clone failures) and
no longer exist at the API tier; the CLI surfaces those failures locally before
ever calling the API.
"""

from __future__ import annotations


class ClaudePluginError(Exception):
    """Base class for claude-plugin registration errors."""

    error_code: str = "claude_plugin_error"


class ClaudePluginManifestMissing(ClaudePluginError):
    """The uploaded tree does not contain `.claude-plugin/plugin.json`."""

    error_code = "not_a_claude_plugin"

    def __init__(self, source_url: str, version: str) -> None:
        super().__init__(
            f"Source {source_url}@{version} is not a Claude plugin "
            f"(missing .claude-plugin/plugin.json)"
        )
        self.source_url = source_url
        self.version = version


class ClaudePluginManifestInvalid(ClaudePluginError):
    """The plugin.json exists but failed to parse or validate."""

    error_code = "claude_plugin_manifest_invalid"

    def __init__(self, source_url: str, version: str, detail: str) -> None:
        super().__init__(f"Invalid plugin.json in {source_url}@{version}: {detail}")
        self.source_url = source_url
        self.version = version
        self.detail = detail


class ClaudePluginInvalidName(ClaudePluginError):
    """A plugin name fails workspace-path safety validation.

    Raised at the materialization boundary when a registered plugin's name
    would be unsafe to interpolate into a workspace-relative path (issue
    #726). Path-traversal, absolute-path, control-character, and empty names
    are rejected so the materializer cannot escape ``.syn-plugins/<name>/``.
    """

    error_code = "claude_plugin_invalid_name"

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(
            f"Claude plugin name {name!r} is invalid: {reason}. "
            "Names must be a single path segment without separators, traversal, "
            "control characters, or leading dots."
        )
        self.name = name
        self.reason = reason


class ClaudePluginNotRegistered(ClaudePluginError):
    """A referenced plugin is not present in the lock projection.

    Raised by ``AddGlobalClaudePluginHandler`` (when the caller asks to add an
    unknown ``(name, version)`` to the global set) and by
    ``ClaudePluginResolutionService.ensure_registered`` (when a workflow YAML
    declares a plugin that has not been registered yet). Per the #726 Phase A
    redesign the API does not fetch on demand; the CLI must register the plugin
    via ``POST /claude-plugins/registrations`` first.
    """

    error_code = "claude_plugin_not_registered"

    def __init__(self, name: str, version: str) -> None:
        super().__init__(
            f"Claude plugin {name}@{version} is not registered. "
            "Register the plugin first via POST /claude-plugins/registrations "
            "(or run `syn claude-plugin install` from the CLI)."
        )
        self.name = name
        self.version = version
