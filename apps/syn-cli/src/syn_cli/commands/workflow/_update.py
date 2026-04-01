"""Workflow update and uninstall commands."""

from __future__ import annotations

from typing import Annotated

import typer

from syn_cli._output import console, print_error, print_success
from syn_cli.commands._api_helpers import api_delete
from syn_cli.commands._package_models import (
    InstallationRecord,
    InstalledRegistry,
)
from syn_cli.commands._package_resolver import (
    load_installed,
    save_installed,
)
from syn_cli.commands.workflow._crud import app
from syn_cli.commands.workflow._install import (
    _install_workflows_via_api,
    _is_bare_name,
    _print_package_preview,
    _resolve_source,
    _try_marketplace_resolution,
)


def _find_installation(name: str) -> InstallationRecord | None:
    """Find an installation record by package name."""
    registry = load_installed()
    for record in registry.installations:
        if record.package_name == name:
            return record
    return None


def _remove_installation(name: str) -> None:
    """Remove an installation record by package name."""
    registry = load_installed()
    remaining = [r for r in registry.installations if r.package_name != name]
    save_installed(InstalledRegistry(version=registry.version, installations=remaining))


def _delete_workflows_via_api(record: InstallationRecord) -> int:
    """Delete all workflows from an installation record via the API.

    Returns the number of successfully deleted workflows.
    """
    deleted = 0
    for wf_ref in record.workflows:
        console.print(f"  Removing [bold]{wf_ref.name}[/bold]...", end=" ")
        try:
            api_delete(f"/workflows/{wf_ref.id}", expected=(200, 204, 404))
            console.print("[green]done[/green]")
            deleted += 1
        except typer.Exit:
            console.print("[red]failed[/red]")
    return deleted


@app.command("update")
def update_workflow(
    name: Annotated[
        str,
        typer.Argument(help="Package name to update"),
    ],
    ref: Annotated[
        str | None,
        typer.Option("--ref", help="Override git ref"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Check for updates without applying"),
    ] = False,
) -> None:
    """Update an installed workflow package to the latest version."""
    record = _find_installation(name)
    if record is None:
        print_error(f"Package '{name}' is not installed")
        console.print("[dim]See installed packages: syn workflow installed[/dim]")
        raise typer.Exit(1)

    # Determine the source for re-installation
    source = record.source
    effective_ref = ref or record.source_ref

    # Check for updates via SHA comparison
    if record.marketplace_source and record.git_sha:
        from syn_cli.commands._marketplace_client import (
            get_git_head_sha,
            resolve_plugin_by_name,
        )

        result = resolve_plugin_by_name(name, registry=record.marketplace_source)
        if result is not None:
            _reg_name, entry, _plugin = result
            current_sha = get_git_head_sha(entry.repo, effective_ref)
            if current_sha and current_sha == record.git_sha:
                console.print(f"[dim]Package '{name}' is already up to date[/dim]")
                return

    if dry_run:
        console.print(f"[cyan]Update available[/cyan] for [bold]{name}[/bold]")
        console.print(f"  Source: {source}")
        console.print(f"  Ref: {effective_ref}")
        console.print("[dim]Run without --dry-run to apply[/dim]")
        return

    import shutil

    from syn_cli.commands._package_resolver import (
        detect_format,
        record_installation,
    )

    # Resolve new version
    marketplace_source: str | None = None
    git_sha: str | None = None

    if _is_bare_name(source) and record.marketplace_source:
        try:
            mkt_result = _try_marketplace_resolution(source, effective_ref)
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print_error(str(e))
            raise typer.Exit(1) from None

        if mkt_result is not None:
            package_path, manifest, workflows, tmpdir, marketplace_source, git_sha = mkt_result
        else:
            print_error(f"Plugin '{name}' no longer found in marketplace")
            raise typer.Exit(1)
    else:
        package_path, manifest, workflows, tmpdir = _resolve_source(source, effective_ref)

    try:
        if not workflows:
            print_error("No workflows found in updated package")
            raise typer.Exit(1)

        fmt = detect_format(package_path)
        pkg_name = manifest.name if manifest is not None else name
        pkg_version = manifest.version if manifest is not None else "0.0.0"

        _print_package_preview(pkg_name, pkg_version, source, fmt, workflows)

        # Remove old workflows
        console.print("\n[bold]Removing old workflows...[/bold]")
        _delete_workflows_via_api(record)
        _remove_installation(name)

        # Install new version
        console.print("\n[bold]Installing updated workflows...[/bold]")
        installed_refs = _install_workflows_via_api(workflows)

        if not installed_refs:
            print_error("No workflows were installed during update")
            raise typer.Exit(1)

        record_installation(
            package_name=pkg_name,
            package_version=pkg_version,
            source=source,
            source_ref=effective_ref,
            fmt=fmt,
            workflows=installed_refs,
            marketplace_source=marketplace_source or record.marketplace_source,
            git_sha=git_sha or record.git_sha,
        )

        print_success(f"\nUpdated {pkg_name} ({len(installed_refs)} workflow(s))")
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


@app.command("uninstall")
def uninstall_workflow(
    name: Annotated[
        str,
        typer.Argument(help="Package name to uninstall"),
    ],
    keep_workflows: Annotated[
        bool,
        typer.Option(
            "--keep-workflows",
            help="Remove from registry but keep workflows in the platform",
        ),
    ] = False,
) -> None:
    """Uninstall a workflow package."""
    record = _find_installation(name)
    if record is None:
        print_error(f"Package '{name}' is not installed")
        console.print("[dim]See installed packages: syn workflow installed[/dim]")
        raise typer.Exit(1)

    if not keep_workflows:
        console.print(f"Removing workflows from [bold]{name}[/bold]...")
        deleted = _delete_workflows_via_api(record)
        console.print(f"  Removed {deleted} workflow(s)")

    _remove_installation(name)
    print_success(f"Uninstalled [bold]{name}[/bold]")
