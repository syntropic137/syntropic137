# E2B remote workspaces (experimental, off by default)

Syntropic137 can run workspaces as [E2B](https://e2b.dev) cloud sandboxes
instead of local Docker containers (#1915, epic #1612). The support ships
**dark**: it is off unless you turn it on, and with it off nothing changes.

The provider itself (`E2BWorkspaceProvider`) lives in agentic-workspace.
Syntropic137 selects it, configures it and wires it behind the same isolation
port as Docker, so the rest of the system does not know which backend ran.

## What works, and what does not yet

| Works through the E2B backend | Not yet |
|---|---|
| Creating and destroying a workspace, with confirmed cleanup | **An agent launch on real E2B.** Syntropic137 launches, streams, settles and cancels an agent through the E2B provider's operation contract (#1912), with launch credentials delivered by the provider into the environment, never argv. That is tested against a scripted provider only; `test_an_agent_launches_on_real_e2b` has not run yet. |
| Running commands (stdout and stderr merged in write order) | Any workspace that needs host credentials. The E2B kit is always `NoCredentials`, so a phase with repositories is refused (see the ubiquitous language). |
| Writing and reading files, binary-safe | Session capture. E2B cannot mount the host's capture directory. |
| Listing and re-attaching to this run's sandboxes | Choosing E2B per run. Placement is #1917; today the flag switches every workspace. |

None of this has been run against real E2B yet. See [Running the real-E2B
suite](#running-the-real-e2b-suite).

## Turning it on

Set these in the API's environment (`.env`, or your deployment's secret
store). `.env.example` lists them under "E2B REMOTE WORKSPACES".

| Variable | Meaning | Default |
|---|---|---|
| `SYN_E2B_ENABLED` | The feature flag. `true` makes every workspace an E2B sandbox. | `false` |
| `SYN_E2B_API_KEY` | Your E2B API key. Required when enabled. | unset |
| `SYN_E2B_TEMPLATE` | The E2B template id or name, built from the pinned workspace image with agentic-workspace's `build_template`. Required when enabled. | unset |
| `SYN_E2B_CPU_COUNT` | vCPUs the template was built with. A workspace asking for more is refused. | `2` |
| `SYN_E2B_MEMORY_MB` | Memory (MB) the template was built with. A workspace asking for more is refused, and a workspace asks for `SYN_WORKSPACE_MEMORY_LIMIT_MB` (4096 by default): with both defaults every workspace is refused, so build the template that large or lower the workspace limit. | `2048` |
| `SYN_E2B_TIMEOUT_SECONDS` | Sandbox lifetime; E2B kills a sandbox this long after it was created. | `3600` |

With `SYN_E2B_ENABLED=true` and no key or no template, settings refuse to
load and the API does not start. It never falls back to Docker: a process that
was asked for E2B and ran on Docker would be lying about where your code ran.

The key is a `SecretStr`. Syntropic137 passes it to the E2B client explicitly
(the SDK's own `E2B_API_KEY` variable is not read), and never logs it or
writes it into an event.

## Running the real-E2B suite

CI has no E2B key and never will. The suite that proves the backend against
real E2B (`live_e2b_suite.py`) is not named `test_*.py`, so no default or CI
collection picks it up; it is marked `e2b` as well, and run by hand:

```bash
export SYN_E2B_API_KEY=...      # from your environment or keychain; never commit it
export SYN_E2B_TEMPLATE=...     # a template built from the pinned workspace image
just test-e2b
```

For example, with the key in the macOS keychain:
`export SYN_E2B_API_KEY="$(security find-generic-password -s e2b -w)"`.

It checks create, an agent launch through the stream path (argv, a launch
credential and the exit code), the merged stream and its outcome, a binary file round trip,
list and attach, and cleanup with nothing left in the E2B list for the run. It
also runs a negative control: a client whose kill does nothing must fail the
cleanup check, so a cleanup check that cannot fail is caught.

Without the two variables every test **skips** with `NOT RUN: real E2B needs
...`. A skip is not a pass.

The `e2b` SDK is not in `uv.lock` (it is agentic-isolation's optional `e2b`
extra), so `just test-e2b` adds it for that run only, without touching the
lock.

The same suite runs in CI against an in-memory sandbox double
(`test_e2b_backend.py`, marker `unit`). That proves Syntropic137's wiring and
the suite itself, not E2B.
