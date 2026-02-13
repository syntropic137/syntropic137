"""Trigger management commands."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from aef_shared.logging import get_logger

logger = get_logger(__name__)
console = Console()

app = typer.Typer(
    name="triggers",
    help="Manage self-healing trigger rules",
    no_args_is_help=True,
)


def _run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


@app.command("register")
def register_trigger(
    name: Annotated[str, typer.Option("--name", "-n", help="Human-readable name")],
    event: Annotated[
        str, typer.Option("--event", "-e", help="GitHub event (e.g., check_run.completed)")
    ],
    repository: Annotated[str, typer.Option("--repository", "-r", help="Repository (owner/repo)")],
    workflow: Annotated[str, typer.Option("--workflow", "-w", help="Workflow ID to execute")],
    condition: Annotated[
        list[str] | None,
        typer.Option("--condition", "-c", help="Conditions: 'field operator value'"),
    ] = None,
    max_attempts: Annotated[int, typer.Option(help="Max retry attempts per PR")] = 3,
    budget: Annotated[float, typer.Option(help="Budget per trigger in USD")] = 5.0,
    daily_limit: Annotated[int, typer.Option(help="Max triggers per day")] = 20,
    installation_id: Annotated[str, typer.Option(help="GitHub App installation ID")] = "",
    created_by: Annotated[str, typer.Option(help="Creator identifier")] = "cli",
) -> None:
    """Register a new trigger rule."""
    from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
        RegisterTriggerCommand,
    )
    from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
        RegisterTriggerHandler,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    # Parse conditions
    parsed_conditions = []
    for cond_str in condition or []:
        parts = cond_str.split(maxsplit=2)
        if len(parts) < 2:
            console.print(f"[red]Invalid condition format: '{cond_str}'[/red]")
            console.print("Expected: 'field operator [value]'")
            raise typer.Exit(1)
        cond = {"field": parts[0], "operator": parts[1]}
        if len(parts) > 2:
            cond["value"] = parts[2]
        parsed_conditions.append(cond)

    cmd = RegisterTriggerCommand(
        name=name,
        event=event,
        conditions=tuple(parsed_conditions),
        repository=repository,
        installation_id=installation_id,
        workflow_id=workflow,
        config=(
            ("max_attempts", max_attempts),
            ("budget_per_trigger_usd", budget),
            ("daily_limit", daily_limit),
        ),
        created_by=created_by,
    )

    store = get_trigger_store()
    handler = RegisterTriggerHandler(store=store)
    aggregate = _run_async(handler.handle(cmd))

    console.print(f"[green]Trigger registered:[/green] {aggregate.trigger_id}")
    console.print(f"  Name: {aggregate.name}")
    console.print(f"  Event: {aggregate.event}")
    console.print(f"  Repository: {aggregate.repository}")
    console.print(f"  Workflow: {aggregate.workflow_id}")
    console.print(f"  Status: {aggregate.status.value}")


@app.command("enable")
def enable_preset(
    preset: Annotated[str, typer.Argument(help="Preset name: self-healing | review-fix")],
    repository: Annotated[str, typer.Option("--repository", "-r", help="Repository (owner/repo)")],
    installation_id: Annotated[str, typer.Option(help="GitHub App installation ID")] = "",
    created_by: Annotated[str, typer.Option(help="Creator identifier")] = "cli",
) -> None:
    """Enable a built-in preset for a repository."""
    from aef_domain.contexts.github._shared.trigger_presets import (
        create_preset_command,
    )
    from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
        RegisterTriggerHandler,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    try:
        cmd = create_preset_command(
            preset_name=preset,
            repository=repository,
            installation_id=installation_id,
            created_by=created_by,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    store = get_trigger_store()
    handler = RegisterTriggerHandler(store=store)
    aggregate = _run_async(handler.handle(cmd))

    console.print(f"[green]Preset '{preset}' enabled:[/green] {aggregate.trigger_id}")
    console.print(f"  Repository: {repository}")
    console.print(f"  Workflow: {aggregate.workflow_id}")


@app.command("list")
def list_triggers(
    repository: Annotated[
        str | None, typer.Option("--repository", "-r", help="Filter by repository")
    ] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
) -> None:
    """List all registered triggers."""
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    store = get_trigger_store()
    triggers = _run_async(store.list_all(repository=repository, status=status))

    if not triggers:
        console.print("[dim]No triggers found.[/dim]")
        return

    table = Table(title="Trigger Rules")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Event")
    table.add_column("Repository")
    table.add_column("Status")
    table.add_column("Fires", justify="right")

    for t in triggers:
        status_style = {
            "active": "green",
            "paused": "yellow",
            "deleted": "red",
        }.get(t.status.value, "")
        table.add_row(
            t.trigger_id,
            t.name,
            t.event,
            t.repository,
            f"[{status_style}]{t.status.value}[/{status_style}]",
            str(t.fire_count),
        )

    console.print(table)


@app.command("show")
def show_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Show trigger details."""
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    store = get_trigger_store()
    trigger = _run_async(store.get(trigger_id))

    if trigger is None:
        console.print(f"[red]Trigger not found: {trigger_id}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Trigger: {trigger.name}[/bold]")
    console.print(f"  ID: {trigger.trigger_id}")
    console.print(f"  Status: {trigger.status.value}")
    console.print(f"  Event: {trigger.event}")
    console.print(f"  Repository: {trigger.repository}")
    console.print(f"  Workflow: {trigger.workflow_id}")
    console.print(f"  Fire Count: {trigger.fire_count}")
    console.print(f"  Conditions: {len(trigger.conditions)}")
    for c in trigger.conditions:
        console.print(f"    - {c.field} {c.operator} {c.value}")
    console.print("  Config:")
    console.print(f"    Max Attempts: {trigger.config.max_attempts}")
    console.print(f"    Daily Limit: {trigger.config.daily_limit}")
    console.print(f"    Cooldown: {trigger.config.cooldown_seconds}s")
    console.print(f"    Budget: ${trigger.config.budget_per_trigger_usd:.2f}")


