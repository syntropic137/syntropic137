"""Workflow update and uninstall commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from syn_cli._output import console, print_error, print_success
from syn_cli.commands._api_helpers import api_delete
from syn_cli.commands._package_models import (
    InstallationRecord,
    InstalledRegistry,
    PluginManifest,
    ResolvedWorkflow,
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


def _is_already_up_to_date(record: InstallationRecord, effective_ref: str) -> bool:
    """Check whether the installed package already matches the latest SHA."""
    if not (record.marketplace_source and record.git_sha):
        return False

    from syn_cli.commands._marketplace_client import (
        get_git_head_sha,
        resolve_plugin_by_name,
    )

    result = resolve_plugin_by_name(record.package_name, registry=record.marketplace_source)
    if result is None:
        return False

    _reg_name, entry, _plugin = result
    current_sha = get_git_head_sha(entry.repo, effective_ref)
    return current_sha is not None and current_sha == record.git_sha


def _resolve_update_source(
    source: str,
    effective_ref: str,
    record: InstallationRecord,
) -> tuple[
    Path, PluginManifest | None, list[ResolvedWorkflow], Path | None, str | None, str | None, str
]:
    """Resolve the updated package source, returning all fields needed for install."""
    if _is_bare_name(source) and record.marketplace_source:
        try:
            mkt_result = _try_marketplace_resolution(source, effective_ref)
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print_error(str(e))
            raise typer.Exit(1) from None

        if mkt_result is not None:
            return mkt_result
        print_error(f"Plugin '{record.package_name}' no longer found in marketplace")
        raise typer.Exit(1)

    package_path, manifest, workflows, tmpdir = _resolve_source(source, effective_ref)
    return (package_path, manifest, workflows, tmpdir, None, None, effective_ref)


def _perform_update(
    name: str,
    source: str,
    effective_ref: str,
    record: InstallationRecord,
    package_path: Path,
    manifest: PluginManifest | None,
    workflows: list[ResolvedWorkflow],
    marketplace_source: str | None,
    git_sha: str | None,
) -> None:
    """Execute the update: preview, remove old, install new, record."""
    from syn_cli.commands._package_resolver import detect_format, record_installation

    if not workflows:
        print_error("No workflows found in updated package")
        raise typer.Exit(1)

    fmt = detect_format(package_path)
    pkg_name = manifest.name if manifest is not None else name
    pkg_version = manifest.version if manifest is not None else "0.0.0"

    _print_package_preview(pkg_name, pkg_version, source, fmt, workflows)

    console.print("\n[bold]Removing old workflows...[/bold]")
    _delete_workflows_via_api(record)
    _remove_installation(name)

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

    source = record.source
    effective_ref = ref or record.source_ref

    if _is_already_up_to_date(record, effective_ref):
        console.print(f"[dim]Package '{name}' is already up to date[/dim]")
        return

    if dry_run:
        console.print(f"[cyan]Update available[/cyan] for [bold]{name}[/bold]")
        console.print(f"  Source: {source}")
        console.print(f"  Ref: {effective_ref}")
        console.print("[dim]Run without --dry-run to apply[/dim]")
        return

    import shutil

    package_path, manifest, workflows, tmpdir, marketplace_source, git_sha, resolved_ref = (
        _resolve_update_source(source, effective_ref, record)
    )

    try:
        _perform_update(
            name,
            source,
            resolved_ref,
            record,
            package_path,
            manifest,
            workflows,
            marketplace_source,
            git_sha,
        )
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
