"""Workflow export command — export workflows as packages or Claude Code plugins."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Annotated, Any

import typer
from rich.panel import Panel
from rich.tree import Tree

from syn_cli._output import console, print_error, print_success
from syn_cli.commands._api_helpers import api_get
from syn_cli.commands.workflow._crud import app


@app.command("export")
def export_workflow(
    workflow_id: Annotated[str, typer.Argument(help="Workflow ID to export")],
    fmt: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Export format: 'package' (default) or 'plugin' (Claude Code plugin)",
        ),
    ] = "package",
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output directory (created if absent)",
        ),
    ] = Path(),
) -> None:
    """Export a workflow as a distributable package or Claude Code plugin."""
    if fmt not in ("package", "plugin"):
        print_error(f"Invalid format '{fmt}'. Must be 'package' or 'plugin'.")
        raise typer.Exit(1)

    data: dict[str, Any] = api_get(
        f"/workflows/{workflow_id}/export",
        params={"format": fmt},
    )

    files: dict[str, str] = data.get("files", {})
    if not files:
        print_error("Export returned no files")
        raise typer.Exit(1)

    out_dir = output.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        print_error(f"Output directory is not empty: {out_dir}")
        raise typer.Exit(1)

    # Write files to disk — validate each path stays within out_dir
    for rel_path, content in sorted(files.items()):
        # Reject absolute paths and directory traversal segments
        posix_path = PurePosixPath(rel_path)
        if posix_path.is_absolute() or ".." in posix_path.parts:
            print_error(f"Unsafe file path in export manifest: {rel_path}")
            raise typer.Exit(1)

        file_path = (out_dir / rel_path).resolve()
        if not file_path.is_relative_to(out_dir):
            print_error(f"Path escapes output directory: {rel_path}")
            raise typer.Exit(1)

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    # Print summary
    workflow_name = data.get("workflow_name", workflow_id)
    _print_export_summary(workflow_name, fmt, out_dir, files)


def _print_export_summary(
    name: str,
    fmt: str,
    out_dir: Path,
    files: dict[str, str],
) -> None:
    """Print a summary panel with file tree."""
    console.print(
        Panel(
            f"[bold]{name}[/bold]\nFormat: {fmt}\nOutput: {out_dir}\nFiles: {len(files)}",
            title="[green]Export Complete[/green]",
            border_style="green",
        )
    )

    tree = Tree(f"[cyan]{out_dir.name}/[/cyan]")
    _build_tree(tree, files)
    console.print(tree)

    print_success(f"Exported to {out_dir}")
    console.print(f"\nTo install: [cyan]syn workflow install {out_dir}[/cyan]")
    if fmt == "plugin":
        console.print(f"Plugin command: [cyan]/syn-{name.lower().replace(' ', '-')}[/cyan]")


def _build_tree(tree: Tree, files: dict[str, str]) -> None:
    """Build a Rich tree from a flat dict of file paths."""
    dirs_added: dict[str, Tree] = {}

    for rel_path in sorted(files):
        parts = Path(rel_path).parts
        parent = tree
        for i, part in enumerate(parts[:-1]):
            dir_key = "/".join(parts[: i + 1])
            if dir_key not in dirs_added:
                dirs_added[dir_key] = parent.add(f"[cyan]{part}/[/cyan]")
            parent = dirs_added[dir_key]
        parent.add(f"[dim]{parts[-1]}[/dim]")
