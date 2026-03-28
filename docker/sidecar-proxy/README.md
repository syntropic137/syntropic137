# Shared Envoy Proxy for Secure Credential Injection (ISS-43)

This directory contains the Envoy proxy configuration that injects API credentials into outbound requests from agent containers. Agents never see API keys.

## Architecture

```
Agent Container (agent-net only, no external egress)
  ANTHROPIC_BASE_URL=http://syn-envoy-proxy:8081
  HTTP_PROXY=http://syn-envoy-proxy:8081
  NO ANTHROPIC_API_KEY, NO CLAUDE_CODE_OAUTH_TOKEN
    │
    ▼
Shared Envoy Proxy (bridges agent-net + default network)
  ├─ ext_authz → Token Injector (reads keys from proxy's own env vars)
  │   ├─ api.anthropic.com → injects x-api-key or Authorization: Bearer
  │   ├─ api.github.com    → passthrough (agent uses setup-phase token)
  │   ├─ github.com         → passthrough (agent uses ~/.git-credentials)
  │   ├─ pypi.org           → passthrough (no injection)
  │   ├─ registry.npmjs.org → passthrough (no injection)
  │   └─ *                  → 403 Forbidden
  └─ Upstream (TLS to external APIs)
```

### Network Isolation

Agent containers are attached to the `agent-net` Docker network, which is internal (no external egress). The Envoy proxy is on both `agent-net` and the `default` network, acting as the sole gateway to external APIs.

```
┌──────────────────────────────────────────────────────────┐
│  agent-net (internal, no external access)                 │
│                                                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                  │
│  │ Agent 1 │  │ Agent 2 │  │ Agent N │                  │
│  └────┬────┘  └────┬────┘  └────┬────┘                  │
│       └────────────┼────────────┘                        │
│                    │                                      │
│            ┌───────▼────────┐                             │
│            │  envoy-proxy   │───── default network ──── Internet
│            │  (both nets)   │
│            └────────────────┘
└──────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `envoy.yaml` | Envoy configuration: listeners, virtual hosts, clusters, ext_authz |
| `Dockerfile` | Builds the Envoy proxy image (pure Envoy — no credential logic) |

The token injector is a separate service in `docker/token-injector/`.

## Environment Variables (on the proxy container)

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | Anthropic API key | One of API key or OAuth token |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code OAuth token (takes priority over API key) | One of API key or OAuth token |
| `SYN_EXECUTION_ID` | Execution ID for tracing headers | No (defaults to "shared") |

## Allowed Hosts

### With Credential Injection

| Host | Service | Header Injected |
|------|---------|----------------|
| `api.anthropic.com` | Claude API | `x-api-key` or `Authorization: Bearer` |

### Passthrough (No Injection)

GitHub credentials are provisioned during the setup phase (installation token
stored in `~/.git-credentials` and `~/.config/gh/hosts.yml`). The proxy routes
traffic but does not inject credentials.

| Host | Purpose |
|------|---------|
| `api.github.com` | GitHub API |
| `github.com` | Git HTTPS (clone/push) |
| `raw.githubusercontent.com` | GitHub raw content |
| `pypi.org` | Python packages |
| `files.pythonhosted.org` | Python package downloads |
| `registry.npmjs.org` | npm packages |

### Blocked

All other hosts return `403 Forbidden`.

## Usage

### Docker Compose (default)

The proxy starts automatically with the stack:

```bash
docker compose up
```

It is defined as the `envoy-proxy` service in `docker/docker-compose.yaml`.

### Verify Credential Injection

```bash
# Health check
curl http://localhost:9901/ready

# Test Anthropic credential injection (from inside agent-net)
docker run --rm --network agent-net curlimages/curl \
  curl -s -H "Host: api.anthropic.com" http://syn-envoy-proxy:8081/v1/messages

# Test blocking
docker run --rm --network agent-net curlimages/curl \
  curl -s -H "Host: attacker.com" http://syn-envoy-proxy:8081/
# → 403 Forbidden
```

### Security Smoke Test

```bash
# Start a workspace container on agent-net
docker run --rm -it --network agent-net ubuntu:22.04 bash

# Inside the container:
env | grep -i key           # → nothing (no API keys)
env | grep ANTHROPIC_BASE   # → http://syn-envoy-proxy:8081
curl https://evil.com       # → fails (no external network)
```

## Token Injection Flow

1. Agent makes request to `http://syn-envoy-proxy:8081` with `Host: api.anthropic.com`
2. Envoy matches the virtual host and calls the ext_authz filter
3. Token Injector looks up the host in its service registry
4. Token Injector returns the appropriate credential header
5. Envoy adds the header and forwards the request upstream over TLS
6. Response flows back to the agent

## Extending with New Services

Add services via the `SYN_PROXY_EXTRA_SERVICES` JSON env var on the proxy container:

```json
[
  {
    "service_name": "firecrawl",
    "hosts": ["api.firecrawl.dev"],
    "header_name": "Authorization",
    "header_template": "Bearer {value}",
    "env_var": "FIRECRAWL_API_KEY"
  }
]
```

Also add corresponding virtual host and cluster entries in `envoy.yaml`.

## Phase 2 (Future)

- **Per-execution credentials** — Redis credential store + source IP routing
- **`--network none` + Unix socket** — Maximum isolation on Linux
- **Fernet encryption** — Credentials at rest in Redis
- **Spend budget enforcement** — Token injector checks budget before allowing requests

## See Also

- `docs/adrs/ADR-022-secure-token-architecture.md`
- `packages/syn-shared/src/syn_shared/settings/credentials.py` — Service credential config
- `packages/syn-adapters/.../docker/shared_envoy_adapter.py` — SharedEnvoyAdapter
- `packages/syn-tokens/` — Token Vending Service
