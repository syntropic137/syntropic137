#!/usr/bin/env python3
"""Generate MDX documentation for the syn CLI from Typer introspection.

This script imports the Typer app, converts it to a Click command tree via
typer.main.get_command(), then walks all groups and commands to extract help
text, arguments, and options.  It writes one MDX file per command group under
content/docs/cli/, plus updates index.mdx and meta.json.

The script uses stub modules for heavy internal dependencies (httpx, pydantic
models, etc.) so it only requires `typer` (which pulls in `click` and `rich`)
to be installed.  This makes it runnable in CI or the docs build without
needing the full syn-cli virtualenv.

Usage (from the syntropic137 repo root):
    python apps/syn-docs/scripts/generate-cli-docs.py

Or with uv:
    uv run --with typer python apps/syn-docs/scripts/generate-cli-docs.py

The script can also be wired into the docs build via package.json:
    "generate:cli": "python scripts/generate-cli-docs.py"
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_DOCS_ROOT = _SCRIPT_DIR.parent  # apps/syn-docs
_CLI_SRC = _DOCS_ROOT.parent / "syn-cli" / "src"

# ---------------------------------------------------------------------------
# Stub out heavy dependencies so we can import syn_cli.main without needing
# the full environment (httpx, pydantic, syn_shared, etc.).
# ---------------------------------------------------------------------------

_STUB_MODULES = [
    "httpx",
    "pydantic",
    "syn_shared",
    "syn_shared.settings",
]


def _create_stub_module(name: str) -> types.ModuleType:
    """Create a stub module that returns MagicMock for any attribute access.

    Uses a custom module subclass so that any attribute access returns a
    usable stub, allowing arbitrary `from foo import Bar` to succeed.
    """

    class _AutoStubModule(types.ModuleType):
        """Module that auto-creates stubs for any attribute."""

        def __getattr__(self, item: str) -> object:
            # Return a callable class-like stub that can be used as a base class,
            # decorator, or called directly.
            stub = MagicMock()
            setattr(self, item, stub)
            return stub

    mod = _AutoStubModule(name)
    mod.__path__ = []  # type: ignore[attr-defined]
    mod.__file__ = f"<stub:{name}>"
    mod.__all__ = []  # type: ignore[attr-defined]

    # Pydantic-specific stubs so `class Foo(BaseModel): ...` works
    if "pydantic" in name:

        class StubBaseModel:
            model_config: dict[str, object] = {}

            def __init_subclass__(cls, **kwargs: object) -> None:
                pass

            def __init__(self, **kwargs: object) -> None:
                for k, v in kwargs.items():
                    setattr(self, k, v)

        mod.BaseModel = StubBaseModel  # type: ignore[attr-defined]
        mod.ConfigDict = lambda **kw: {}  # type: ignore[attr-defined]
        mod.Field = lambda *a, **kw: None  # type: ignore[attr-defined]

    return mod


class _StubFinder:
    """A sys.meta_path finder that intercepts imports for stubbed packages."""

    def __init__(self, stub_prefixes: list[str]) -> None:
        self._prefixes = sorted(stub_prefixes, key=len, reverse=True)

    def find_module(self, fullname: str, path: object = None) -> _StubFinder | None:
        for prefix in self._prefixes:
            if fullname == prefix or fullname.startswith(prefix + "."):
                return self
        return None

    def load_module(self, fullname: str) -> types.ModuleType:
        if fullname in sys.modules:
            return sys.modules[fullname]
        mod = _create_stub_module(fullname)
        sys.modules[fullname] = mod
        return mod


def _install_stubs() -> None:
    """Install stub modules and the meta-path finder."""
    for name in _STUB_MODULES:
        if name not in sys.modules:
            sys.modules[name] = _create_stub_module(name)
    sys.meta_path.insert(0, _StubFinder(_STUB_MODULES))


def _patch_syn_cli_internals() -> None:
    """Pre-populate syn_cli internal modules with stubs.

    The command modules import from syn_cli.client, syn_cli._output, etc.
    We stub those so the Typer app objects and their decorators still work
    (they only need typer + click), but the runtime helpers are mocked.
    """
    # Ensure syn_cli package exists
    if str(_CLI_SRC) not in sys.path:
        sys.path.insert(0, str(_CLI_SRC))

    # Create the base package
    import syn_cli  # noqa: F401 — just ensure it's imported

    # Stub internal modules that hit network/heavy deps
    stub_internals = [
        "syn_cli.client",
        "syn_cli._output",
        "syn_cli.__version__",
    ]
    for name in stub_internals:
        if name not in sys.modules:
            mod = _create_stub_module(name)
            # _output needs specific names that commands import
            if name == "syn_cli._output":
                mock = MagicMock()
                for attr in [
                    "console",
                    "print_error",
                    "print_success",
                    "format_timestamp",
                    "format_cost",
                    "format_tokens",
                    "format_duration",
                    "format_breakdown",
                    "format_status",
                    "status_style",
                ]:
                    setattr(mod, attr, mock)
            if name == "syn_cli.client":
                for attr in ["get_client", "get_api_url", "get_streaming_client"]:
                    setattr(mod, attr, MagicMock())
            sys.modules[name] = mod


# ---------------------------------------------------------------------------
# Typer -> Click introspection
# ---------------------------------------------------------------------------

import click  # noqa: E402


@dataclass
class ParamInfo:
    """Extracted info about a CLI parameter (argument or option)."""

    name: str
    param_type: str  # "argument" or "option"
    type_str: str
    required: bool
    default: str | None
    help: str
    opts: list[str] = field(default_factory=list)


@dataclass
class CommandInfo:
    """Extracted info about a single CLI command."""

    name: str
    help: str
    params: list[ParamInfo]


@dataclass
class GroupInfo:
    """Extracted info about a command group (syn <group>)."""

    name: str
    help: str
    commands: list[CommandInfo]


def _type_name(param: click.Parameter) -> str:
    """Get a human-readable type string for a Click parameter."""
    t = param.type
    if isinstance(t, click.types.Choice):
        return " | ".join(f'"{c}"' for c in t.choices)
    name = getattr(t, "name", str(t))
    mapping = {
        "TEXT": "string",
        "INT": "integer",
        "FLOAT": "float",
        "BOOL": "boolean",
        "PATH": "path",
        "FILENAME": "path",
        "UUID": "string",
    }
    return mapping.get(name, name.lower())


def _default_str(param: click.Parameter) -> str | None:
    """Render the default value, or None if not applicable."""
    if param.default is None or param.required:
        return None
    if isinstance(param.default, bool):
        return str(param.default).lower()
    if isinstance(param.default, (list, tuple)) and not param.default:
        return None
    return str(param.default)


def _extract_params(cmd: click.Command) -> list[ParamInfo]:
    """Extract parameters from a Click command."""
    params: list[ParamInfo] = []
    for p in cmd.params:
        if p.name == "help":
            continue
        if isinstance(p, click.Argument):
            params.append(
                ParamInfo(
                    name=p.name or "",
                    param_type="argument",
                    type_str=_type_name(p),
                    required=p.required,
                    default=_default_str(p),
                    help=getattr(p, "help", "") or p.make_metavar() or "",
                    opts=[],
                )
            )
        elif isinstance(p, click.Option):
            params.append(
                ParamInfo(
                    name=p.name or "",
                    param_type="option",
                    type_str=_type_name(p),
                    required=p.required,
                    default=_default_str(p),
                    help=p.help or "",
                    opts=list(p.opts),
                )
            )
    return params


def _extract_command(name: str, cmd: click.Command) -> CommandInfo:
    """Extract a single command's metadata."""
    return CommandInfo(
        name=name,
        help=(cmd.help or cmd.short_help or "").strip(),
        params=_extract_params(cmd),
    )


