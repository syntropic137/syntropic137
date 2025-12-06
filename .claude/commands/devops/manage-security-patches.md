---
description: Manage security patches with 48-hour cooldown validation and safe rollback
argument-hint: [list|validate|apply|rollback] [package-name]
model: sonnet
allowed-tools: Read, Grep, Glob, Bash
---

# Manage Security Patches

Automated workflow for reviewing, validating, and applying security patches from Dependabot and other sources with supply chain protection.

## Variables

ACTION: $ARGUMENTS[0] (list|validate|apply|rollback)
PACKAGE: $ARGUMENTS[1] (optional package name)

## Security Policy

**48-Hour Cooldown Rule:** Never apply a package version released within the last 48 hours unless it's a critical security fix with a CVE.

This protects against:
- Supply chain attacks (compromised releases)
- Accidental breaking changes
- Quickly-reverted bad releases

## Instructions

Based on ACTION, execute the appropriate workflow:

### Action: `list` - List Pending Updates

```bash
# Check dependabot PRs
gh pr list --label "dependencies" --json number,title,createdAt

# Check security alerts
gh api repos/{owner}/{repo}/dependabot/alerts --jq '.[] | {package: .dependency.package.name, severity: .severity, state: .state}'

# For Rust: check outdated dependencies
cargo outdated --root-deps-only
```

### Action: `validate` - Validate a Specific Update

For the specified package, verify:

1. **Release Date Check (48hr cooldown)**
   ```bash
   # For Rust crates - check crates.io release date
   cargo search <crate-name> --limit 1
   ```

2. **Changelog Review**
   - Check for breaking changes
   - Review security advisories
   - Note MSRV requirements

3. **Compatibility Check**
   ```bash
   cargo update -p <package>
   cargo check
   cargo test
   cargo clippy -- -D warnings
   ```

### Action: `apply` - Apply Updates

Group updates by risk level:

| Risk | Criteria | Strategy |
|------|----------|----------|
| 🟢 Low | Patch versions, no breaking changes | Batch together |
| 🟡 Medium | Minor versions, documented changes | Individual commits |
| 🟠 High | Major versions, API changes | Separate PR with migration |

**Workflow:**
```bash
# Create branch
git checkout main && git pull origin main
git checkout -b security/patch-$(date +%Y%m%d)

# Apply updates
cargo update -p <package1> -p <package2>

# Run QA
just qa  # Or project-specific QA command

# Commit
git add Cargo.toml Cargo.lock
git commit -m "security(deps): apply security patches

Updates:
- package1: X.X.X → Y.Y.Y
- package2: X.X.X → Y.Y.Y

All versions verified with 48-hour cooldown from release."

# Create PR
git push -u origin security/patch-$(date +%Y%m%d)
gh pr create --title "security(deps): apply security patches" --label "security,dependencies"
```

### Action: `rollback` - Safe Rollback

**⚠️ CRITICAL: Use `git revert`, NOT `git reset --hard` + force push!**

Force pushing rewrites history and breaks:
- Other developers who already pulled
- CI/CD pipelines
- Deployment servers

**Safe Rollback Procedure:**
```bash
# Find the commit to revert
git log --oneline -10

# Create a revert commit (preserves history)
git revert <commit-sha>

# Push normally (no force required)
git push origin main
```

**Multiple Commits:**
```bash
git revert --no-commit <oldest-sha>^..<newest-sha>
git commit -m "revert: rollback security patches due to <reason>

Reverts commits <sha1>, <sha2>
Reason: <explanation>"
git push origin main
```

## CVE Response Protocol

For critical vulnerabilities (CVSSv3 ≥ 9.0):

### Immediate Assessment (< 1 hour)
- Verify vulnerability affects our usage
- Check if exploit exists in the wild

### Expedited Patch (< 4 hours)
- Apply patch even if < 48 hours old
- Document exception in commit message:

```bash
git commit -m "security(deps): CRITICAL - patch CVE-XXXX-YYYY

⚠️ EXPEDITED: Applied within 48hr cooldown due to critical severity

- package: X.X.X → Y.Y.Y
- CVSSv3: 9.8 (Critical)
- Affected: <vulnerability description>

Reference: https://nvd.nist.gov/vuln/detail/CVE-XXXX-YYYY"
```

## Security Checklist

Before applying any patch:

- [ ] Package version is > 48 hours old (or has critical CVE)
- [ ] Changelog reviewed for breaking changes
- [ ] MSRV requirements checked
- [ ] Local tests pass
- [ ] CI pipeline passes
- [ ] No new vulnerabilities introduced

## Report Format

After completing a security patch cycle:

```markdown
## Security Patch Report - YYYY-MM-DD

### Updates Applied

| Package | From | To | Risk | CVE | Release Age |
|---------|------|-----|------|-----|-------------|
| pkg1 | 1.0.0 | 1.0.1 | 🟢 | N/A | 2 weeks |

### Skipped Updates (Cooldown)

| Package | Version | Release Date | Eligible Date |
|---------|---------|--------------|---------------|
| pkg2 | 3.0.0 | YYYY-MM-DD | YYYY-MM-DD |

### Rollback Plan

If issues discovered:
git revert <commit-sha>
git push origin main
```

## Examples

### List all pending updates
```
/manage-security-patches list
```

### Validate a specific package
```
/manage-security-patches validate jsonschema
```

### Apply all validated patches
```
/manage-security-patches apply
```

### Rollback a bad patch
```
/manage-security-patches rollback abc1234
```
