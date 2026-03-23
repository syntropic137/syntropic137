# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest (`main`) | ✅ Active |
| Beta releases | ✅ Active |
| Older releases | ❌ No backports |

We support only the latest release. Security fixes are shipped as a new release — we do
not backport to older versions.

---

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**
Public disclosure before a fix is available gives attackers a head start.

### How to Report

**Email:** security@syntropic137.dev _(or file a [GitHub private security advisory](https://github.com/syntropic137/syntropic137/security/advisories/new))_

Please include:
- A description of the vulnerability and its impact
- Steps to reproduce (proof of concept if possible)
- Affected component(s) and version(s)
- Any suggested mitigations you've identified

We treat all reports as confidential. You will not be asked to sign an NDA.

### Response Timeline

| Milestone | Target |
|-----------|--------|
| Initial acknowledgement | 48 hours |
| Severity assessment | 5 business days |
| Fix or mitigation | Depends on severity (see below) |
| Public disclosure | Coordinated with reporter |

**Severity targets:**

| Severity | Fix Target |
|----------|------------|
| Critical (CVSS 9.0+) | 7 days |
| High (CVSS 7.0–8.9) | 14 days |
| Medium (CVSS 4.0–6.9) | 30 days |
| Low (CVSS < 4.0) | 90 days or next release |

If we need more time than the target, we will communicate this to the reporter with an
updated timeline and interim mitigation if possible.

### What to Expect

1. We confirm receipt within 48 hours
2. We assess severity and scope within 5 business days
3. We develop and test a fix
4. We notify you before public disclosure so you can review the fix and coordinate timing
5. We credit you in the release notes and security advisory (unless you prefer anonymity)

---

## Disclosure Policy

We follow **coordinated disclosure**: reporter and maintainers agree on a disclosure date
after a fix is available, typically 7–14 days after the fix ships. We respect reporter
preference for earlier or later disclosure within reason.

We do not pursue legal action against researchers who discover and responsibly report
vulnerabilities in good faith.

---

## Security Controls

The following controls are in place. See [docs/security-practices.md](docs/security-practices.md)
for implementation details.

### Supply Chain

- **GitHub Actions SHA-pinned** — all third-party Actions are pinned to immutable commit
  SHAs, not mutable version tags. Defends against XZ-utils style tag-repointing attacks.
- **`--ignore-scripts` / `onlyBuiltDependencies`** — npm and pnpm installs block
  postinstall hook execution in CI. Defends against event-stream style attacks.
- **Lock file enforcement** — `npm ci` and `uv sync --frozen` ensure CI installs exact
  dependency versions from committed lock files, not fresh resolutions.
- **OSV Scanner** — scans all lock files (Python, npm, pnpm) against the OSV vulnerability
  database on every push and PR.
- **dependency-review-action** — blocks PRs that introduce newly vulnerable packages.

### CI/CD

- **Least-privilege workflow permissions** — all workflows default to `contents: read`.
  Jobs requiring write access declare it explicitly at the job level.
- **CODEOWNERS** — `.github/`, `docker/`, `infra/`, and `.gitmodules` require maintainer
  approval on all changes.

### Secrets

- **No hardcoded credentials** — secrets are injected at runtime via environment variables
  from 1Password or GitHub Actions secrets.
- **`.gitignore` credential patterns** — key and certificate file extensions are gitignored.
- **Immediate revocation** — any accidentally committed secret is revoked before any other
  action is taken.

### Code Quality

- **Static analysis** — Pyright (strict) on all Python code; Ruff for lint.
- **Type safety** — no `Any` without justification; all public interfaces fully typed.

---

## Incident Response

If a secret is accidentally committed:

1. **Immediately revoke** the exposed credential — do not wait, do not clean up git first
2. Rotate and issue a new credential
3. If unpushed: `git reset` and amend (coordinate with team before force-push)
4. If already pushed: open an incident record, assess history rewrite vs. accepting
   exposure with rotation
5. Check GitHub audit log and any service logs for unauthorized access during the window
6. File a post-mortem and add the file pattern to `.gitignore` to prevent recurrence

---

## Planned Controls

- [ ] Pre-commit secret gate (gitleaks or detect-secrets)
- [ ] Dependabot for Actions + npm
- [ ] CodeQL SAST
- [ ] Container scanning (Docker Scout)
- [ ] OpenSSF Scorecard integration
- [ ] Sigstore/cosign artifact signing
- [ ] SBOM generation