def extract_cli_tree(
    click_group: click.Group,
) -> tuple[list[GroupInfo], list[CommandInfo]]:
    """Walk the Click command tree and extract all groups and top-level commands."""
    groups: list[GroupInfo] = []
    top_level: list[CommandInfo] = []

    for cmd_name in sorted(click_group.list_commands(click.Context(click_group))):
        cmd = click_group.get_command(click.Context(click_group), cmd_name)
        if cmd is None:
            continue

        if isinstance(cmd, click.Group):
            sub_commands: list[CommandInfo] = []
            for sub_name in sorted(cmd.list_commands(click.Context(cmd))):
                sub_cmd = cmd.get_command(click.Context(cmd), sub_name)
                if sub_cmd is not None:
                    sub_commands.append(_extract_command(sub_name, sub_cmd))
            groups.append(
                GroupInfo(
                    name=cmd_name,
                    help=(cmd.help or cmd.short_help or "").strip(),
                    commands=sub_commands,
                )
            )
        else:
            top_level.append(_extract_command(cmd_name, cmd))

    return groups, top_level


# ---------------------------------------------------------------------------
# MDX rendering
# ---------------------------------------------------------------------------


def _render_param_table(params: list[ParamInfo]) -> str:
    """Render a Markdown table of parameters."""
    args = [p for p in params if p.param_type == "argument"]
    opts = [p for p in params if p.param_type == "option"]
    lines: list[str] = []

    if args:
        lines.append("**Arguments:**")
        lines.append("")
        lines.append("| Name | Type | Required | Description |")
        lines.append("|------|------|----------|-------------|")
        for a in args:
            req = "Yes" if a.required else "No"
            lines.append(f"| `{a.name}` | `{a.type_str}` | {req} | {a.help} |")
        lines.append("")

    if opts:
        lines.append("**Options:**")
        lines.append("")
        lines.append("| Flag | Type | Default | Description |")
        lines.append("|------|------|---------|-------------|")
        for o in opts:
            flags = ", ".join(f"`{f}`" for f in o.opts) if o.opts else f"`--{o.name}`"
            default = f"`{o.default}`" if o.default is not None else "---"
            lines.append(f"| {flags} | `{o.type_str}` | {default} | {o.help} |")
        lines.append("")

    return "\n".join(lines)


