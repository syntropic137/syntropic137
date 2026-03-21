# Security Practices

This document describes the supply chain and operational security controls in place for Syntropic137. It follows the internal supply-chain hardening playbook and is updated as controls are added or changed.

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
- `apps/syn-dashboard-ui/package-lock.json` — Dashboard
- `apps/syn-pulse-ui/pnpm-lock.yaml` — Pulse UI
- `packages/openclaw-plugin/package-lock.json` — OpenClaw plugin

**Rollout:** OSV runs in warn mode (`continue-on-error: true`) until a clean baseline is established, then switches to blocking. See `TODO(#259)` in `ci.yml`.

### npm/pnpm install hygiene

`--ignore-scripts` is applied to all package installs in CI to block `postinstall` hooks — the primary npm supply chain attack vector (event-stream, ua-parser-js style). Applied per-project:

- **ui-feedback-react** (submodule, pnpm): `pnpm install --ignore-scripts`
- **syn-dashboard-ui** (npm): `npm ci --ignore-scripts` — Vite 7.x sources esbuild via optional platform packages, so no binary restore is needed
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

## Planned Controls (not yet implemented)

- [ ] Pre-commit secret gate (`detect-secrets` or `gitleaks`) — ISS-259
- [x] `dependency-review-action` — blocks newly added CVE-laden or script-running packages on PRs
- [ ] Dependabot for Actions + npm — ISS-259
- [ ] OSV Scanner switched to blocking mode (after baseline) — ISS-259 `TODO(#259)`
- [ ] Topology auto-snapshot on commit — ISS-260
- [ ] Sigstore/cosign artifact signing — post-launch
- [ ] OpenSSF Scorecard integration — post-launch
