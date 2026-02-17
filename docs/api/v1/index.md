# v1 API Reference

Version 1 of the AEF programmatic API.

## Changelog

### v0.1.0 (Phase 1)

- Initial release
- Core workflow operations: `list_workflows`, `get_workflow`, `create_workflow`, `execute_workflow`, `get_execution`, `list_executions`
- Workspace operations: `create_workspace`, `terminate_workspace`
- Session operations: `list_sessions`, `start_session`, `complete_session`
- Stub modules: artifacts, github, observability (signatures and types complete, implementation pending)

## Modules

- [workflows](workflows.md) — Workflow template CRUD and execution
- [workspaces](workspaces.md) — Isolated workspace management
- [sessions](sessions.md) — Agent session lifecycle
- [artifacts](artifacts.md) — Artifact storage (stub)
- [github](github.md) — GitHub integration (stub)
- [observability](observability.md) — Metrics and telemetry (stub)
- [types](types.md) — Result type, error enums, shared models
- [auth](auth.md) — AuthContext reference
