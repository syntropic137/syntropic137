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
| Brute-force on Basic Auth | Password is 64 hex chars (256 bits entropy); a Cloudflare Rate Limiting rule bans clients that trip repeated 401s at the edge (primary control), and an origin-side `limit_req` (`auth` zone) on the dashboard root is the backstop. Both key on the real client IP recovered from `CF-Connecting-IP`. |
| Rate limits keyed to the wrong IP | The `cloudflared` sidecar proxies to `gateway:8081` over the Docker network, so nginx's peer is cloudflared's container IP, not the visitor. `set_real_ip_from` (private Docker ranges) + `real_ip_header CF-Connecting-IP` restore the true client so per-client limiting and logs are meaningful. Trusting RFC1918 is safe because 8081 is never host-published under the tunnel overlay. |
| Internal port / scheme leaked in redirects | `absolute_redirect off` + `port_in_redirect off` keep auto-generated redirects (e.g. `/api/v1` -> `/api/v1/`) relative, so the internal `:8081` port and `http://` scheme are never emitted in a `Location` header. |
| Basic credentials solicited over plaintext HTTP | Cloudflare "Always Use HTTPS" 301s http->https at the edge before the auth challenge; HSTS (`security-headers.conf`) covers repeat browser visits. |

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

## Edge Hardening (2026-08-28)

A black-box assessment of a live tunnel found the auth wall intact (every
application path returns 401; header-injection, path-traversal and verb-tampering
bypasses all failed) but surfaced four gaps, now closed:

1. **No real brute-force control.** The only rate limits were a 30 r/s DoS
   throttle on `/api/v1/`, and the credential-bearing dashboard root had none.
   The limits also keyed on the Cloudflare edge IP, not the visitor. Fix:
   recover the real client IP (`CF-Connecting-IP`), add an `auth`-zone
   `limit_req` backstop on the root, and add a Cloudflare Rate Limiting rule on
   401s as the primary control (dashboard step, see checklist below).
2. **`/health` was a prefix match** with `auth_basic off`, so anything under
   `/health*` skipped auth. Now an exact regex match on `/health` and `/healthz`.
3. **Redirect leak.** `/api/v1` and `/ws` 301'd to `http://…:8081/…`, exposing
   the internal port and downgrading the scheme. Fixed with relative redirects.
4. **HTTP did not redirect to HTTPS**, so Basic credentials could be solicited
   over plaintext. Fixed at the Cloudflare edge (dashboard step).

**Cloudflare dashboard steps (not in code):**
- SSL/TLS → Edge Certificates: "Always Use HTTPS" = On, "Automatic HTTPS Rewrites" = On.
- Security → Rate Limiting: rule matching path `/*` AND response status `401`,
  threshold ~10/min per client IP, mitigation block ~15 min.

---

## References

- `infra/docker/images/gateway/nginx.conf` — nginx config implementing both server blocks
- `infra/docker/images/gateway/rate-limit.conf` — http-level real-client-IP recovery and rate-limit zones
- `infra/docker/images/gateway/docker-entrypoint.sh` — generates auth + shared locations (health match, root backstop, relative redirects)
- `infra/cloudflare/tunnel-config.yaml.example` — tunnel config template (routes to port 8081)
- `infra/.env.example` — `SYN_API_PASSWORD` documentation
- ADR-022 — future real authentication design
