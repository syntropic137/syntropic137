"""Shared utilities for Syntropic137."""

__version__ = "0.1.0"

# Re-export commonly used items for convenience
from syn_shared.env_constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_ANTHROPIC_BASE_URL,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_CLAUDE_SESSION_ID,
    ENV_SYN_AGENT_NETWORK,
    ENV_SYN_WORKSPACE_CONTAINER_DIR,
    ENV_SYN_WORKSPACE_HOST_DIR,
    MODEL_HAIKU,
    MODEL_OPUS,
    MODEL_SONNET,
)
from syn_shared.logging import LogConfig, configure_logging, get_logger
from syn_shared.settings import AppEnvironment, Settings, get_settings
from syn_shared.workspace_paths import (
    WORKSPACE_ANALYTICS_DIR,
    WORKSPACE_ANALYTICS_FILE,
    WORKSPACE_ARTIFACTS_DIR,
    WORKSPACE_CLAUDE_DIR,
    WORKSPACE_CONTEXT_DIR,
    WORKSPACE_HOOKS_DIR,
    WORKSPACE_INPUT_DIR,
    WORKSPACE_LOGS_DIR,
    WORKSPACE_OUTPUT_DIR,
    WORKSPACE_REPOS_DIR,
    WORKSPACE_ROOT,
    WORKSPACE_SETTINGS_FILE,
    WORKSPACE_TASK_FILE,
)

__all__ = [
    "ENV_ANTHROPIC_API_KEY",
    "ENV_ANTHROPIC_BASE_URL",
    "ENV_CLAUDE_CODE_OAUTH_TOKEN",
    "ENV_CLAUDE_SESSION_ID",
    "ENV_SYN_AGENT_NETWORK",
    "ENV_SYN_WORKSPACE_CONTAINER_DIR",
    "ENV_SYN_WORKSPACE_HOST_DIR",
    "MODEL_HAIKU",
    "MODEL_OPUS",
    "MODEL_SONNET",
    "WORKSPACE_ANALYTICS_DIR",
    "WORKSPACE_ANALYTICS_FILE",
    "WORKSPACE_ARTIFACTS_DIR",
    "WORKSPACE_CLAUDE_DIR",
    "WORKSPACE_CONTEXT_DIR",
    "WORKSPACE_HOOKS_DIR",
    "WORKSPACE_INPUT_DIR",
    "WORKSPACE_LOGS_DIR",
    "WORKSPACE_OUTPUT_DIR",
    "WORKSPACE_REPOS_DIR",
    "WORKSPACE_ROOT",
    "WORKSPACE_SETTINGS_FILE",
    "WORKSPACE_TASK_FILE",
    "AppEnvironment",
    "LogConfig",
    "Settings",
    "configure_logging",
    "get_logger",
    "get_settings",
]
