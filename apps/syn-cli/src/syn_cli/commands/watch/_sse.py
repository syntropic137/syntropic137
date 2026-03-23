"""SSE streaming loop and watch commands."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from syn_cli._output import console, print_error
from syn_cli.client import get_api_url, get_streaming_client
from syn_cli.commands.watch._render import app, parse_sse_line, render_event


def _process_sse_lines(response: Any, connected_msg: str, *, handle_terminal: bool) -> None:
    """Process SSE lines from a streaming response."""
    for line in response.iter_lines():
        if not line:
            continue
        frame = parse_sse_line(line)
        if frame is None:
            continue
        frame_type = str(frame.get("type", ""))
        if frame_type == "connected":
            console.print(f"[green]{connected_msg}[/green]")
        elif frame_type == "terminal" and handle_terminal:
            render_event(frame)
            console.print("[dim]Stream ended.[/dim]")
            return
        elif frame_type == "event":
            render_event(frame)


def _stream_sse(
    url: str,
    connected_msg: str,
    *,
    handle_terminal: bool = False,
) -> None:
    """Shared SSE streaming loop with error handling."""
    base = get_api_url()
    console.print(f"[dim]Connecting to {base}{url} …[/dim]")
    console.print("[dim]Press Ctrl-C to stop.[/dim]")
    console.print()

    try:
        with get_streaming_client() as client, client.stream("GET", url) as response:
            if response.status_code not in (200,):
                msg = (
                    f"Not found: {url}"
                    if response.status_code == 404
                    else f"HTTP {response.status_code}"
                )
                print_error(msg)
                raise typer.Exit(1)
            _process_sse_lines(response, connected_msg, handle_terminal=handle_terminal)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    except typer.Exit:
        raise
    except Exception:
        print_error(f"Could not connect to API at {get_api_url()}")
        console.print("[dim]Make sure the API server is running.[/dim]")
        raise typer.Exit(1) from None


@app.command("execution")
def watch_execution(
    execution_id: Annotated[str, typer.Argument(help="Execution ID to watch")],
) -> None:
    """Stream live events for a specific execution."""
    _stream_sse(
        f"/sse/executions/{execution_id}",
        "Connected.",
        handle_terminal=True,
    )


@app.command("activity")
def watch_activity() -> None:
    """Stream live global activity across all executions."""
    _stream_sse("/sse/activity", "Connected — watching global activity.")
