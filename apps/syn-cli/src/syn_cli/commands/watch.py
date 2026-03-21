"""Watch commands — live SSE stream of execution or global activity."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from syn_cli._output import console, format_cost, format_timestamp, print_error, status_style
from syn_cli.client import get_api_url, get_streaming_client

app = typer.Typer(
    name="watch",
    help="Watch live execution or activity streams",
    no_args_is_help=True,
)


def _parse_sse_line(line: str) -> dict[str, object] | None:
    """Parse a single SSE data line into a dict, or None if not a data line."""
    if line.startswith("data: "):
        raw = line[6:].strip()
        if raw:
            try:
                parsed: dict[str, object] = json.loads(raw)
                return parsed
            except json.JSONDecodeError:
                pass
    return None


def _render_event(frame: dict[str, object]) -> None:
    """Render an SSE event frame to the console."""
    event_type = str(frame.get("event_type", ""))
    data = frame.get("data")
    if not isinstance(data, dict):
        data = {}

    ts = format_timestamp(str(frame.get("timestamp", "")))

    if event_type == "ExecutionStarted":
        exec_id = str(data.get("execution_id", ""))[:12]
        console.print(f"[dim]{ts}[/dim]  [green]▶ started[/green]  {exec_id}")
    elif event_type in ("ExecutionCompleted", "WorkflowCompleted"):
        exec_id = str(data.get("execution_id", ""))[:12]
        cost = format_cost(data.get("total_cost_usd") or "0")
        console.print(f"[dim]{ts}[/dim]  [green]✓ completed[/green]  {exec_id}  {cost}")
    elif event_type in ("ExecutionFailed", "WorkflowFailed"):
        exec_id = str(data.get("execution_id", ""))[:12]
        err = str(data.get("error_message") or "")[:60]
        console.print(f"[dim]{ts}[/dim]  [red]✗ failed[/red]  {exec_id}  {err}")
    elif event_type == "PhaseStarted":
        phase = str(data.get("phase_name", ""))
        console.print(f"[dim]{ts}[/dim]  [blue]→ phase[/blue]  {phase}")
    elif event_type == "PhaseCompleted":
        phase = str(data.get("phase_name", ""))
        console.print(f"[dim]{ts}[/dim]  [blue]✓ phase[/blue]  {phase}")
    elif event_type == "SessionTokensRecorded":
        tokens = data.get("total_tokens", 0)
        cost = format_cost(data.get("cost_usd") or "0")
        console.print(f"[dim]{ts}[/dim]  [dim]tokens {tokens}  {cost}[/dim]")
    elif event_type:
        status = str(data.get("status", ""))
        style = status_style(status)
        suffix = f"  [{style}]{status}[/{style}]" if status and style else ""
        console.print(f"[dim]{ts}[/dim]  [dim]{event_type}[/dim]{suffix}")


@app.command("execution")
def watch_execution(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to watch")],
) -> None:
    """Stream live events for a specific execution."""
    url = f"/sse/executions/{execution_id}"
    base = get_api_url()
    console.print(f"[dim]Connecting to {base}{url} …[/dim]")
    console.print("[dim]Press Ctrl-C to stop.[/dim]")
    console.print()

    try:
        with get_streaming_client() as client:
            with client.stream("GET", url) as response:
                if response.status_code == 404:
                    print_error(f"Execution not found: {execution_id}")
                    raise typer.Exit(1)
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    raise typer.Exit(1)

                for line in response.iter_lines():
                    if not line:
                        continue
                    frame = _parse_sse_line(line)
                    if frame is None:
                        continue
                    frame_type = str(frame.get("type", ""))
                    if frame_type == "connected":
                        console.print("[green]Connected.[/green]")
                    elif frame_type == "terminal":
                        _render_event(frame)
                        console.print("[dim]Stream ended.[/dim]")
                        return
                    elif frame_type == "event":
                        _render_event(frame)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    except Exception:
        print_error(f"Could not connect to API at {get_api_url()}")
        console.print("[dim]Make sure the API server is running.[/dim]")
        raise typer.Exit(1)


@app.command("activity")
def watch_activity() -> None:
    """Stream live global activity across all executions."""
    url = "/sse/activity"
    base = get_api_url()
    console.print(f"[dim]Connecting to {base}{url} …[/dim]")
    console.print("[dim]Press Ctrl-C to stop.[/dim]")
    console.print()

    try:
        with get_streaming_client() as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    raise typer.Exit(1)

                for line in response.iter_lines():
                    if not line:
                        continue
                    frame = _parse_sse_line(line)
                    if frame is None:
                        continue
                    frame_type = str(frame.get("type", ""))
                    if frame_type == "connected":
                        console.print("[green]Connected — watching global activity.[/green]")
                    elif frame_type == "event":
                        _render_event(frame)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    except Exception:
        print_error(f"Could not connect to API at {get_api_url()}")
        console.print("[dim]Make sure the API server is running.[/dim]")
        raise typer.Exit(1)
