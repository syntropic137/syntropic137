# Security Practices

This document describes the supply chain and operational security controls in place for Syntropic137. It follows the internal supply-chain hardening playbook and is updated as controls are added or changed.

> **Vulnerability reporting:** See [SECURITY.md](../SECURITY.md) at the repo root for the responsible disclosure policy and response timeline.

## Supply Chain Hardening

### GitHub Actions — SHA pinning

All third-party Actions in `.github/workflows/` are pinned to **commit SHAs**, not mutable version tags. This protects against tag-repointing attacks (e.g., XZ-utils style), where a compromised maintainer silently moves a tag to a malicious commit.

```yaml
# Safe — immutable
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4

# Unsafe — tag can be repointed without any diff in this repo
- uses: actions/checkout@v4
```

When updating an Action version: look up the new release SHA via `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`, replace the SHA, and update the comment.

### Workflow permissions — least privilege

All workflows declare `permissions: contents: read` at the top level. Jobs that need additional access (e.g., writing to releases or packages) must declare it explicitly at the job level. This limits blast radius if a step is compromised.

### Dependency vulnerability scanning — OSV Scanner

CI runs [Google's OSV Scanner](https://github.com/google/osv-scanner) on every push and PR. It checks all lock files against the [OSV database](https://osv.dev) (covers CVEs, GitHub Security Advisories, and ecosystem advisories for PyPI, npm, crates.io, and more).

**Lock files scanned:**
- `uv.lock` — Python workspace
- `pnpm-lock.yaml` — Node.js workspace (root, shared across all pnpm apps)

**Rollout:** OSV runs in warn mode (`continue-on-error: true`) until a clean baseline is established, then switches to blocking. See `TODO(#259)` in `ci.yml`.

### npm/pnpm install hygiene

`--ignore-scripts` is applied to all package installs in CI to block `postinstall` hooks — the primary npm supply chain attack vector (event-stream, ua-parser-js style). Applied per-project:

- **ui-feedback-react** (submodule, pnpm): `pnpm install --ignore-scripts`
- **syn-dashboard-ui** (pnpm): `pnpm install --frozen-lockfile --ignore-scripts` — shares the root workspace lockfile
- **syn-docs** (pnpm): `pnpm.onlyBuiltDependencies` allowlist in `package.json` restricts install scripts to explicitly reviewed packages (esbuild, sharp, @img/\*)

The `onlyBuiltDependencies` approach for pnpm is preferred over blanket `--ignore-scripts` when some packages legitimately require build steps. The allowlist is code-reviewed and auditable.

### CODEOWNERS

`.github/CODEOWNERS` requires maintainer approval for changes to:
- `.github/` — CI/CD workflows (highest risk: arbitrary code execution)
- `docker/`, `infra/` — container and deployment configuration
- `packages/syn-shared/` — env constants and shared credentials config
- `.gitmodules` — submodule pin changes must be intentional

### Private key and credential gitignore rules

`.gitignore` excludes common private key and certificate file patterns (`*.pem`, `*.key`, `*.p12`, `id_rsa`, `id_ed25519`, etc.) to reduce the risk of accidentally committing credentials.

---

## Credential Management

Secrets are managed via **1Password** and injected at runtime through environment variables. They are never hardcoded or committed.

- API keys and tokens live in 1Password vaults
- `.op-save-secrets.sh` (gitignored) handles local secret injection
- CI secrets are stored as GitHub Actions secrets scoped to this repository

**Rotation:** All tokens should have an expiry date. Rotate on any suspected exposure.

---

## Incident Response

If a secret is accidentally committed:

1. **Immediately revoke** the exposed credential — do not wait
2. Rotate and issue a new credential
3. If the commit is recent and unpushed: `git reset` and force-push (coordinate with team)
4. If already pushed: open an incident record, assess git history rewrite vs. accepting the exposure with rotation
5. Check git log and GitHub audit log for any unauthorized access during the exposure window

---

## Lock File Discipline

All lock files (`uv.lock`, `pnpm-lock.yaml`) are committed to the repository and enforced in CI:

- **Python**: `uv sync --all-extras` (add `--frozen` to enforce lock — planned)
- **pnpm**: `pnpm install --frozen-lockfile --ignore-scripts` — uses exact versions from root `pnpm-lock.yaml`, shared across all workspace apps

All Node.js packages use pnpm with a single root lockfile (`shared-workspace-lockfile` defaults to `true`). Per-app lockfiles are not used — the root lockfile is authoritative.

---

## CI/CD Security Scanning

### SAST — Static Application Security Testing

Not yet implemented. Planned controls:

- **CodeQL** — GitHub-native SAST, free for public repos. Detects SQL injection, XSS,
  path traversal, insecure deserialization across Python and JavaScript/TypeScript.
- **Bandit** — Python-specific SAST for common security anti-patterns.

### Container Scanning

Not yet implemented. OSV Scanner covers app-layer dependencies (Python, npm, etc.) via
lock files. For OS-layer CVEs in base images, we will use **Docker Scout**.

**Why Docker Scout:** We already trust Docker for the container runtime — Scout is
maintained by the same team, keeping the trust chain short rather than introducing a new
third-party security dependency. Trivy (aquasecurity) is commonly cited but aquasecurity
has experienced multiple security incidents; a compromised scanner is itself a supply
chain risk.

### Secret Scanning

Not yet implemented as a blocking gate. Planned controls:

- **gitleaks** pre-commit hook — blocks commits containing secrets before they reach
  git history (much cheaper than incident response after accidental push)
- **gitleaks** in CI — scans full git history on push, catches anything that slipped
  past the pre-commit hook
- **GitHub secret scanning** — enable in Settings > Security > Secret scanning

---

## Docker Runtime Security

Agent containers run in isolated Docker environments with multiple layers of defense. For the full GitHub App integration model, see [GitHub App Security Model](./deployment/github-app-security.md).

### Secret isolation — Docker secrets (tmpfs)

Sensitive credentials (database passwords, Redis passwords, MinIO passwords, GitHub App PEM) are mounted as **Docker secrets** — stored on tmpfs (RAM-only) at `/run/secrets/`. They are:
- Not visible in `docker inspect`
- Not in the process environment (`/proc/1/environ`)
- Not in `docker compose config` output
- Never written to the container filesystem

### Agent credential injection — Envoy ext_authz proxy

Agent containers never hold real API keys. Instead:
1. Agents are started with `ANTHROPIC_API_KEY=proxy-managed` (a placeholder)
2. All Anthropic traffic routes through a shared Envoy proxy (`ANTHROPIC_BASE_URL=http://envoy-proxy:8081`)
3. The **token injector** (ext_authz HTTP service) intercepts requests and replaces the placeholder with the real credential
4. Direct calls to `api.anthropic.com` from agents fail — only the proxy path works

GitHub API access uses a different pattern: short-lived installation tokens (1-hour TTL) are baked into `~/.git-credentials` during a setup phase, then the environment is cleared. The token injector treats GitHub hosts as passthrough.

### Container hardening

All containers in the selfhost compose file use:
- `read_only: true` — immutable root filesystem
- `no-new-privileges: true` — prevents privilege escalation
- `cap_drop: ALL` — drops all Linux capabilities (re-adds only what's needed)
- Resource limits (memory and CPU) — prevents runaway containers
- JSON file logging with rotation — prevents disk exhaustion

### Network segmentation

- **syn-internal**: Control plane services (API, database, event store, collector)
- **syn-proxy**: Docker socket proxy (API ↔ socket proxy only, `internal: true`)
- **agent-net**: Agent containers + Envoy proxy. Not fully internal (agents need git egress), but API key security enforced via proxy routing.

### Docker socket proxy

The API container does not mount `/var/run/docker.sock` directly. Instead, it connects through a **Docker socket proxy** (tecnativa/docker-socket-proxy) that allowlists only the operations needed for workspace management (container create/start/stop/exec). This limits blast radius if the API container is compromised.

---

## Planned Controls (not yet implemented)

- [ ] Pre-commit secret gate (`gitleaks`) — ISS-259
- [x] `dependency-review-action` — added; warn-only until repo goes public (requires GitHub Advanced Security, free for public repos)
- [ ] Dependabot for Actions + npm — ISS-259
- [ ] OSV Scanner switched to blocking mode (after baseline) — ISS-259 `TODO(#259)`
- [ ] CodeQL SAST — post-launch
- [ ] Container scanning (Docker Scout) — post-launch
- [ ] gitleaks CI secret scanning — ISS-259
- [ ] `uv sync --frozen` enforced in CI
- [ ] Topology auto-snapshot on commit — ISS-260
- [ ] Sigstore/cosign artifact signing — post-launch
- [ ] OpenSSF Scorecard integration — post-launch
- [ ] SBOM generation (syft/cyclonedx) — post-launch
