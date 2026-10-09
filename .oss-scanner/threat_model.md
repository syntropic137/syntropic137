# Threat model

Read by Anthropic's OSS Scanner before it scans this repository. Every
statement below is grounded in a file in this repo; paths are given so a claim
can be checked. Disclosure policy: [SECURITY.md](../SECURITY.md).

## What this project does

Syntropic137 orchestrates AI coding agents (Claude Code, Codex) inside
isolated Docker workspaces and records every event they produce for
observability. It is self-hosted: one operator runs the whole stack with
Docker Compose (`docker/docker-compose.syntropic137.yaml`).

| Component | Where | Role |
|---|---|---|
| API (FastAPI, Python 3.12) | `apps/syn-api/` | HTTP API, GitHub webhooks, workflow execution, workspace lifecycle |
| Domain + adapters | `packages/syn-domain/`, `packages/syn-adapters/` | Event-sourced aggregates, workspace backends, agent stream parsing |
| Collector | `packages/syn-collector/` | Ingests agent hook events and OTLP telemetry |
| CLI `syn` (Node 22, TypeScript) | `apps/syn-cli-node/` | HTTP client for the API; installs workflow packages from git marketplaces |
| Dashboard (React + Vite) | `apps/syn-dashboard-ui/` | Operator UI, renders agent output and events |
| Gateway (nginx) | `infra/docker/images/gateway/` | Front door; basic auth on the external port (ADR-059) |
| Envoy sidecar proxy | `docker/sidecar-proxy/` | Agents reach model APIs and the platform route through it |
| Token injector | `docker/token-injector/token_injector.py` | Envoy ext_authz service; swaps the `proxy-managed` placeholder for the real model credential |
| Docker socket proxy | `docker/docker-compose.syntropic137.yaml` | Allowlisted Docker API for the API container |
| Event store (Rust, gRPC) | `lib/event-sourcing-platform` (submodule) | Separate project; only its Python SDK is used here |
| Workspace images, isolation provider | `lib/agentic-workspace` (submodule) | Separate project; `agentic_isolation` builds the containers |

Submodules under `lib/` are fetched by `.oss-scanner/Dockerfile` so the code
builds and tests offline, but they are separate repositories and **out of
scope** here except where this repo's code calls them.

## Trust boundaries and untrusted input

The core assumption, from ADR-021 ("Threat Model"): **an agent workspace is
hostile.** Agents run arbitrary shell commands on repositories they clone and
can be prompt-injected by file content, issues or PRs. Everything that crosses
from a workspace back into the platform is untrusted.

