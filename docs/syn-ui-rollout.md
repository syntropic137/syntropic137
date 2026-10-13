# syn-ui rollout across the stack

How the Svelte dashboard (`apps/syn-ui`, ADR-073) replaces the React dashboard
(`apps/syn-dashboard-ui`) everywhere it is deployed. Two releases, each one a
normal `main -> release` merge; nothing here needs a special deploy path.

## What ships where today

| Piece | Lives in | Reaches a deployment via |
|---|---|---|
| Both UIs | one `syn-gateway` image (`infra/docker/images/gateway/Dockerfile`): syn-ui built with `SYN_UI_BASE=/` to `/` (default); React plus a `/next/` syn-ui build kept for `SYN_GATEWAY_UI=legacy` | `release-containers.yaml` builds, signs and pushes the image; the release attaches a digest-pinned compose |
| Self-host install | `syntropic137-setup` (`npx @syntropic137/setup`): `templates/docker-compose.syntropic137.yaml` pins `ghcr.io/syntropic137/syn-gateway@sha256:...` | `template-sync.yml` in that repo pulls the next release's digests; owner merges the bot PR (human gate) |
| Owner VPS | same compose, deployed by pit stop | `just pit-stop` with the release digests |
| Feature flags | `SYN_UI_FEEDBACK_ENABLED` (setup template exposes it, default false); `/features` reports it; syn-ui additionally requires a dev or fixtures build for the feedback widget | env on the API |
| Versions | API `GET /build-info` (version, sha, built_at); CLI `syn version`; syn-ui shows API and UI version in the shell | lockstep: `just bump-version` writes every manifest, `apps/syn-ui` and `packages/syn-ui/*` included |

Consequence: a self-host user gets syn-ui at `/` the moment they install a
release that contains it, with no change to the setup repo. The cutover is a
gateway routing change inside the same image.

## Release N: default (this branch, #1764)

Owner decision (2026-10-09): the next release ships syn-ui as the default; the
same endpoint opens it. The former "parallel" and "cutover" releases are one.

- Gateway: syn-ui is built with `SYN_UI_BASE=/` and owns `/` (SPA fallback to its `index.html`, hashed `/assets/` immutable, a missing chunk a real 404). `/next` and `/next/*` answer 301 to the same path under `/`, for bookmarks. Auth, `/api/v1/`, SSE, WebSocket and webhook locations are unchanged.
- `SYN_GATEWAY_UI` selects the UI, `next` (default) or `legacy`; any other value stops the gateway. `legacy` restores the previous release's layout for this release only: React at `/`, syn-ui (a second build with `SYN_UI_BASE=/next/`) at `/next`. The entrypoint writes the document root (`ui-root.conf`) and the UI locations from it.
- React is not served at `/legacy`: its `BrowserRouter` has no `basename`, so it cannot be re-based without editing `apps/syn-dashboard-ui`, which is frozen. `/legacy` in `next` mode is the syn-ui not-found page; the opt-out is the env, not a path.
- Setting declared in `InfraSettings.syn_gateway_ui` (ADR-004), generated into `infra/.env.example`, documented in `docker/selfhost.env.example`, passed by `docker/docker-compose.selfhost.yaml` (and the generated published compose).
- Proof: `infra/scripts/check_gateway_ui.py --mode next|legacy` (syn-ui at `/`, `/next` redirects, legacy React at `/`, `/api/v1/` still proxies); the `Gateway serves syn-ui at /` CI job and `just skyline-gateway-smoke` run both modes; `infra/scripts/tests/test_gateway_ui_mode.py` drives the entrypoint.
- Versions: `apps/syn-ui` and `packages/syn-ui/*` joined the product version (`PACKAGE_JSON_RELPATHS` in `bump_version.py`, exemption removed from `test_bump_version.py`), so the shell's UI version equals the API's and the mismatch mark is off on a clean build (`apps/syn-ui/src/shell/build.test.ts`).
- syn-ui: the `/insights/*` redirect route is gone (Insights left the nav on Oct 8); `getContributionHeatmap` stays for the Overview. API and CLI unchanged.
- Required API changes land first: #1765 (skills, latest outputs, cost by token type), #1800 (score, judge model, trend endpoints), #1816 (evals list batching, request latency telemetry, merged). #1800 and the evals read model bump projection versions, so they rebuild on deploy (one beta).
- syn-ui degrades per panel when an endpoint is missing ("not available on this server"), so an older API behind a newer gateway is safe.
- Setup repo: expose `SYN_GATEWAY_UI` in its `selfhost.env.example` with a comment (the `template-sync` bot PR carries the gateway digest as usual); README screenshots move to syn-ui; CHANGELOG "the dashboard is now the Svelte app; set `SYN_GATEWAY_UI=legacy` for the previous one, this release only".
- Public docs (`apps/syn-docs/content/docs/guide`): dashboard pages re-shot from syn-ui; keyboard shortcuts and the command palette documented from the keymap table.
- CLI: unchanged; it talks to the API only.
- Done when: this release is on the VPS with `SYN_GATEWAY_UI` unset, `/` serves syn-ui at the API's version, and no `legacy` fallback was needed for a release cycle.

## Release N+1: removal

- Delete `apps/syn-dashboard-ui`, `lib/ui-feedback/packages/ui-feedback-react` (the Svelte widget replaced it; the backend `ui-feedback-api` stays), the React build stage in the gateway Dockerfile, the `Dashboard UI` CI job, `SYN_GATEWAY_UI`, and the `/legacy` location.
- `pnpm-workspace.yaml` drops the React app; `bump_version.py` drops its manifest; the design README's Shipped table is the record of parity.
- Setup repo: remove the env line; nothing else, since the compose never referenced the React app directly.
- Done when: the release containing none of the above is on the VPS and the setup template points at it.

## What each repo must not do

- syntropic137-setup must never build or embed either UI: it pins the gateway digest only. All UI routing lives in the gateway image.
- The design-system repo (`@syntropic137/design-contracts`, `design-tokens`) releases on its own cadence; syn-ui pins exact versions and bumps them in ordinary PRs.
- No new feature flag for "new UI on/off" at the API level: the gateway env is the only switch, so the API never knows which UI called it.

## Versions, visible everywhere

| Surface | Shows |
|---|---|
| syn-ui shell | API version from `/build-info`, UI version baked at build; a mismatch (stale tab, rollout in flight) is highlighted |
| `syn version` | CLI version and API version |
| `GET /build-info` | version, git sha, built_at, environment |
| Release page | tag, digests of all six images, SHA256SUMS |

The UI version equals the API's on a clean deploy; the API version is the one that matters for support.

## Release checklist

1. Merge in order: #1765, #1800, then #1764 (this branch).
2. `just bump-version <next>` on `main`; `just check-version` passes (20 files, syn-ui included).
3. Cut a beta tag and run `just release-local` per [release-process.md](release-process.md#beta-release); no GitHub prerelease.
4. Pit stop the VPS with the beta digests (`just pit-stop`).
5. Verify `/` serves syn-ui and its shell shows the API's version with no mismatch mark (`infra/scripts/check_gateway_ui.py <url>` from a host that can reach it).
6. Verify the opt-out: `SYN_GATEWAY_UI=legacy` on the gateway serves React at `/` (`check_gateway_ui.py <url> --mode legacy`), then unset it again. `/legacy` is not a path (see Release N).
7. `GET /observability/latency` shows `/evals` under 500 ms.
8. Then the real release (`main -> release`).
