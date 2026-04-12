# ADR-059: nginx Gateway Two-Port Authentication Model

**Status:** Accepted  
**Date:** 2026-04-09  
**Context:** Self-hosted deployments with Cloudflare Tunnel external access

---

## Context

Self-hosted Syntropic137 runs behind an nginx reverse proxy (`gateway` service). Two distinct consumers exist:

1. **Docker-internal services** — health checks, inter-service calls that run over the Docker bridge network and must never be blocked by authentication.
2. **External traffic** — requests entering via Cloudflare Tunnel from the public internet that require authentication.

A single-port nginx config forces a choice: unauthenticated (breaks security) or authenticated (breaks internal health checks). This ADR documents the two-port design that satisfies both.

---

## Decision

nginx exposes two server blocks on separate ports with different authentication policies:

| Port | Authentication | Consumers | Host port |
|------|---------------|-----------|-----------|
| 80 | None | Docker health checks, internal service calls | — (not published) |
| 8081 | HTTP Basic Auth (when `SYN_API_PASSWORD` set) | Cloudflare Tunnel, any external access | — (not published) |

Host port 8137 → container port 80 (unauthenticated). This is the **local developer access** port, bound to `127.0.0.1` only, never reachable from the internet.

### Port 80 — unauthenticated, loopback-only

Used by:
- Docker Compose health checks (`GET /health`)
- Internal service-to-service traffic over the `default` Docker network
- Local developer access via `http://localhost:8137`

This port is intentionally not published to external interfaces. It relies on Docker network isolation as its security boundary.

### Port 8081 — basic auth required

Used by:
- **Cloudflare Tunnel** — tunnel config MUST reference `http://gateway:8081`, not `localhost:8137`
- Any other reverse proxy or external access point

Basic auth is enforced when `SYN_API_PASSWORD` is non-empty. An empty password disables auth entirely — the setup wizard generates a strong random password automatically and blocks tunnel activation until one is present.

### `SYN_API_PASSWORD` lifecycle

- **Generated**: 64-char hex (~256 bits of entropy), automatically during setup via `crypto.randomBytes(32).toString("hex")` in the NPX wizard (`npx @syntropic137/setup init`)
- **Stored**: `~/.syntropic137/.env` with mode `0600`
- **Rotated**: `npx @syntropic137/setup credentials rotate` — generates new password, updates `.env`, restarts stack
- **Never printed**: Password is never written to terminal output. Retrieval commands are shown instead.

### Cloudflare Tunnel routing requirement

```yaml
# CORRECT — routes to auth-guarded port
- hostname: syn.yourdomain.com
  service: http://gateway:8081

# WRONG — bypasses authentication
- hostname: syn.yourdomain.com
  service: http://localhost:8137
```

The tunnel connects inside the Docker network and can reach `gateway:8081` directly. Routing to `localhost:8137` (or any port 80 path) bypasses the auth gate entirely.

---

## Threat Model

| Threat | Mitigation |
|--------|-----------|
| Unauthenticated internet access to API | Port 8081 requires Basic Auth; tunnel config enforces port 8081 |
| Empty/default password on fresh install | Setup wizard generates password during init; tunnel blocked without it |
| Password visible in process list or logs | Password lives only in `~/.syntropic137/.env` (mode 0600); never echoed |
| Docker health checks blocked by auth | Port 80 is unauthenticated; health checks use internal Docker network |
| Port 8137 exposed to internet | Published as `127.0.0.1:8137:80` — loopback bind, not reachable externally |
| Brute-force on Basic Auth | Username is `admin` (known); password is 64 hex chars (256 bits entropy) |

---

## What This Is Not

This is not the final authentication design. Basic auth over HTTPS (via Cloudflare Tunnel TLS termination) is acceptable for self-hosted v1. A proper auth layer (JWT sessions, OAuth, role-based access) is planned in ADR-022 and will replace this when implemented.

The stub `auth.py` / `AuthContext` placeholder (previously in `apps/syn-api/src/syn_api/auth.py`) was removed as part of this work — it gave a false impression of auth enforcement at the application layer. nginx is the real gate.

---

## Consequences

**Good:**
- Fresh installs are secure by default — password auto-generated, tunnel blocked without it
- Docker health checks work without authentication
- Local developer access (`localhost:8137`) is convenient and safe (loopback-only)
- Rotation is a single command, handled end-to-end by the setup wizard

**Bad / Accepted tradeoffs:**
- Basic auth username is hardcoded as `admin` — slightly reduces brute-force resistance but simplifies v1 UX
- Password lives on disk in plaintext (chmod 600) — same as all other secrets in `.env`; acceptable for v1
- Between `writeEnv` and `docker start` during rotation (~10s), the running stack still accepts the old password — unavoidable with this architecture
- Swagger UI (`/docs`) is accessible to anyone with the Basic Auth credentials — no per-route authorization

---

## References

- `infra/docker/images/gateway/nginx.conf` — nginx config implementing both server blocks
- `infra/cloudflare/tunnel-config.yaml.example` — tunnel config template (routes to port 8081)
- `infra/.env.example` — `SYN_API_PASSWORD` documentation
- ADR-022 — future real authentication design
