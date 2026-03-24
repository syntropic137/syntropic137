"""Watch commands — live SSE stream of execution or global activity."""

from syn_cli.commands.watch._render import app
from syn_cli.commands.watch._sse import watch_activity, watch_execution

__all__ = ["app", "watch_activity", "watch_execution"]
