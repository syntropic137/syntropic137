# ADR-060: On-Demand Environment Creation

- **Status:** Proposed
- **Date:** 2026-04-11
- **Context:** DORA capability - on-demand environment creation for branch-based testing

## Problem

Testing changes across branches requires manually stopping/starting the dev stack or running a single test stack with hardcoded port offsets. There's no way to:

1. Run two feature branches side-by-side for comparison testing
2. Hand an agent a URL and say "test against this environment running branch X"
3. Discover which environments are running, what branches they track, and what ports they use

The existing test stack (port +10000) proves the concept works but is hardcoded to a single additional environment. Scaling to N parallel environments needs dynamic port allocation, branch awareness, and a discovery mechanism.

## Decision

Implement on-demand environment creation in three phases, each building on the previous.

### Phase 1: Local On-Demand Environments (Implemented)

A Docker Compose overlay (`docker-compose.ondemand.yaml`) layered on the base compose, parameterized by environment name and port offsets. Managed via `infra/scripts/env_manager.py` and `just` recipes.

**DRY Compose Architecture:**

All stacks share a single base compose that defines service images, health checks, dependencies,
and shared infrastructure (docker-socket-proxy, envoy-proxy, token-injector, internal networks).
Overlays add only environment-specific config:

```
docker/
  docker-compose.yaml            # Base: images, health checks, deps, shared infra
  docker-compose.dev.yaml        # Dev: ports, volumes, restart
  docker-compose.selfhost.yaml   # Prod: secrets, resource limits, gateway, security
  docker-compose.ondemand.yaml   # On-demand: parameterized ports, gateway, ephemeral
```

The ondemand overlay mirrors the selfhost stack (including gateway/UI) for full e2e testing.
Services that are fully defined in base (docker-socket-proxy) only get a `container_name` in the overlay.
No persistent volumes - each environment starts with a clean slate.

**Port allocation strategy:**

Each environment gets a slot (2-5). Port offsets derived deterministically:

```
Slot 0: dev stack        (hardcoded: 5432, 9137, 8080, ...)
Slot 1: test stack       (hardcoded: +10000 offset)
Slot 2: on-demand        (gateway=28137, api=29137, db=25432, es=60051, ...)
Slot 3: on-demand        (gateway=38137, api=39137, db=35432, es=61051, ...)
Slot 4: on-demand        (gateway=48137, api=49137, db=45432, es=62051, ...)
Slot 5: on-demand        (gateway=58137, api=59137, db=55432, es=63051, ...)
```

Most services: `dev_port + (slot * 10000)`. Event store uses a separate range starting at 60051
(+1000 per slot) to avoid exceeding port 65535.

**Environment registry:**

A JSON file at `infra/environments.json` tracks active environments:

```json
{
  "environments": [
    {
      "name": "new-triggers",
      "branch": "feature/new-triggers",
      "slot": 2,
      "created_at": "2026-04-11T14:30:00Z",
      "ports": {
        "gateway": 28137,
        "api": 29137,
        "db": 25432,
        "event_store": 60051,
        "collector": 28080,
        "redis": 26379,
        "minio": 29000,
        "minio_console": 29001,
        "envoy": 28081
      }
    }
  ]
}
```

**Management (env_manager.py + just recipes):**

```bash
just env-up <branch>         # allocate slot, generate env file, start stack
just env-down <name>         # tear down stack, remove volumes, free slot
just env-list                # show running environments with ports and branches
just env-status <name>       # show details for one environment
just env-stop <name>         # pause (containers stopped, slot held)
just env-start <name>        # resume a paused environment
just env-logs <name>         # stream container logs
```

All commands support `--json` for agent consumption.

**How `env-up feature/new-triggers` works:**
1. Slugify branch name (`feature/new-triggers` -> `new-triggers`)
2. Allocate next free slot from registry
3. Compute ports from slot using deterministic formula
4. Write `.env.ondemand-{slug}` with port mappings + agent network name
5. `docker compose -f base -f ondemand --env-file .env.ondemand-{slug} -p syn-env-{slug} up -d --build`
6. Register in `infra/environments.json`
7. Print environment summary (URLs, ports, agent network)

### Phase 2: Environment Discovery (Implemented)

Agent-friendly discovery is built into `env_manager.py` via `--json` flags:

```bash
# List all environments as JSON
just env-list --json

# Get details for one environment as JSON
just env-status <name> --json
```

**JSON output includes all URLs and ports an agent needs:**

