"""Trigger management commands — register, enable, list, show, history, pause, resume, delete, disable."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from syn_cli._output import console, print_error, status_style
from syn_cli.client import get_client

app = typer.Typer(
    name="triggers",
    help="Manage self-healing trigger rules",
    no_args_is_help=True,
)


def _handle_connect_error() -> None:
    from syn_cli.client import get_api_url

    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


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
    parsed_conditions = []
    for cond_str in condition or []:
        parts = cond_str.split(maxsplit=2)
        if len(parts) < 2:
            print_error(f"Invalid condition format: '{cond_str}'")
            console.print("Expected: 'field operator [value]'")
            raise typer.Exit(1)
        cond = {"field": parts[0], "operator": parts[1]}
        if len(parts) > 2:
            cond["value"] = parts[2]
        parsed_conditions.append(cond)

    try:
        with get_client() as client:
            resp = client.post(
                "/triggers",
                json={
                    "name": name,
                    "event": event,
                    "repository": repository,
                    "workflow_id": workflow,
                    "conditions": parsed_conditions or None,
                    "installation_id": installation_id,
                    "config": {
                        "max_attempts": max_attempts,
                        "budget_per_trigger_usd": budget,
                        "daily_limit": daily_limit,
                    },
                    "created_by": created_by,
                },
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    console.print(f"[green]Trigger registered:[/green] {data.get('trigger_id', '')}")
    console.print(f"  Name: {name}")
    console.print(f"  Event: {event}")
    console.print(f"  Repository: {repository}")
    console.print(f"  Workflow: {workflow}")


@app.command("enable")
def enable_preset(
    preset: Annotated[str, typer.Argument(help="Preset name: self-healing | review-fix")],
    repository: Annotated[str, typer.Option("--repository", "-r", help="Repository (owner/repo)")],
    installation_id: Annotated[str, typer.Option(help="GitHub App installation ID")] = "",
    created_by: Annotated[str, typer.Option(help="Creator identifier")] = "cli",
) -> None:
    """Enable a built-in preset for a repository."""
    try:
        with get_client() as client:
            resp = client.post(
                f"/triggers/presets/{preset}",
                json={
                    "repository": repository,
                    "installation_id": installation_id,
                    "created_by": created_by,
                },
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    console.print(f"[green]Preset '{preset}' enabled:[/green] {data.get('trigger_id', '')}")
    console.print(f"  Repository: {repository}")


@app.command("list")
def list_triggers(
    repository: Annotated[
        str | None, typer.Option("--repository", "-r", help="Filter by repository")
    ] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
) -> None:
    """List all registered triggers."""
    try:
        with get_client() as client:
            params = {}
            if repository:
                params["repository"] = repository
            if status:
                params["status"] = status
            resp = client.get("/triggers", params=params)
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    triggers = data.get("triggers", [])

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
        style = status_style(t.get("status", ""))
        table.add_row(
            t.get("trigger_id", ""),
            t.get("name", ""),
            t.get("event", ""),
            t.get("repository", ""),
            f"[{style}]{t.get('status', '')}[/{style}]",
            str(t.get("fire_count", 0)),
        )
    console.print(table)


@app.command("show")
def show_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Show trigger details."""
    try:
        with get_client() as client:
            resp = client.get(f"/triggers/{trigger_id}")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    detail = resp.json()
    console.print(f"[bold]Trigger: {detail.get('name', '')}[/bold]")
    console.print(f"  ID: {detail.get('trigger_id', '')}")
    console.print(f"  Status: {detail.get('status', '')}")
    console.print(f"  Event: {detail.get('event', '')}")
    console.print(f"  Repository: {detail.get('repository', '')}")
    console.print(f"  Workflow: {detail.get('workflow_id', '')}")
    console.print(f"  Fire Count: {detail.get('fire_count', 0)}")
    conditions = detail.get("conditions") or []
    if conditions:
        console.print(f"  Conditions: {len(conditions)}")
        for c in conditions:
            console.print(
                f"    - {c.get('field', '')} {c.get('operator', '')} {c.get('value', '')}"
            )
    config = detail.get("config") or {}
    if config:
        console.print("  Config:")
        for k, v in config.items():
            console.print(f"    {k}: {v}")


@app.command("history")
def trigger_history(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
    limit: Annotated[int, typer.Option(help="Max entries to show")] = 50,
) -> None:
    """Show trigger execution history."""
    try:
        with get_client() as client:
            resp = client.get(f"/triggers/{trigger_id}/history", params={"limit": limit})
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    entries = data.get("entries", [])

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
        table.add_row(
            entry.get("fired_at") or "-",
            entry.get("execution_id", ""),
            entry.get("event_type", ""),
            str(entry.get("pr_number") or "-"),
            entry.get("status", ""),
        )
    console.print(table)


@app.command("pause")
def pause_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
    reason: Annotated[str | None, typer.Option(help="Reason for pausing")] = None,
) -> None:
    """Pause a trigger rule."""
    try:
        with get_client() as client:
            resp = client.patch(
                f"/triggers/{trigger_id}",
                json={"action": "pause", "reason": reason, "paused_by": "cli"},
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    console.print(f"[yellow]Trigger paused:[/yellow] {trigger_id}")


@app.command("resume")
def resume_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Resume a paused trigger rule."""
    try:
        with get_client() as client:
            resp = client.patch(
                f"/triggers/{trigger_id}",
                json={"action": "resume", "resumed_by": "cli"},
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    console.print(f"[green]Trigger resumed:[/green] {trigger_id}")


@app.command("delete")
def delete_trigger(
    trigger_id: Annotated[str, typer.Argument(help="Trigger ID")],
) -> None:
    """Delete a trigger rule."""
    try:
        with get_client() as client:
            resp = client.delete(f"/triggers/{trigger_id}")
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    console.print(f"[red]Trigger deleted:[/red] {trigger_id}")


@app.command("disable")
def disable_all(
    repository: Annotated[
        str, typer.Option("--repository", "-r", help="Disable all triggers for repo")
    ],
) -> None:
    """Disable all triggers for a repository."""
    try:
        with get_client() as client:
            resp = client.post(
                "/triggers/disable",
                json={"repository": repository, "paused_by": "cli"},
            )
    except Exception:
        _handle_connect_error()
        return

    if resp.status_code != 200:
        print_error(resp.json().get("detail", f"HTTP {resp.status_code}"))
        raise typer.Exit(1)

    data = resp.json()
    count = data.get("count", 0)
    if count == 0:
        console.print(f"[dim]No active triggers for {repository}.[/dim]")
    else:
        console.print(f"[yellow]Paused {count} trigger(s) for {repository}[/yellow]")