@app.command("history")
def trigger_history(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
    limit: Annotated[int, typer.Option(help="Max entries to show")] = 50,
) -> None:
    """Show trigger execution history."""
    from aef_domain.contexts.github.domain.queries.get_trigger_history import (
        GetTriggerHistoryQuery,
    )
    from aef_domain.contexts.github.slices.trigger_history.handler import (
        GetTriggerHistoryHandler,
    )

    query = GetTriggerHistoryQuery(trigger_id=trigger_id, limit=limit)
    handler = GetTriggerHistoryHandler()
    entries = handler.handle(query)

    if not entries:
        console.print(f"[dim]No history for trigger {trigger_id}.[/dim]")
        return

    table = Table(title=f"History for {trigger_id}")
    table.add_column("Fired At")
    table.add_column("Execution ID", style="cyan")
    table.add_column("Event")
    table.add_column("PR #", justify="right")
    table.add_column("Status")

    for entry in entries:
        fired_at = entry.fired_at.isoformat() if entry.fired_at else "-"
        table.add_row(
            fired_at,
            entry.execution_id,
            entry.github_event_type,
            str(entry.pr_number or "-"),
            entry.status,
        )

    console.print(table)


@app.command("pause")
def pause_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
    reason: Annotated[str | None, typer.Option(help="Reason for pausing")] = None,
) -> None:
    """Pause a trigger rule."""
    from aef_domain.contexts.github.domain.commands.PauseTriggerCommand import (
        PauseTriggerCommand,
    )
    from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    store = get_trigger_store()
    handler = ManageTriggerHandler(store=store)
    event = _run_async(
        handler.pause(PauseTriggerCommand(trigger_id=trigger_id, paused_by="cli", reason=reason))
    )

    if event:
        console.print(f"[yellow]Trigger paused:[/yellow] {trigger_id}")
    else:
        console.print(f"[red]Could not pause trigger {trigger_id} (not found or not active)[/red]")


@app.command("resume")
def resume_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Resume a paused trigger rule."""
    from aef_domain.contexts.github.domain.commands.ResumeTriggerCommand import (
        ResumeTriggerCommand,
    )
    from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    store = get_trigger_store()
    handler = ManageTriggerHandler(store=store)
    event = _run_async(
        handler.resume(ResumeTriggerCommand(trigger_id=trigger_id, resumed_by="cli"))
    )

    if event:
        console.print(f"[green]Trigger resumed:[/green] {trigger_id}")
    else:
        console.print(f"[red]Could not resume trigger {trigger_id} (not found or not paused)[/red]")


@app.command("delete")
def delete_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Delete a trigger rule."""
    from aef_domain.contexts.github.domain.commands.DeleteTriggerCommand import (
        DeleteTriggerCommand,
    )
    from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    store = get_trigger_store()
    handler = ManageTriggerHandler(store=store)
    event = _run_async(
        handler.delete(DeleteTriggerCommand(trigger_id=trigger_id, deleted_by="cli"))
    )

    if event:
        console.print(f"[red]Trigger deleted:[/red] {trigger_id}")
    else:
        console.print(
            f"[red]Could not delete trigger {trigger_id} (not found or already deleted)[/red]"
        )


@app.command("disable")
def disable_all(
    repository: Annotated[
        str, typer.Option("--repository", "-r", help="Disable all triggers for repo")
    ],
) -> None:
    """Disable all triggers for a repository."""
    from aef_domain.contexts.github.domain.commands.PauseTriggerCommand import (
        PauseTriggerCommand,
    )
    from aef_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
        ManageTriggerHandler,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_store,
    )

    store = get_trigger_store()
    triggers = _run_async(store.list_all(repository=repository, status="active"))

    if not triggers:
        console.print(f"[dim]No active triggers for {repository}.[/dim]")
        return

    handler = ManageTriggerHandler(store=store)
    paused = 0
    for t in triggers:
        event = _run_async(
            handler.pause(
                PauseTriggerCommand(
                    trigger_id=t.trigger_id,
                    paused_by="cli",
                    reason=f"Bulk disable for {repository}",
                )
            )
        )
        if event:
            paused += 1

    console.print(f"[yellow]Paused {paused} trigger(s) for {repository}[/yellow]")
