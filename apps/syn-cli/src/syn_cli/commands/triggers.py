"""Trigger management commands — register, enable, list, show, history, pause, resume, delete, disable."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_api.types import Err, Ok
from syn_cli._async import run
from syn_cli._output import console, status_style

app = typer.Typer(
    name="triggers",
    help="Manage self-healing trigger rules",
    no_args_is_help=True,
)


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
    import syn_api.v1.triggers as tr

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

    result = run(
        tr.register_trigger(
            name=name,
            event=event,
            repository=repository,
            workflow_id=workflow,
            conditions=parsed_conditions or None,
            installation_id=installation_id,
            config={
                "max_attempts": max_attempts,
                "budget_per_trigger_usd": budget,
                "daily_limit": daily_limit,
            },
            created_by=created_by,
        )
    )

    match result:
        case Ok(trigger_id):
            console.print(f"[green]Trigger registered:[/green] {trigger_id}")
            console.print(f"  Name: {name}")
            console.print(f"  Event: {event}")
            console.print(f"  Repository: {repository}")
            console.print(f"  Workflow: {workflow}")
        case Err(error, message=msg):
            console.print(f"[red]Failed to register trigger: {msg or error}[/red]")
            raise typer.Exit(1)


@app.command("enable")
def enable_preset(
    preset: Annotated[str, typer.Argument(help="Preset name: self-healing | review-fix")],
    repository: Annotated[str, typer.Option("--repository", "-r", help="Repository (owner/repo)")],
    installation_id: Annotated[str, typer.Option(help="GitHub App installation ID")] = "",
    created_by: Annotated[str, typer.Option(help="Creator identifier")] = "cli",
) -> None:
    """Enable a built-in preset for a repository."""
    import syn_api.v1.triggers as tr

    result = run(
        tr.enable_preset(
            preset_name=preset,
            repository=repository,
            installation_id=installation_id,
            created_by=created_by,
        )
    )

    match result:
        case Ok(trigger_id):
            console.print(f"[green]Preset '{preset}' enabled:[/green] {trigger_id}")
            console.print(f"  Repository: {repository}")
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("list")
def list_triggers(
    repository: Annotated[
        str | None, typer.Option("--repository", "-r", help="Filter by repository")
    ] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
) -> None:
    """List all registered triggers."""
    import syn_api.v1.triggers as tr

    result = run(tr.list_triggers(repository=repository, status=status))

    match result:
        case Ok(triggers):
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
                style = status_style(t.status)
                table.add_row(
                    t.trigger_id,
                    t.name,
                    t.event,
                    t.repository,
                    f"[{style}]{t.status}[/{style}]",
                    str(t.fire_count),
                )
            console.print(table)
        case Err(error, message=msg):
            console.print(f"[red]Failed: {msg or error}[/red]")
            raise typer.Exit(1)


@app.command("show")
def show_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Show trigger details."""
    import syn_api.v1.triggers as tr

    result = run(tr.get_trigger(trigger_id))

    match result:
        case Ok(detail):
            console.print(f"[bold]Trigger: {detail.name}[/bold]")
            console.print(f"  ID: {detail.trigger_id}")
            console.print(f"  Status: {detail.status}")
            console.print(f"  Event: {detail.event}")
            console.print(f"  Repository: {detail.repository}")
            console.print(f"  Workflow: {detail.workflow_id}")
            console.print(f"  Fire Count: {detail.fire_count}")
            if detail.conditions:
                console.print(f"  Conditions: {len(detail.conditions)}")
                for c in detail.conditions:
                    console.print(
                        f"    - {c.get('field', '')} {c.get('operator', '')} {c.get('value', '')}"
                    )
            if detail.config:
                console.print("  Config:")
                for k, v in detail.config.items():
                    console.print(f"    {k}: {v}")
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("history")
def trigger_history(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
    limit: Annotated[int, typer.Option(help="Max entries to show")] = 50,
) -> None:
    """Show trigger execution history."""
    import syn_api.v1.triggers as tr

    result = tr.get_trigger_history(trigger_id=trigger_id, limit=limit)

    match result:
        case Ok(entries):
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
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("pause")
def pause_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
    reason: Annotated[str | None, typer.Option(help="Reason for pausing")] = None,
) -> None:
    """Pause a trigger rule."""
    import syn_api.v1.triggers as tr

    result = run(tr.pause_trigger(trigger_id=trigger_id, reason=reason, paused_by="cli"))

    match result:
        case Ok():
            console.print(f"[yellow]Trigger paused:[/yellow] {trigger_id}")
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("resume")
def resume_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Resume a paused trigger rule."""
    import syn_api.v1.triggers as tr

    result = run(tr.resume_trigger(trigger_id=trigger_id, resumed_by="cli"))

    match result:
        case Ok():
            console.print(f"[green]Trigger resumed:[/green] {trigger_id}")
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("delete")
def delete_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Delete a trigger rule."""
    import syn_api.v1.triggers as tr

    result = run(tr.delete_trigger(trigger_id=trigger_id, deleted_by="cli"))

    match result:
        case Ok():
            console.print(f"[red]Trigger deleted:[/red] {trigger_id}")
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)


@app.command("disable")
def disable_all(
    repository: Annotated[
        str, typer.Option("--repository", "-r", help="Disable all triggers for repo")
    ],
) -> None:
    """Disable all triggers for a repository."""
    import syn_api.v1.triggers as tr

    result = run(tr.disable_triggers(repository=repository, paused_by="cli"))

    match result:
        case Ok(count):
            if count == 0:
                console.print(f"[dim]No active triggers for {repository}.[/dim]")
            else:
                console.print(f"[yellow]Paused {count} trigger(s) for {repository}[/yellow]")
        case Err(error, message=msg):
            console.print(f"[red]{msg or error}[/red]")
            raise typer.Exit(1)
