"""Canonical workspace paths for isolated agent execution.

These constants define the standard directory structure inside
isolated workspaces (Docker containers, VMs, etc.).

All paths are relative to /workspace (the container mount point).

Usage:
    from aef_shared.workspace_paths import (
        WORKSPACE_ROOT,
        WORKSPACE_OUTPUT_DIR,
        WORKSPACE_CONTEXT_DIR,
        WORKSPACE_TASK_FILE,
    )

Note:
    These are PurePosixPath objects for platform-independent path handling.
    When used inside containers (always Linux), they work directly.
    On the host, convert to Path if needed: Path(str(WORKSPACE_OUTPUT_DIR))
"""

from pathlib import PurePosixPath

# Base workspace root (where host directory is mounted)
WORKSPACE_ROOT = PurePosixPath("/workspace")

# Agent output artifacts - collected after execution
# This is where the agent should write any output files
WORKSPACE_OUTPUT_DIR = WORKSPACE_ROOT / "artifacts"

# Injected context directory (task.json, input artifacts)
# This is where the orchestrator writes files for the agent
WORKSPACE_CONTEXT_DIR = WORKSPACE_ROOT / ".context"

# Task file location - contains phase configuration for the agent
WORKSPACE_TASK_FILE = WORKSPACE_CONTEXT_DIR / "task.json"

# Analytics events from hooks (written by agentic-primitives hooks)
WORKSPACE_ANALYTICS_DIR = WORKSPACE_ROOT / ".agentic" / "analytics"

# Analytics events file
WORKSPACE_ANALYTICS_FILE = WORKSPACE_ANALYTICS_DIR / "events.jsonl"

# Claude hooks and settings
WORKSPACE_CLAUDE_DIR = WORKSPACE_ROOT / ".claude"
WORKSPACE_HOOKS_DIR = WORKSPACE_CLAUDE_DIR / "hooks"
WORKSPACE_SETTINGS_FILE = WORKSPACE_CLAUDE_DIR / "settings.json"

# Container logs directory
WORKSPACE_LOGS_DIR = WORKSPACE_ROOT / ".logs"

# All exported constants
__all__ = [
    "WORKSPACE_ANALYTICS_DIR",
    "WORKSPACE_ANALYTICS_FILE",
    "WORKSPACE_CLAUDE_DIR",
    "WORKSPACE_CONTEXT_DIR",
    "WORKSPACE_HOOKS_DIR",
    "WORKSPACE_LOGS_DIR",
    "WORKSPACE_OUTPUT_DIR",
    "WORKSPACE_ROOT",
    "WORKSPACE_SETTINGS_FILE",
    "WORKSPACE_TASK_FILE",
]
