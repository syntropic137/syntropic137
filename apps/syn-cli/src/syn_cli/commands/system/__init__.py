"""System management commands — CRUD plus status, cost, activity, patterns, history."""

from syn_cli.commands.system._crud import app, create, delete, list_systems, show, update
from syn_cli.commands.system._observability import (
    system_activity,
    system_cost,
    system_history,
    system_patterns,
    system_status,
)

__all__ = [
    "app",
    "create",
    "delete",
    "list_systems",
    "show",
    "system_activity",
    "system_cost",
    "system_history",
    "system_patterns",
    "system_status",
    "update",
]
