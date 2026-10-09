# syntropic137.com: the marketing site (apps/syn-landing), Vite + React 19 on
# Vercel. Plan: design/landing-plan.md. CI: .github/workflows/syn-landing.yml;
# each of its jobs has a recipe here that runs the same commands.

_landing_port := env_var_or_default("LANDING_PORT", "3000")

# Dev server (http://localhost:5173 unless vite picks another port)
landing-dev:
    pnpm --filter syn-landing run dev

# Production build into apps/syn-landing/dist (syn-landing.yml `build`)
landing-build:
    pnpm --filter syn-landing run build

# Serve the production build on LANDING_PORT (default 3000)
landing-preview:
    pnpm --filter syn-landing exec vite preview --port {{_landing_port}} --strictPort

# No em dashes in user-facing copy (syn-landing.yml `copy-lint`)
landing-copy-lint:
    bash apps/syn-landing/scripts/check-copy.sh

# tsc --noEmit over src/ (syn-landing.yml `build`; vite build itself does not type-check)
landing-typecheck:
    pnpm --filter syn-landing run typecheck

# Lighthouse against vite preview of dist/ with the CI minimums (syn-landing.yml `lighthouse`)
landing-lighthouse: landing-build
    bash apps/syn-landing/scripts/lighthouse.sh

# Takes ~2 minutes. LANDING_PORT moves the server; PW_CHROMIUM_PATH reuses a browser.
# Idle-CPU energy test against vite preview of dist/ (syn-landing.yml `energy`)
landing-energy: landing-build
    LANDING_PORT={{_landing_port}} pnpm --filter syn-landing run test:energy

# Fast local gate: copy lint, typecheck, build
landing-qa: landing-copy-lint landing-typecheck landing-build
