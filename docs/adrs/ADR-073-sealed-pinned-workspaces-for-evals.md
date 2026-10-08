# ADR-073: Sealed Pinned Workspaces for Evals

- **Status**: Proposed (workspace mechanism landed in #1760; workflow declaration, egress and renewal pending)
- **Date**: 2026-10-08
- **Issue**: #1725 (research, pitfall #2), #1747 (implementer evals, which documented leakage as unsolved)
- **Related**: ADR-024 (setup-phase secrets), ADR-058 (multi-repo credentials), #1458 (pinned checkout), #725 (credential lifecycle)

## Context

The implementer-seed eval suite provisions a workspace at the first parent of
a real merged fix and scores the agent's patch against the fix's own tests. A
PASS only measures the agent if the agent could not read the fix. Today it
can, through three independent channels (`evals/implementer-seed-v1/README.md`):

1. **Local objects.** Provisioning is a full `git clone`; the pin is a
   detached checkout on top. `git log --all`, any tag, any branch, and
   `git show <fix sha>` all reach the fix offline.
2. **Remote fetch.** `~/.git-credentials` and gh's `hosts.yml` are kept after
   setup on purpose, so a `git fetch` or `gh pr view` works.
3. **Network.** The Envoy egress allowlist is service-wide and includes
   `api.github.com`.

Closing any one channel leaves the other two, so the decision has three parts.

## Decision

### 1. Seal the repository after the pin is verified, rather than shallow-clone

The pin is still cloned in full and verified by the #1458 rule (a branch or
a tag of origin must reach it). Only then is each repository, and each
submodule, *sealed*: every remote, ref, tag, reflog, `FETCH_HEAD` and
`ORIG_HEAD` is removed and `git gc --prune=now` drops every object HEAD no
longer reaches. One ref, `refs/remotes/pinned/<sha>`, is restored so the
unpushed-work guard and branch observation do not read the pin's history as
the phase's own work.

Considered and rejected: `git init` + `fetch --depth=1 origin <sha>`. It
fetches by id, which #1458 deliberately refuses (GitHub serves commits no
ref retains, so two phases of one run could disagree about what they ran on),
and it would need a second reachability rule and a second submodule path.
Sealing composes with the existing path instead of forking it, and costs one
full clone of bandwidth per eval workspace.

Implemented by `pinned_checkout.append_seal_at_pin`, selected by
`SetupPhaseSecrets.sealed_at_pin`.

### 2. A sealed workspace holds no GitHub credential after setup

The clone uses the installation token as usual; the setup script then deletes
`~/.git-credentials` and the credential helper. gh is never given a token. A
sealed workspace refuses to be built with an unpinned repository, a skipped
clone, or a continued branch: sealing at a default branch's head seals
nothing.

### 3. Egress for the agent's phase excludes GitHub (pending)

The phase allowlist must drop `github.com`, `api.github.com` and
`raw.githubusercontent.com` once setup is done, while package indexes stay
reachable (or are prewarmed) so gates can run. The default allowlist contains
no package index today, so that must be added explicitly for these phases.

### 4. Declared per workflow (pending)

A workflow opts in (`isolation: pinned`); the eval workflows declare it. The
value flows from the YAML through the template and execution aggregates to
`WorkspaceProvisionHandler`, exactly as `delivers_repo_changes` does, and the
credential renewal path (`git_credential_renewal.py`) must not re-install a
credential into a sealed workspace.

## Consequences

- With parts 1 and 2 alone, an agent can still reach GitHub anonymously over
  the network for a public repository: the seal removes the URL and the
  credential, not the route. Part 3 closes that. Until it lands, a PASS still
  needs the tool trace read as the README says.
- Sealing is irreversible inside the workspace. A sealed phase cannot push,
  which is correct for the eval workflow (`delivers_repo_changes: false`) and
  is why sealing is opt-in rather than tied to having a pin.