```json
{
  "name": "new-triggers",
  "branch": "feature/new-triggers",
  "slot": 2,
  "created_at": "2026-04-11T14:30:00Z",
  "url": "http://localhost:28137",
  "api_url": "http://localhost:28137/api/v1",
  "api_direct_url": "http://localhost:29137",
  "api_docs_url": "http://localhost:28137/api/v1/docs",
  "minio_console_url": "http://localhost:29001",
  "agent_network": "syn-env-new-triggers_agent-net",
  "ports": { "gateway": 28137, "api": 29137, "db": 25432, ... }
}
```

Agents call `just env-list --json`, parse the output, and target the right environment.
No HTTP discovery service needed - the CLI is the discovery mechanism.

**Future: HTTP discovery endpoint.** If agents need to discover environments from inside
Docker containers (where they can't call `just`), a lightweight HTTP endpoint reading
`infra/environments.json` can be added. ~50 LOC.

### Phase 3: CI Per-PR Environments (Ephemeral)

GitHub Actions workflow that spins up an environment for automated testing during PR checks. These are ephemeral - they exist only for the duration of the CI job.

```yaml
# .github/workflows/pr-environment.yml
on: pull_request

jobs:
  integration-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Start environment
        run: |
          docker compose \
            -f docker/docker-compose.yaml \
            -f docker/docker-compose.ondemand.yaml \
            -p pr-${{ github.event.number }} \
            up -d --build
        env:
          SYN_ENV_NAME: pr-${{ github.event.number }}
          SYN_ENV_PORT_API: 28000
          # ... other ports (no conflicts - one env per runner)
      - name: Wait for healthy
        run: # health check loop
      - name: Run integration tests
        run: # tests targeting localhost:28000
      - name: Tear down
        if: always()
        run: docker compose -p pr-${{ github.event.number }} down -v
```

No port conflicts because each CI runner hosts exactly one environment. No registry needed because the environment is destroyed at the end of the job.

### Phase 4 (Future): Persistent Preview Environments

Not in scope for this ADR. Would require hosting infrastructure (self-hosted runner on Mac Mini with Cloudflare Tunnel, or cloud VPS). Revisit when the team or testing needs outgrow ephemeral CI environments.

## Constraints

### Memory Budget

Measured baseline (2026-04-11):

| Stack | Memory |
|---|---|
| Dev (`syn-*`) | ~514 MB |
| Selfhost (`syn137-*`) | ~665 MB |
| Per on-demand environment (measured) | ~471 MB |

On the current 8 GB Docker allocation: 2-3 parallel environments max.
On a 48 GB Mac Mini: 5-8 parallel environments comfortably (leaving room for agentic workspaces).

### What's NOT Shared Between Environments

Each environment is fully isolated:
- Own database (no schema isolation tricks - separate TimescaleDB instance)
- Own event store
- Own Redis
- Own MinIO
- Own agent network

This is intentional. Full isolation means environments can't interfere with each other, and tearing one down has zero impact on others.

## Consequences

### Positive

- **DORA capability:** Any team member (human or agent) can spin up an environment on demand
- **Branch comparison:** Run main and a feature branch side-by-side, test both
- **Agent-friendly:** Discovery service gives agents a structured way to find and target environments
- **Minimal drift risk:** Single overlay file, all service definitions inherited from base compose
- **Ephemeral by default:** No volumes means no stale state, no cleanup burden

### Negative

- **Port management complexity:** Registry file adds state to manage (creation, cleanup, slot recycling)
- **Image build time:** Each environment builds its own images from the branch (mitigated by Docker layer caching)
- **Memory ceiling:** Each environment costs ~500-650 MB, limiting parallelism on smaller machines

### Neutral

- The existing test stack (`docker-compose.test.yaml`, port +10000) remains as-is. It serves a different purpose (deterministic test infrastructure) and is not replaced by on-demand environments.

## Key Files

- `docker/docker-compose.yaml` - Base compose (shared service definitions, docker-proxy network)
- `docker/docker-compose.ondemand.yaml` - On-demand overlay (parameterized ports, gateway, ephemeral)
- `infra/scripts/env_manager.py` - Environment manager (slot allocation, registry, compose lifecycle)
- `infra/environments.json` - Active environment registry (gitignored)
- `.env.ondemand-{name}` - Generated env files per environment (gitignored)

## Related

- ADR-005 - Development environments (original dev/test split)
- ADR-034 - Test infrastructure architecture (port offset strategy, DRY compose overlay structure)
- ADR-021 - Isolated workspace architecture (agent network isolation)
