# ADR-073: Sealed Pinned Workspaces for Evals

- **Status**: Proposed (decisions 1, 2 and 4 implemented in #1760; decision 3, egress, and the Docker probe test are not)
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

### 3. Egress for the agent's phase excludes GitHub (NOT implemented)

The allowlist is not where this can be enforced today. `agent-net` is
deliberately not an internal network (`docker/docker-compose.yaml`: "agents
need egress for git operations"), so a workspace container reaches the
internet directly and the Envoy allowlist governs only what is routed through
Envoy. Dropping `api.github.com` from `SidecarConfig.allowed_hosts` for a
pinned phase would therefore change nothing an agent could not route around.

What closing it needs, in order:

1. A pinned phase's container on a network with no direct egress (an
   `internal: true` network, or a per-container egress policy set by the
   isolation provider in agentic-workspace), with the clone done before the
   agent starts, as it already is.
2. Its proxy allowlist without `github.com`, `api.github.com` and
   `raw.githubusercontent.com`, and WITH the package indexes the gates need
   (pypi, the npm registry) - none of which the default allowlist contains -
   or the workspace prewarmed so no index is needed.
3. A Docker probe test in a real pinned workspace: `git log --all`,
   `git fetch origin`, `gh pr view <fix pr>` and `curl api.github.com` all
   fail to reveal the fix, and the pinned files are present.

Until then a sealed workspace has no route to the fix through git, gh or a
credential, but anonymous HTTPS to GitHub's public API still works for a
public repository.

### 4. Declared per phase, as `isolation: pinned`

`PhaseIsolation` (`_shared/phase_isolation.py`): `standard` or `pinned`.
Declared on the phase, beside `clone_repos`, because like it it decides what
the workspace contains, and because one workflow can hold a sealed phase and
a phase that needs GitHub. The eval workflow's implement phase declares it.
It travels the same hops as `delivers_repo_changes`: YAML -> `PhaseDefinition`
-> `WorkflowTemplateCreated` -> `ExecutablePhase` ->
`WorkspaceProvisionHandler` -> `SetupPhaseSecrets.sealed_at_pin`, and the API
create path, read models and YAML export carry it too.

A pinned phase is refused at authoring unless it declares
`delivers_repo_changes: false` and clones: it could never push, and a phase
with no clone has nothing to seal. `ManagedWorkspace` records no credential
source for a sealed workspace, so credential renewal (#1393) has nothing to
re-install.

## Consequences

- With decisions 1, 2 and 4 alone, an agent can still reach GitHub
  anonymously over the network for a public repository: the seal removes the
  history, the URL and the credential, not the route. Decision 3 closes that.
  Until it lands, a PASS still needs the tool trace read as the README says.
- Sealing is irreversible inside the workspace. A sealed phase cannot push,
  which is correct for the eval workflow (`delivers_repo_changes: false`) and
  is why sealing is opt-in rather than tied to having a pin.
