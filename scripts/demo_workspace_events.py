#!/usr/bin/env python3
"""Demo: Workspace Events E2E Flow.

Shows how workspace events are emitted and collected within a session.
Uses InMemoryCollectorEmitter for immediate inspection without running collector.

Usage:
    uv run python scripts/demo_workspace_events.py
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aef_adapters.agents.agentic_types import WorkspaceConfig
from aef_adapters.workspaces import (
    InMemoryCollectorEmitter,
    IsolatedWorkspaceConfig,
    WorkspaceRouter,
    configure_workspace_emitter,
)

console = Console()


async def main() -> None:
    """Run the E2E demo."""
    console.print()
    console.print(Panel.fit("[bold cyan]Workspace Events E2E Demo[/bold cyan]"))
    console.print()

    # === Setup: Configure in-memory event collection ===
    emitter = InMemoryCollectorEmitter()
    configure_workspace_emitter(emitter=emitter, enabled=True)

    router = WorkspaceRouter()

    # === Create a session with workspaces ===
    session_id = "demo-session-001"
    console.print(f"[bold]Session:[/bold] {session_id}")
    console.print(f"[bold]Backend:[/bold] {router.get_best_backend().value}")
    console.print()

    # Create workspace config
    base_config = WorkspaceConfig(
        session_id=session_id,
        workflow_id="demo-workflow",
    )
    config = IsolatedWorkspaceConfig(base_config=base_config)

    console.print("[dim]Creating isolated workspace...[/dim]")

    async with router.create(config) as workspace:
        console.print(
            f"[green]✓[/green] Workspace ready: [dim]{workspace.container_id[:12]}...[/dim]"
        )

        # Execute some commands
        commands = [
            ["echo", "Hello from isolated workspace!"],
            ["python", "-c", "print('Python works!')"],
            ["ls", "-la", "/workspace"],
        ]

        for cmd in commands:
            console.print(f"[dim]  Running: {' '.join(cmd[:3])}...[/dim]")
            exit_code, _stdout, _stderr = await router.execute_command(workspace, cmd)
            if exit_code == 0:
                console.print(f"  [green]✓[/green] Exit code: {exit_code}")
            else:
                console.print(f"  [red]✗[/red] Exit code: {exit_code}")

    console.print("[green]✓[/green] Workspace destroyed")
    console.print()

    # === Show collected events ===
    console.print(Panel.fit("[bold cyan]Events Collected in Session[/bold cyan]"))
    console.print()

    # Summary
    summary = emitter.summary()
    console.print(f"[bold]Total Events:[/bold] {summary['total_events']}")
    console.print()

    # Events by type
    type_table = Table(title="Events by Type")
    type_table.add_column("Event Type", style="cyan")
    type_table.add_column("Count", justify="right")

    for event_type, count in sorted(summary["by_type"].items()):
        type_table.add_row(event_type, str(count))

    console.print(type_table)
    console.print()

    # Timeline of events
    timeline_table = Table(title="Event Timeline")
    timeline_table.add_column("#", justify="right", style="dim")
    timeline_table.add_column("Event Type", style="cyan")
    timeline_table.add_column("Workspace", style="dim")
    timeline_table.add_column("Details")

    for i, event in enumerate(emitter.events, 1):
        event_type = event["event_type"]
        data = event["data"]
        workspace_id = data.get("workspace_id", "")[:8] + "..."

        # Extract relevant detail
        if event_type == "WorkspaceCreating":
            detail = f"backend={data.get('isolation_backend', 'unknown')}"
        elif event_type == "WorkspaceCreated":
            detail = f"create_time={data.get('create_duration_ms', 0):.0f}ms"
        elif event_type == "WorkspaceCommandExecuted":
            cmd = " ".join(data.get("command", [])[:2])
            detail = f"cmd='{cmd}' exit={data.get('exit_code', '?')}"
        elif event_type == "WorkspaceDestroyed":
            detail = f"lifetime={data.get('total_lifetime_ms', 0):.0f}ms, cmds={data.get('commands_executed', 0)}"
        else:
            detail = ""

        timeline_table.add_row(str(i), event_type, workspace_id, detail)

    console.print(timeline_table)
    console.print()

    # Show session linkage
    console.print(Panel.fit("[bold]Session → Workspace Linkage[/bold]"))
    console.print()
    console.print("All workspace events are linked to the session via [cyan]session_id[/cyan]:")
    console.print()

    session_events = emitter.get_by_session(session_id)
    console.print(f"  Session [bold]{session_id}[/bold]")
    console.print(f"    └── {len(session_events)} workspace events")

    # Group by workspace
    workspaces = {}
    for event in session_events:
        ws_id = event["data"].get("workspace_id", "unknown")
        if ws_id not in workspaces:
            workspaces[ws_id] = []
        workspaces[ws_id].append(event["event_type"])

    for ws_id, events in workspaces.items():
        console.print(f"        └── Workspace [dim]{ws_id[:12]}[/dim]")
        for event_type in events:
            console.print(f"            └── {event_type}")

    console.print()


if __name__ == "__main__":
    asyncio.run(main())