def render_group_mdx(group: GroupInfo) -> str:
    """Render a full MDX page for a command group."""
    lines: list[str] = []

    lines.append("---")
    lines.append(f"title: syn {group.name}")
    lines.append(f'description: "{group.help}"')
    lines.append("---")
    lines.append("")
    lines.append(f"{group.help}")
    lines.append("")

    for cmd in group.commands:
        lines.append(f"## `syn {group.name} {cmd.name}`")
        lines.append("")
        if cmd.help:
            lines.append(cmd.help)
            lines.append("")

        # Usage line
        usage_parts = [f"syn {group.name} {cmd.name}"]
        for p in cmd.params:
            if p.param_type == "argument":
                usage_parts.append(f"<{p.name}>")
            elif p.opts and p.required:
                usage_parts.append(f"{p.opts[0]} <{p.name}>")
        lines.append("```bash")
        lines.append(" ".join(usage_parts))
        lines.append("```")
        lines.append("")

        if cmd.params:
            lines.append(_render_param_table(cmd.params))

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def render_index_mdx(
    groups: list[GroupInfo],
    top_level: list[CommandInfo],
) -> str:
    """Render the CLI reference index page."""
    lines: list[str] = []

    lines.append("---")
    lines.append("title: CLI Reference")
    lines.append("description: Command-line interface for Syntropic137.")
    lines.append("---")
    lines.append("")
    lines.append(
        "The `syn` CLI provides commands for managing workflows, agents, and the Syntropic137"
    )
    lines.append("platform from your terminal.")
    lines.append("")
    lines.append("## Installation")
    lines.append("")
    lines.append("The CLI is included when you install Syntropic137:")
    lines.append("")
    lines.append("```bash")
    lines.append("uv sync")
    lines.append("syn --help")
    lines.append("```")
    lines.append("")

    if top_level:
        lines.append("## Global Commands")
        lines.append("")
        lines.append("| Command | Description |")
        lines.append("|---------|-------------|")
        for cmd in top_level:
            lines.append(f"| `syn {cmd.name}` | {cmd.help} |")
        lines.append("")

    lines.append("## Command Groups")
    lines.append("")
    lines.append("| Group | Description |")
    lines.append("|-------|-------------|")
    for g in groups:
        lines.append(f"| [`syn {g.name}`](./{g.name}) | {g.help} |")
    lines.append("")

    lines.append("## Global Options")
    lines.append("")
    lines.append("| Option | Description |")
    lines.append("|--------|-------------|")
    lines.append("| `--help` | Show help message |")
    lines.append("")

    return "\n".join(lines)


def render_meta_json(groups: list[GroupInfo]) -> str:
    """Render the meta.json for Fumadocs navigation."""
    pages = ["index"] + [g.name for g in groups]
    meta = {
        "title": "CLI Reference",
        "root": True,
        "pages": pages,
    }
    return json.dumps(meta, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    output_dir = _DOCS_ROOT / "content" / "docs" / "cli"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Install stubs BEFORE importing syn_cli
    _install_stubs()
    _patch_syn_cli_internals()

    # Now import the Typer app — decorators execute, registering commands
    import typer.main

    from syn_cli.main import app as typer_app

    # Convert Typer app -> Click group
    click_app = typer.main.get_command(typer_app)
    assert isinstance(click_app, click.Group), "Expected a Click Group"

    groups, top_level = extract_cli_tree(click_app)

    total_commands = sum(len(g.commands) for g in groups) + len(top_level)
    print(
        f"Extracted {len(groups)} command groups, "
        f"{len(top_level)} top-level commands "
        f"({total_commands} total)"
    )

    # Write index
    index_path = output_dir / "index.mdx"
    index_path.write_text(render_index_mdx(groups, top_level))
    print(f"  wrote {index_path.relative_to(_DOCS_ROOT)}")

    # Write meta.json
    meta_path = output_dir / "meta.json"
    meta_path.write_text(render_meta_json(groups))
    print(f"  wrote {meta_path.relative_to(_DOCS_ROOT)}")

    # Write per-group pages
    for group in groups:
        page_path = output_dir / f"{group.name}.mdx"
        page_path.write_text(render_group_mdx(group))
        print(f"  wrote {page_path.relative_to(_DOCS_ROOT)}")

    print(
        f"\nDone. {len(groups) + 2} files written to "
        f"{output_dir.relative_to(_DOCS_ROOT)}/"
    )


if __name__ == "__main__":
    main()
