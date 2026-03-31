# Smoke Test: Selfhost Stack Validation

> **Issue:** [#405](https://github.com/syntropic137/syntropic137/issues/405)
> **Workflow:** [`.github/workflows/smoke-test.yml`](../../.github/workflows/smoke-test.yml)

## What It Tests

The smoke test builds and starts the selfhost Docker Compose stack with locally-built images, then validates infrastructure connectivity that unit tests can't catch:

| Check | What it catches |
|-------|----------------|
| API health endpoint (`/health`) | Misconfigured environment, broken entrypoints, missing dependencies |
| Docker CLI in syn-api image | `INCLUDE_DOCKER_CLI` build-arg not passed (silent Docker ignore) |
| Envoy proxy admin `/ready` | Proxy build failures, missing envoy.yaml config |
| DNS resolution from agent-net | Service name mismatch between code and compose (ISS-405 root cause) |
| Workflow creation round-trip | API → event store → projection pipeline working end-to-end |

## When It Runs

- **Push** to `main` or `release/**` branches (when `docker/**`, `infra/docker/**`, or the workflow itself changes)
- **Pull requests** targeting `main` that touch the same paths
- **Manual** via `workflow_dispatch`

## How It Works

1. Creates dummy secrets and minimal `.env` (no real API keys needed)
2. Runs `docker compose -f docker-compose.yaml -f docker-compose.selfhost.yaml up --build -d`
3. Waits for the API container health check (up to 5 minutes)
4. Runs validation checks against the running stack
5. Tears down with `docker compose down -v --remove-orphans`

The stack uses the **selfhost overlay** with **locally-built images** — the same Dockerfiles and build-args as the release pipeline. This catches configuration drift between what we build and what we ship.

## Running Locally

```bash
# Full selfhost stack (same as CI)
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.selfhost.yaml \
  up --build -d

# Wait for healthy
docker inspect --format='{{.State.Health.Status}}' syn137-api

# Quick health check
curl http://localhost:8137/health

# Tear down
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.selfhost.yaml \
  down -v
```

## Test Tiers

The smoke test sits between unit tests and full E2E acceptance tests:

| Tier | What | Speed | Infra needed | Runs on |
|------|------|-------|-------------|---------|
| **Unit** | Logic, pure functions | ~30s | None | Every push |
| **Fitness** | Architecture invariants (AST, YAML parsing) | ~5s | None | Every push |
| **Smoke** (this) | Infrastructure connectivity, image correctness | ~10min | Docker | Release branches, docker/** changes |
| **Integration** | DB round-trips, event store | ~2min | TimescaleDB | Weekly + main |
| **E2E Acceptance** | Real agent execution | ~15min | Full stack + API keys | Manual |

## Fitness Tests (Tier 1)

The smoke test workflow is complemented by **config consistency fitness tests** in `ci/fitness/infrastructure/` that run on every push (no Docker needed):

- **`test_proxy_hostname_agreement`** — Asserts `DEFAULT_PROXY_URL`, envoy.yaml domains, and token injector allowlist all agree on the same proxy hostname
- **`test_phase_definition_roundtrip`** — Asserts `_build_phase_defs` preserves all 13 PhaseDefinition fields (regression for ISS-405 field-drop bug)
- **`test_compose_consistency`** — Validates compose YAML parsing and build-arg/Dockerfile ARG alignment

## Troubleshooting

**API doesn't become healthy:**
Check API logs: `docker compose -f docker/docker-compose.yaml -f docker/docker-compose.selfhost.yaml logs api`

Common causes: missing secrets files, event-store not starting (Rust build issue), TimescaleDB initialization timeout.

**DNS resolution fails:**
The agent-net network name includes the compose project name. If you see "network not found", check `docker network ls | grep agent-net` for the actual name.

**Docker CLI not found in syn-api:**
The `INCLUDE_DOCKER_CLI=1` build-arg must be in `docker-compose.selfhost.yaml` under `api.build.args`. If missing, Docker silently ignores it — this is exactly the class of bug the smoke test catches.
