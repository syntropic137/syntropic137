# AppArmor on the Docker host (Codex workspaces)

Issue #1398. Applies to Linux hosts whose Docker daemon enforces AppArmor:
`docker info --format '{{json .SecurityOptions}}'` contains `name=apparmor`
(Ubuntu 24.04, most Debian/Ubuntu servers). macOS and Docker Desktop are not
affected.

## Why

Codex sandboxes its own tool calls with bubblewrap. Docker's `docker-default`
AppArmor profile contains `deny mount,`, so bubblewrap fails with
`bwrap: Failed to make / slave: Permission denied`. agentic-workspace (AW #2)
therefore runs images that declare Codex (image label
`agentic.codex_cli_version`) with the seccomp profile `codex-sandbox.json` and
the AppArmor profile `agentic-codex-sandbox`: docker-default with `deny mount,`
replaced by exactly the mounts bubblewrap performs, plus explicit denials. No
capabilities are added and `apparmor=unconfined` is never used. Provenance and
the full rule table:
`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/apparmor/README.md`.

The profile must be loaded into the kernel of the host that runs the Docker
daemon. The containerized API cannot load it.

## Setup (once per host)

```bash
just apparmor-setup          # install to /etc/apparmor.d + apparmor_parser -r (sudo)
just apparmor-setup --check  # exit 1 if needed but not loaded and persisted
```

`infra/scripts/apparmor-setup.sh` installs the profile shipped by the pinned
AW submodule to `/etc/apparmor.d/agentic-codex-sandbox`, so it loads at every
boot, and loads it now with `apparmor_parser -r`. It skips hosts without
AppArmor and treats a failing `docker info` as an error, never as "no
AppArmor". `just selfhost-up` runs it from `_selfhost-preflight`, and it
re-installs when an AW bump changes the profile.

Without a repository checkout (npx setup), copy the profile out of the
running API image:

```bash
docker exec syn137-api python -c \
  "from agentic_isolation import codex_sandbox_apparmor_profile_path as p; print(p().read_text(), end='')" \
  | sudo tee /etc/apparmor.d/agentic-codex-sandbox >/dev/null
sudo apparmor_parser -r /etc/apparmor.d/agentic-codex-sandbox
```

## Failure mapping

agentic_isolation fails closed. The workspace backend
(`packages/syn-adapters/src/syn_adapters/workspace_backends/host_security.py`)
maps each refusal to a typed `WorkspaceProvisionError` with a stable `reason`:

| agentic_isolation error | Syntropic137 error | `reason` |
|---|---|---|
| `AppArmorProfileNotLoadedError` | `AppArmorProfileMissingError` (carries `profile`, `remedy`) | `apparmor_profile_not_loaded` |
| `CodexSandboxPolicyError` | `CodexSandboxPolicyConflictError` | `codex_sandbox_policy_conflict` |
| `DockerDetectionError` | `DockerHostDetectionError` | `docker_detection_failed` |

None of these is retried: each needs an operator action.
