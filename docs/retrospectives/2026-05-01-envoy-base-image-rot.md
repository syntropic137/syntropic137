# 2026-05-01 Envoy base image rot broke two consecutive releases

## What happened
The v0.25.3 release pipeline broke when `docker/sidecar-proxy/Dockerfile` failed to `apt-get install ca-certificates curl` against the `envoyproxy/envoy:v1.31-latest` base. PR #737 bumped the base to `v1.34.14` to unblock the release, but the bump was made without a local `docker build` first. v1.34.14 had the same class of failure (libcurl4 dependencies libbrotli1, libpsl5, librtmp1 unsatisfiable from the image's pinned apt sources), so the release pipeline broke again at v0.25.4. PR #740 bumps to `v1.35.10`, which was built locally first and succeeded on the first try.

## Timeline
- v0.25.3 release - sidecar-proxy build fails on v1.31-latest apt resolution
- PR #737 merged - bumps base to v1.34.14 with no local build
- v0.25.4 release - sidecar-proxy build fails again, same error class
- PR #740 merged - bumps base to v1.35.10, verified locally first

## Root cause
Treating "the upstream tag was pushed recently" as a proxy for "apt sources still resolve inside the image." Those are independent: Envoy's release cadence has nothing to do with whether Debian's apt mirrors still serve the exact package versions pinned in that image's sources.list. Without a local build, the bump was a guess.

## What we changed
- PR #740 - bump sidecar-proxy base to envoyproxy/envoy:v1.35.10
- `docker/sidecar-proxy/Dockerfile` - header comment now logs both incidents (v1.31, v1.34.14) and requires a local-build sanity check before any base bump
- Memory entry `feedback_local_build_before_base_bump.md` - never bump a base image without a local `docker build` first; 30 seconds locally beats a broken release pipeline

## Open follow-ups
- [ ] Weekly canary build of leaf images (sidecar-proxy, token-injector) so upstream apt rot surfaces outside the release window. No issue filed yet.
