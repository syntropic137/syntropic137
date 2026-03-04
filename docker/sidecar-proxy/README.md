# Sidecar Proxy for Secure Token Injection

This directory contains the Envoy sidecar proxy configuration for the Syn137 secure token architecture.

## Purpose

The sidecar proxy intercepts outbound requests from agent containers and:

1. **Injects authentication tokens** - Adds Bearer tokens to requests without exposing them to the container
2. **Enforces spend limits** - Validates budget before forwarding requests
3. **Logs all requests** - Creates audit trail for observability
4. **Rate limits** - Prevents runaway request patterns

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Pod / Container Group                                           │
│                                                                 │
│  ┌──────────────┐         ┌──────────────┐                     │
│  │    Agent     │ HTTP    │   Sidecar    │ HTTPS    External   │
│  │  Container   │────────▶│    Proxy     │────────▶   APIs     │
│  │              │         │   (Envoy)    │                     │
│  └──────────────┘         └──────────────┘                     │
│                                   │                             │
│                                   │                             │
│                          ┌────────▼────────┐                    │
│                          │ Token Vending   │                    │
│                          │    Service      │                    │
│                          └─────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration Files

- `envoy.yaml` - Main Envoy configuration
- `config.yaml` - Syn137-specific token injection configuration

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SYN_TOKEN_SERVICE_URL` | URL of token vending service | `http://localhost:8080` |
| `SYN_EXECUTION_ID` | Current execution ID | Required |
| `SYN_ALLOWED_HOSTS` | Comma-separated allowed hosts | See config |

## Allowed Hosts

By default, only these hosts are allowed:

- `api.anthropic.com` - Claude API
- `api.github.com` - GitHub API
- `raw.githubusercontent.com` - GitHub raw content

## Usage

### Kubernetes

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: agent-pod
spec:
  containers:
  - name: agent
    image: syn-workspace:latest
    env:
    - name: http_proxy
      value: "http://localhost:8081"
    - name: https_proxy
      value: "http://localhost:8081"
  - name: sidecar
    image: syn-sidecar:latest
    env:
    - name: SYN_EXECUTION_ID
      valueFrom:
        fieldRef:
          fieldPath: metadata.labels['execution-id']
```

### Docker Compose

```yaml
services:
  agent:
    image: syn-workspace:latest
    environment:
      - http_proxy=http://sidecar:8081
      - https_proxy=http://sidecar:8081
    depends_on:
      - sidecar

  sidecar:
    image: syn-sidecar:latest
    environment:
      - SYN_EXECUTION_ID=${EXECUTION_ID}
      - SYN_TOKEN_SERVICE_URL=http://token-service:8080
```

## Token Injection Flow

1. Agent makes request to `api.anthropic.com`
2. Request is intercepted by sidecar proxy
3. Proxy fetches token from Token Vending Service
4. Proxy injects `Authorization: Bearer <token>` header
5. Request is forwarded to upstream
6. Response is logged and returned to agent

## Spend Enforcement

Before forwarding requests to Claude API:

1. Proxy checks remaining budget with Spend Tracker
2. If budget exhausted, returns 429 with budget info
3. After response, records actual token usage

## See Also

- `docs/adrs/ADR-022-secure-token-architecture.md`
- `docs/deployment/claude-api-security.md`
- `packages/syn-tokens/` - Token Vending Service
