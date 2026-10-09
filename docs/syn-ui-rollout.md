# syn-ui rollout across the stack

How the Svelte dashboard (`apps/syn-ui`, ADR-073) replaces the React dashboard
(`apps/syn-dashboard-ui`) everywhere it is deployed, without a flag day. Three
releases, each one a normal `main -> release` merge; nothing here needs a special
deploy path.

## What ships where today

| Piece | Lives in | Reaches a deployment via |
|---|---|---|
| Both UIs | one `syn-gateway` image (`infra/docker/images/gateway/Dockerfile`): React built to `/`, syn-ui built with `SYN_UI_BASE=/next/` to `/next` | `release-containers.yaml` builds, signs and pushes the image; the release attaches a digest-pinned compose |
| Self-host install | `syntropic137-setup` (`npx @syntropic137/setup`): `templates/docker-compose.syntropic137.yaml` pins `ghcr.io/syntropic137/syn-gateway@sha256:...` | `template-sync.yml` in that repo pulls the next release's digests; owner merges the bot PR (human gate) |
| Owner VPS | same compose, deployed by pit stop | `just pit-stop` with the release digests |
| Feature flags | `SYN_UI_FEEDBACK_ENABLED` (setup template exposes it, default false); `/features` reports it; syn-ui additionally requires a dev or fixtures build for the feedback widget | env on the API |
| Versions | API `GET /build-info` (version, sha, built_at); CLI `syn version`; syn-ui shows API and UI version in the shell | lockstep: `just bump-version` writes every manifest; `apps/syn-ui` and `packages/syn-ui/*` are exempt (0.0.0) until release 2 below |

Consequence: a self-host user gets syn-ui at `/next` the moment they install a
release that contains it, with no change to the setup repo. The cutover is a
gateway routing change inside the same image.

## Release 1: parallel (this branch, #1764)

- Gateway serves React at `/`, syn-ui at `/next`. `infra/scripts/check_gateway_next.py` and the `Gateway serves /next` CI job prove both.
- Required API changes land first: #1765 (skills, latest outputs, cost by token type), #1800 (score, judge model, trend endpoints), #1816 (evals list batching, request latency telemetry). Each is a normal PR; #1800 and the evals read model bump projection versions, so they rebuild on deploy (group them in one beta).
- syn-ui degrades per panel when an endpoint is missing ("not available on this server"), so an older API behind a newer gateway is safe.
- Setup repo: nothing. The `template-sync` bot PR carries the new gateway digest as usual. README gets one line: "the new dashboard is available at `/next`".
- Done when: a week of owner use at `/next` on the VPS with the feedback widget on, the short list of what bugs (design/README.md owner tweaks) worked through, and `GET /observability/latency` shows the evals list under 500 ms.

## Release 2: cutover

- Gateway routes `/` to syn-ui and `/legacy` to React, behind one env, `SYN_GATEWAY_UI` (`next` default, `legacy` opt-out for one release). The entrypoint already generates nginx locations from env; this is one more location block.
- `apps/syn-ui` joins the product version: remove the exemption in `scripts/workflows/test_bump_version.py` and add `apps/syn-ui/package.json` and `packages/syn-ui/*/package.json` to `PACKAGE_JSON_RELPATHS` in `bump_version.py`; the version shown in the shell then equals the API's.
- Setup repo: expose `SYN_GATEWAY_UI` in `selfhost.env.example` with a comment; `docs/` and README screenshots move to syn-ui; CHANGELOG "the dashboard is now the Svelte app; the previous one is at `/legacy` for this release".
- Public docs (`apps/syn-docs/content/docs/guide`): dashboard pages re-shot from syn-ui; keyboard shortcuts and the command palette documented from the keymap table.
- CLI: unchanged; it talks to the API only.
- Done when: a release with `SYN_GATEWAY_UI=next` default has shipped and no `/legacy` fallback was needed on the VPS for a release cycle.

## Release 3: removal

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
| syn-ui shell | API version from `/build-info`, UI version baked at build; mismatch is highlighted during rollout |
| `syn version` | CLI version and API version |
| `GET /build-info` | version, git sha, built_at, environment |
| Release page | tag, digests of all six images, SHA256SUMS |

Until release 2 the UI version reads `0.0.0` by design (pre-release, exempt from lockstep); the API version is the one that matters for support.