1. **Agent workspace -> host and platform.** Highest-value boundary.
   - Agent stdout/stderr JSONL streams are parsed on the host:
     `packages/syn-domain/.../execute_workflow/EventStreamProcessor.py`,
     `HookEventParser.py`, `packages/syn-adapters/src/syn_adapters/events/parse.py`,
     `packages/syn-adapters/src/syn_adapters/workspace_backends/service/codex_rollout.py`,
     `packages/syn-collector/src/syn_collector/watcher/parsing.py`. The content
     is agent-controlled.
   - Files agents write are read by the platform: artifact collection from
     the host bind-mounted workspace directory
     (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py`,
     `workspace_walk.py`), session capture and transcripts
     (`capture_result.py`, `packages/syn-adapters/src/syn_adapters/session_inventory/`).
     Paths, symlinks, sizes and contents are agent-controlled.
   - Git repositories in the workspace (agent-authored commits, branches,
     hooks, config) are pushed and inspected by the platform at teardown.
   - Agent output is rendered in the dashboard (`apps/syn-dashboard-ui/`).
   - Workspace -> Envoy (`docker/sidecar-proxy/envoy.yaml`) and the token
     injector: an agent must not obtain the model credential the injector
     adds, reach Envoy's admin interface, or reach the API except through the
     authenticated `/syn-platform` route.
2. **Workspace platform tokens (ADR-072).** A workspace may hold a
   `synpt_` read-scoped token. `WorkspaceIngressMiddleware` and
   `syn_adapters.platform_access` enforce its scope server-side. A token
   escaping its scope (write methods, denied path segments, another
   deployment) is in scope. Off by default (`SYN_PLATFORM_ACCESS_ENABLED`).
3. **GitHub -> API.** Webhook payloads at `POST /webhooks/github`
   (`apps/syn-api/src/syn_api/routes/webhooks/endpoint.py`, HMAC check in
   `signature.py`), plus Events API and Checks API polling
   (`apps/syn-api/src/syn_api/services/github_event_poller.py`,
   `check_run_poller.py`). Payload fields (branch names, PR titles and
   bodies, comments) flow into trigger rules and agent prompts.
4. **GitHub App credentials** (`infra/docs/github-app-security.md`, ADR-024).
   The PEM stays in the API container (Docker secret). Workspaces receive
   only repo-scoped, 1-hour installation tokens written to
   `~/.git-credentials` and `~/.config/gh/hosts.yml`. Leaking the PEM, or a
   token wider than the workspace's repositories, is in scope.
5. **Operator -> API and dashboard.** The API has no auth of its own; nginx
   basic auth on gateway port 8081 is the external boundary, and port 80 is
   unauthenticated and relies on Docker network isolation (ADR-059). An
   unauthenticated path to the API from outside, or from `agent-net` other
   than the ADR-072 route, is in scope.
6. **API -> Docker engine.** Through `tecnativa/docker-socket-proxy` only
   (`docs/security-practices.md`, ADR-021 addendum). A path from workspace
   or webhook input to influencing what the API asks Docker to create is in
   scope.
7. **Workflow definitions and marketplace packages.** Workflow YAML and
   Markdown prompts (`packages/syn-domain/.../_shared/workflow_definition.py`,
   `md_prompt_loader.py`), skills and Claude plugins
   (`register_skill/`, `apps/syn-api/src/syn_api/services/claude_plugin_resolution_service.py`),
   and the CLI's git-based marketplace install (`apps/syn-cli-node/src/marketplace/`).
   Treat third-party packages as untrusted.
8. **Uploaded artifacts** (`POST /artifacts`, `/artifacts/{id}/upload` in
   `apps/syn-api/src/syn_api/routes/artifacts.py`) stored in MinIO and served
   back to the dashboard.

## Known, publicly tracked hardening work

Reports that only restate these add little; reports showing a concrete new
consequence of them are welcome.

- #1794: `agent-net` is not `internal` in production, so workspaces have
  direct internet egress.
- #1806: the socket proxy does not restrict the `HostConfig` the API may
  request when creating containers.
- #1735: model and GitHub credentials still live inside the workspace.
- ADR-072 "Consequences": a read-scoped platform token can read every
  execution, session and artifact on the instance (single-tenant by design).

## Components that matter most / least

Most: workspace -> host data paths (stream parsing, artifact and capture
reads, teardown git operations), the token injector and Envoy config,
`WorkspaceIngressMiddleware` / `platform_access`, webhook signature
verification, GitHub token scoping, socket-proxy usage.

Less: dashboard (XSS from agent output still matters), CLI.

Out of scope: `apps/syn-docs/` (static public docs site), `experiments/`,
`evals/`, `fixtures/`, `scripts/` (developer tooling), test code, and the
`lib/` submodules as products in their own right.

## How to exercise it

The image has the full Python and Node workspaces installed; no network,
database or Docker daemon is available.

- Python unit tests: `uv run pytest -m unit -q` (from `/src`). Tests marked
  `integration`/`e2e` need Postgres, Redis, the event store or Docker and do
  not run offline. Known environment-only failures in this image:
  `scripts/tests/test_1310_pit_stop_gateway_only.py` assumes the checkout
  directory is named `syntropic137` (it is `/src` here); it tests operator
  release tooling and is out of scope.
- Focused: `uv run pytest -q -m unit apps/syn-api/tests`,
  `packages/syn-domain/tests`, `packages/syn-adapters/tests`,
  `docker/token-injector/tests`.
- Node: `pnpm --dir apps/syn-cli-node test`, `pnpm --dir apps/syn-dashboard-ui test`.
- The API app can be built in-process with FastAPI's `TestClient` (see
  `apps/syn-api/tests/` for fixtures); webhook signature tests are in
  `apps/syn-api/tests/test_webhooks_signature.py`.

## How we rate severity

- **Critical:** escape from an agent workspace to the host or the API
  container; an agent obtaining the model credential, the GitHub App PEM, or
  another workspace's tokens; unauthenticated remote code execution or
  write access to the API from outside the gateway.
- **High:** a workspace-controlled input (stream, file, symlink, git object)
  that reads or writes host files outside its workspace; a platform token
  exceeding its scope; webhook signature bypass; a GitHub token wider than the
  workspace's repositories; stored XSS in the dashboard from agent output.
- **Medium:** denial of service of the API, collector or projections from a
  single workspace or webhook; information disclosure across executions not
  already accepted under ADR-072.
- **Low:** issues needing an already-authenticated operator, or local
  developer-only tooling.

Reports should include the input, the boundary crossed, and a test in the
style of the nearest existing test file. Patches should keep strict typing
(pyright, no `Any`).

## Anything to leave alone

- Missing auth on gateway port 80 or the API itself: documented design
  (ADR-059); report only a way to reach it from outside the Docker network.
- `InMemory*` adapters: refuse to construct outside test/offline (ADR-060).
- Dev-only compose files and `.env.example` placeholder values.
