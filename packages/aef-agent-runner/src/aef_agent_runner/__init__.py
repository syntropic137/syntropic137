"""AEF Agent Runner - Execute Claude agents inside isolated containers.

This package is designed to run INSIDE isolated workspace containers.
It reads task configuration, executes the Claude agent SDK, and emits
JSONL events to stdout for the orchestrator to parse.

Key features:
- Task-driven execution from /workspace/task.json
- JSONL event streaming to stdout
- Artifact writing to /workspace/artifacts/
- Graceful cancellation via /workspace/.cancel
- SDK hooks for observability and safety validation
- Zero-trust: agent never sees raw API tokens (sidecar injects them)
"""

__version__ = "0.1.0"

from aef_agent_runner.events import AgentEvent, emit_event
from aef_agent_runner.hooks import (
    HookEventName,
    PermissionDecision,
    ToolName,
    create_hooks_config,
)
from aef_agent_runner.runner import AgentRunner
from aef_agent_runner.task import Task

__all__ = [
    "AgentEvent",
    "AgentRunner",
    "HookEventName",
    "PermissionDecision",
    "Task",
    "ToolName",
    "create_hooks_config",
    "emit_event",
]
