# ADR-072: Workspace Access to the Syntropic137 API

- **Status**: Accepted (read scope only; the eval scope is split out to #1744, see "Not granted")
- **Date**: 2026-10-07
- **Issue**: PC-127; unblocks #1724, #1726, #1727
- **Related**: ADR-024 (setup-phase secrets), ADR-059 (gateway two-port auth model), ADR-060 (in-memory adapter guard), ADR-021 (isolated workspaces)

## Context

Every run that measures or improves the platform needs to read the platform:
the capacity model, the eval A/B, the scorecard, the eval-optimizer loop. From
a workspace, every `/api/v1` call failed with HTTP 000. There was no route and
no credential.

Three facts shaped the design:

1. **The API has no auth of its own.** ADR-059 puts all auth in the nginx
   gateway, and gateway port 80 serves the internal network with
   `auth_basic off`. ADR-059 calls Docker network isolation the security
   boundary. Putting `api` or `gateway` on `agent-net` would therefore give
   every workspace unauthenticated read-write access to everything.
2. **Workspaces already reach the outside only through Envoy** (`envoy-proxy`
   on `agent-net`), and Envoy already shares a network with `api`
   (`syn-internal` in selfhost, `default` in dev).
3. **The `syn` CLI already reads `SYN_API_URL` and `SYN_API_TOKEN`** and sends
   the token as `Authorization: Bearer` (`apps/syn-cli-node/src/config.ts`).

## Decision

### 1. One setting, default OFF

`SYN_PLATFORM_ACCESS_ENABLED` (`PlatformAccessSettings`). OFF means two things,
and both come from one wiring decision: `get_platform_token_service()` builds
the service with **no store**. A service with no store issues nothing, so no
workspace gets `SYN_API_TOKEN`, and it refuses every workspace-ingress request
with 403. "Off" cannot be half-wired.

The same variable also reaches `envoy-proxy`. Its `entrypoint.sh` writes the
Envoy runtime key `syn_platform.access_enabled` only when the value is true,
and both `/syn-platform` routes match only when that key is on (default 0%).
So with access OFF there is **no route**: a workspace request ends at Envoy's
local 404 and nothing is forwarded to the API. The API's 403 stays as defense
in depth. `ci/fitness/infrastructure/test_platform_route_is_switched.py` keeps
every route to `syn_platform_api` gated, and keeps Envoy's admin interface out
of a workspace's reach. Port 9901 is reachable from `agent-net`, so Envoy's
admin API listens on `127.0.0.1:9900` only and 9901 is a listener that forwards
`GET /ready` and nothing else. Admin on 9901 would let a workspace flip the
switch (`POST /runtime_modify`), raise the log level so Envoy prints other
workspaces' `Authorization` headers (`POST /logging`), or stop the proxy. The
runtime also has no admin layer, as a second lock on the switch.

### 2. The route: a path on the Envoy sidecar, not a network join

Workspace containers do not set `HTTP_PROXY`; they reach Envoy by name, as
`ANTHROPIC_BASE_URL=http://envoy-proxy:8081` already does. So the route is a
path on that host: `SYN_API_URL=http://envoy-proxy:8081/syn-platform`. Only
`/syn-platform/api/v1/` (rewritten to `/`, as nginx does) and
`/syn-platform/health` are forwarded; any other `/syn-platform/` path gets a
404 from Envoy. They go to the `api:8000` cluster directly and **never through
the gateway**.

On these routes:

- `x-syn-workspace-ingress` is set with `OVERWRITE_IF_EXISTS_OR_ADD`, so
  whatever a workspace sends, the API knows the request came from a workspace.
- ext_authz is disabled per route (`ExtAuthzPerRoute`). The token-injector
  would otherwise add the Anthropic credential for the `envoy-proxy` host to a
  request bound for our own API. With it off, the workspace's own
  `Authorization: Bearer` header is the only credential, and it reaches the
  API unchanged.

Neither `api` nor `gateway` joins `agent-net`. Envoy already shares a network
with `api` (`syn-internal` in selfhost, `default` in dev); the only compose
change is forwarding the setting to `envoy-proxy` (section 1). This is the
boundary for reaching the API, not for all egress: `agent-net` is not
`internal`, and harness credentials still follow ADR-024. The ADR-059 boundary still holds for every path except this one, and
this path is authenticated.

### 3. The API enforces scope server-side

`WorkspaceIngressMiddleware` is the **outermost** middleware. It runs before
the startup gate and before every router. A request carrying the ingress header
must present a token whose scope allows the method and path, or it gets a 401
(no token, unknown, expired or revoked) or a 403 (access off, or out of scope).
Requests without the header come from the internal network and are not touched
(ADR-059 is unchanged for them).

The path judged is the **router-relative** path, stripped of the ASGI
`root_path` by Starlette's own rule (`get_route_path`), because selfhost runs
Uvicorn with `--root-path /api/v1` and hands the app `/api/v1/health`. And
since the API never sees the `/syn-platform/api/v1` prefix Envoy stripped, a
same-host `Location` header (a framework redirect such as `/health/` to
`/health`) is re-rooted onto that prefix on workspace-ingress responses, so a
client following it stays on the authenticated route.

The allowlist lives in one place, `syn_adapters.platform_access`. It fails
closed: a route added later is denied until someone adds its first path
segment. The policy is per resource, not per route: a GET added later under
an allowed first segment (`/executions/...`) is readable at once.

| Scope | Methods | First path segment |
|---|---|---|
| `read` | GET, HEAD | `executions`, `sessions`, `artifacts`, `evals`, `insights`, `health` |

`workflows`, `triggers`, `github`, `organizations`, `costs`, `conversations`,
`events`, `maintenance` and every write method are refused.

### 4. The token (extends ADR-024)

ADR-024 injects provider credentials during setup and keeps them out of the
agent's reach where it can. The platform token is the opposite kind of
credential: the agent is **meant** to hold it. So it is made harmless to hold
rather than hidden:

- `synpt_` + 32 random bytes, shown once. The store keeps only its SHA-256.
- One token per workspace, minted in `WorkspaceService.create_workspace`
  (the token's lifetime is the workspace's) and handed to the agent as
  `SYN_API_URL` / `SYN_API_TOKEN` by `ManagedWorkspace.stream`, the one
  launch path every provider uses, so codex phases get it as well.
- Bounded by the phase deadline. The first launch carrying
  `SYN_PHASE_DEADLINE` lowers the grant's expiry (store TTL and `expires_at`)
  to `min(issued + max TTL, deadline)`. It never raises it, so a retry sharing
  the phase's deadline changes nothing.
- Revoked in `create_workspace`'s `finally`, beside the GitHub token
  revocation (#725). If revocation fails, the token still expires at
  `SYN_PLATFORM_ACCESS_TOKEN_TTL_SECONDS` (store TTL **and** an explicit
  `expires_at` check, so a store that ignores TTL cannot extend it).
- Never logged. Log lines name the execution id, and `WorkspacePlatformGrant`
  hides the token from `repr`. The token rides the `docker exec -e` argv, so
  `capture_signal_death` replaces every `-e`/`--env` value with `<redacted>`
  before a `SignalDeath` (logged at ERROR) retains the command.
- Store: Redis (`syn:platform-token:<sha256>`) in production, because a grant
  must survive an API restart or every running phase loses access.
  `InMemoryPlatformTokenStore` inherits `InMemoryAdapter` (ADR-060).

## Not granted, and why

**The eval scope (launch into an eval, record a score) is not built here.** It
is tracked in #1744. This ADR ships the read scope only.

- `POST /evals/{id}/runs/{exec}/score` now exists on `main`, but a platform
  token cannot reach it: the read scope allows GET and HEAD only, and the API
  refuses every other method from a workspace. Granting it needs a second
  scope bound to one eval and one execution, which is #1744's design.
- `POST /workflows/{id}/execute` with `eval_id` starts an execution. A
  credential that can start executions is exactly what this boundary exists to
  prevent. Granting it safely needs body-aware enforcement (eval_id required,
  workflow pinned to the eval's), a `platform_access: eval` declaration on the
  phase definition, and a budget story. Each of those is its own design.

The scope enum has one member on purpose. Adding a second is a change to this
ADR, not a line in a table.

## Image contract (agentic-workspace)

No workspace image ships the `syn` CLI today. The contract on this side is
fixed and needs nothing new from the image except the binary:

- `SYN_API_URL` = `http://envoy-proxy:8081/syn-platform` (overridable with
  `SYN_PLATFORM_ACCESS_WORKSPACE_API_URL`). The CLI appends `/api/v1`.
- `SYN_API_TOKEN` = the platform token, sent as `Bearer`.
- Both arrive in the environment of every agent launch
  (`ManagedWorkspace.stream`), for claude and codex phases alike.

**What agentic-workspace must do:** install `@syntropic137/cli` in the
`claude-cli` and `omni-agent` images, release it, and bump `PINNED_DIGESTS`
here. Nothing else: no proxy or DNS configuration is needed. Until then an
agent can use
`curl -H "Authorization: Bearer $SYN_API_TOKEN" "$SYN_API_URL/api/v1/executions"`.

## Consequences

- ADR-059's sentence "port 80 relies on Docker network isolation" stays true.
  This ADR adds a second, authenticated path into the API that does not go
  through the gateway at all.
- The owner's deployment turns this on with `SYN_PLATFORM_ACCESS_ENABLED=true`.
  Nothing else changes for anyone else.
- An agent holding a read token can read every execution, session and
  artifact on the instance, not only its own. That is the point for the
  measurement workflows. On a multi-tenant instance it is not acceptable, and
  it would need per-tenant scoping (ADR-022, on hold).
