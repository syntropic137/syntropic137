# Skyline serving, e2e and CI mirrors (.github/workflows/syn-ui.yml).
#
# Production: the gateway image (infra/docker/images/gateway) builds apps/syn-ui
# with SYN_UI_BASE=/ and serves it at / (SYN_GATEWAY_UI=next, the default). The
# one-release opt-out SYN_GATEWAY_UI=legacy restores React at / and syn-ui at
# /next (docs/syn-ui-rollout.md). Build, check and dev recipes live in
# just/skyline.just; this file holds what serves, tests and gates the build.

_skyline_e2e_port := env_var_or_default("SKYLINE_E2E_PORT", "4199")
_skyline_gw_port := env_var_or_default("SKYLINE_GATEWAY_PORT", "18137")

# Mirror of syn-ui.yml `qa`: frozen install, check, test, build with the size budget
skyline-ci:
    CI=true pnpm install --frozen-lockfile --ignore-scripts
    just skyline-qa

# Dev server at /next/ against the dev gateway API (:9137), the same path production serves
skyline-dev-next:
    SYN_UI_BASE=/next/ pnpm --filter syn-ui run dev

# Build for /next/ and preview it on :4173 (set VITE_SYN_FIXTURES=1 for no backend)
skyline-preview-next:
    SYN_UI_BASE=/next/ pnpm --filter syn-ui exec vite build
    SYN_UI_BASE=/next/ pnpm --filter syn-ui exec vite preview --host 127.0.0.1

# Mirror of syn-ui.yml `e2e`: Playwright suite, fixtures data, against a / build (the production base)
skyline-e2e *args:
    #!/usr/bin/env bash
    set -euo pipefail
    cd apps/syn-ui
    pw=node_modules/@playwright/test/cli.js
    if [ ! -f "$pw" ]; then
        echo "skyline-e2e: @playwright/test is not installed for apps/syn-ui." >&2
        echo "  Add \"@playwright/test\": \"1.59.0\" to apps/syn-ui devDependencies and run pnpm install." >&2
        exit 1
    fi
    # A production-shaped bundle (fixtures data, / base) rather than the
    # dev server: no cold on-demand compiles, and the deploy base is exercised.
    out="$(mktemp -d)"
    trap 'kill "${preview:-}" 2>/dev/null || true; rm -rf "$out"' EXIT
    SYN_UI_BASE=/ VITE_SYN_FIXTURES=1 pnpm exec vite build --outDir "$out" --emptyOutDir --logLevel warn
    SYN_UI_BASE=/ pnpm exec vite preview --outDir "$out" --host 127.0.0.1 --port {{_skyline_e2e_port}} --strictPort > /dev/null &
    preview=$!
    base="http://127.0.0.1:{{_skyline_e2e_port}}/"
    for _ in $(seq 1 60); do curl -sf --noproxy '*' -o /dev/null "$base" && break; sleep 0.5; done
    E2E_BASE_URL="$base" E2E_DATA=fixtures node "$pw" test {{args}}

# Mirror of syn-ui.yml `screenshots`: /dev/components and /dev/patterns at 1440px and 390px.
# Baselines are Linux Chromium (CI); on macOS this writes git-ignored *-darwin.png files.
# Pass --update-snapshots=all to (re)write the baselines for this OS.
skyline-screenshots *args:
    SYN_UI_SCREENSHOTS=1 just skyline-e2e --project=screenshots-1440 --project=screenshots-390 {{args}}

# The suite's own server at / (fixtures preview build; E2E_DEV=1 for the dev server)
skyline-e2e-root *args:
    cd apps/syn-ui && node node_modules/@playwright/test/cli.js test {{args}}

# Mirror of syn-ui.yml `gateway`: build the gateway image, assert both SYN_GATEWAY_UI modes
skyline-gateway-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    image=syn-gateway:skyline-smoke
    docker build -f infra/docker/images/gateway/Dockerfile -t "$image" .
    url="http://127.0.0.1:{{_skyline_gw_port}}"
    name=""
    trap 'rc=$?; [ "$rc" -eq 0 ] || [ -z "$name" ] || docker logs "$name" 2>&1 | tail -20; [ -z "$name" ] || docker stop "$name" > /dev/null 2>&1 || true' EXIT
    for mode in next legacy; do
        name="syn-gateway-skyline-smoke-$$-$mode"
        # The API is not part of this check; `api` only has to resolve for nginx to load.
        docker run -d --rm --name "$name" --add-host api:127.0.0.1 \
            -e SYN_GATEWAY_BIND=127.0.0.1 -e SYN_GATEWAY_UI="$mode" \
            -p 127.0.0.1:{{_skyline_gw_port}}:80 "$image" > /dev/null
        for _ in $(seq 1 30); do curl -sf --noproxy '*' -o /dev/null "$url/health" && break; sleep 1; done
        python3 infra/scripts/check_gateway_ui.py "$url" --mode "$mode"
        docker stop "$name" > /dev/null
        name=""
    done
