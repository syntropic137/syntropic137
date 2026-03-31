"""Workflow ID resolution with partial matching."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from syn_cli._output import console, print_error
from syn_cli.commands._workflow_models import WorkflowSummary

if TYPE_CHECKING:
    import httpx


class WorkflowResolver:
    """Resolves partial workflow IDs to full workflow summaries."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def resolve(self, partial_id: str, *, include_archived: bool = False) -> WorkflowSummary:
        """Resolve a partial workflow ID to a full WorkflowSummary.

        Args:
            partial_id: Full or partial workflow ID
            include_archived: Search archived workflows too

        Returns:
            Matched WorkflowSummary

        Raises:
            typer.Exit: On not-found or ambiguous match
        """
        params: dict[str, str] = {}
        if include_archived:
            params["include_archived"] = "true"
        list_resp = self._client.get("/workflows", params=params)
        if list_resp.status_code != 200:
            print_error("Failed to list workflows")
            raise typer.Exit(1)

        workflows = list_resp.json().get("workflows", [])
        matching = [w for w in workflows if w["id"].startswith(partial_id)]

        if not matching:
            print_error(f"No workflow found matching: {partial_id}")
            raise typer.Exit(1)

        if len(matching) > 1:
            console.print(f"[yellow]Multiple workflows match '{partial_id}':[/yellow]")
            for w in matching[:5]:
                console.print(f"  {w['id'][:12]}... - {w['name']}")
            console.print("[dim]Please provide a more specific ID[/dim]")
            raise typer.Exit(1)

        return WorkflowSummary(
            id=matching[0]["id"],
            name=matching[0]["name"],
            workflow_type=matching[0]["workflow_type"],
            phase_count=matching[0].get("phase_count", 0),
        )
