"""Workflow package commands — install, installed, init, validate (directory)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from syn_cli._output import console, format_timestamp, print_error, print_success
from syn_cli.commands._api_helpers import api_post
from syn_cli.commands._package_models import (
    InstalledWorkflowRef,
    ResolvedWorkflow,
)
from syn_cli.commands._package_resolver import (
    detect_format,
    load_installed,
    parse_source,
    record_installation,
    resolve_from_git,
    resolve_package,
    scaffold_multi_package,
    scaffold_single_package,
)
from syn_cli.commands.workflow._crud import app

# ---------------------------------------------------------------------------
# syn workflow install
# ---------------------------------------------------------------------------


@app.command("install")
def install_workflow(
    source: Annotated[str, typer.Argument(help="Local path, GitHub URL, or org/repo shorthand")],
    ref: Annotated[str, typer.Option("--ref", help="Git branch/tag to clone")] = "main",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Validate without installing")
    ] = False,
) -> None:
    """Install workflow(s) from a package directory or git repository."""
    resolved_source, is_remote = parse_source(source)
    tmpdir: Path | None = None

    try:
        if is_remote:
            console.print(f"Cloning [cyan]{resolved_source}[/cyan]@{ref}...")
            tmpdir, manifest, workflows = resolve_from_git(resolved_source, ref=ref)
            package_path = tmpdir
        else:
            package_path = Path(resolved_source).resolve()
            manifest, workflows = resolve_package(package_path)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print_error(str(e))
        raise typer.Exit(1) from None

    if not workflows:
        print_error("No workflows found in package")
        raise typer.Exit(1)

    # Determine package name / version
    fmt = detect_format(package_path)
    pkg_name = manifest.name if manifest is not None else package_path.name
    pkg_version = manifest.version if manifest is not None else "0.0.0"

    # Preview panel
    total_phases = sum(len(w.phases) for w in workflows)
    console.print(
        Panel(
            f"[bold]{pkg_name}[/bold] v{pkg_version}\n"
            f"Source: {source}\n"
            f"Format: {fmt.value}\n"
            f"Workflows: {len(workflows)}\n"
            f"Total phases: {total_phases}",
            title="[cyan]Package Preview[/cyan]",
            border_style="cyan",
        )
    )

    if dry_run:
        print_success("Dry run — package is valid, no workflows installed")
        _print_workflow_summary(workflows)
        return

    # Install each workflow via the API
    installed_refs: list[InstalledWorkflowRef] = []
    for i, wf in enumerate(workflows, 1):
        console.print(f"  [{i}/{len(workflows)}] Creating [bold]{wf.name}[/bold]...", end=" ")
        try:
            data = api_post(
                "/workflows",
                json=wf.model_dump(exclude={"source_path"}),
                expected=(201,),
            )
            wf_id = data.get("id", "unknown")
            console.print(f"[green]done[/green] (id: {wf_id})")
            installed_refs.append(InstalledWorkflowRef(id=wf_id, name=wf.name))
        except SystemExit:
            console.print("[red]failed[/red]")

    if not installed_refs:
        print_error("No workflows were installed")
        raise typer.Exit(1)

    # Record installation
    record_installation(
        package_name=pkg_name,
        package_version=pkg_version,
        source=source,
        source_ref=ref,
        fmt=fmt,
        workflows=installed_refs,
    )

    print_success(f"\nInstalled {len(installed_refs)} workflow(s) from {source}")

    # Cleanup
    if tmpdir is not None:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# syn workflow installed
# ---------------------------------------------------------------------------


@app.command("installed")
def list_installed() -> None:
    """List installed workflow packages."""
    registry = load_installed()

    if not registry.installations:
        console.print("[dim]No packages installed yet.[/dim]")
        console.print("Install one with: [cyan]syn workflow install <source>[/cyan]")
        return

    table = Table(title="Installed Packages")
    table.add_column("Package", style="cyan")
    table.add_column("Version")
    table.add_column("Source", style="dim")
    table.add_column("Workflows", justify="right")
    table.add_column("Installed", style="dim")

    for record in registry.installations:
        table.add_row(
            record.package_name,
            record.package_version,
            record.source,
            str(len(record.workflows)),
            format_timestamp(record.installed_at),
        )

    console.print(table)


# ---------------------------------------------------------------------------
# syn workflow init
# ---------------------------------------------------------------------------


@app.command("init")
def init_package(
    directory: Annotated[Path, typer.Argument(help="Directory to scaffold")] = Path(),
    name: Annotated[str | None, typer.Option("--name", "-n", help="Workflow name")] = None,
    workflow_type: Annotated[str, typer.Option("--type", "-t", help="Workflow type")] = "research",
    phases: Annotated[int, typer.Option("--phases", help="Number of phases")] = 3,
    multi: Annotated[bool, typer.Option("--multi", help="Scaffold multi-workflow plugin")] = False,
) -> None:
    """Scaffold a new workflow package from a template."""
    resolved_dir = directory.resolve()
    wf_name = name or resolved_dir.name.replace("-", " ").replace("_", " ").title()

    if resolved_dir.exists() and any(resolved_dir.iterdir()):
        print_error(f"Directory is not empty: {resolved_dir}")
        raise typer.Exit(1)

    if multi:
        scaffold_multi_package(
            resolved_dir,
            name=wf_name,
            workflow_type=workflow_type,
            num_phases=phases,
        )
        fmt_label = "multi-workflow plugin"
    else:
        scaffold_single_package(
            resolved_dir,
            name=wf_name,
            workflow_type=workflow_type,
            num_phases=phases,
        )
        fmt_label = "single workflow package"

    print_success(f"Scaffolded {fmt_label} at {resolved_dir}")
    console.print("\nNext steps:")
    console.print(f"  1. Edit the prompts in [cyan]{resolved_dir}/phases/[/cyan]")
    console.print(f"  2. Validate: [cyan]syn workflow validate {resolved_dir}[/cyan]")
    console.print(f"  3. Install: [cyan]syn workflow install {resolved_dir}[/cyan]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_workflow_summary(workflows: list[ResolvedWorkflow]) -> None:
    """Print a summary table of resolved workflows."""
    table = Table(title="Resolved Workflows")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Type")
    table.add_column("Phases", justify="right")

    for wf in workflows:
        table.add_row(
            wf.name,
            wf.id,
            wf.workflow_type,
            str(len(wf.phases)),
        )

    console.print(table)
