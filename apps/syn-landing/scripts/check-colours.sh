#!/usr/bin/env bash
# Colour lint: no colour literals in the landing page's CSS or TSX
# (design/landing-plan.md, section 7). Colours come only from Skyline's
# --ds-* / --sky-* tokens (@syn137/skyline-themes).
#   CSS: Skyline's own gate, packages/syn-ui/scripts/check-css.mjs, pointed at
#        src/ (hex, rgb()/hsl()/oklch(), named colours, var() fallbacks).
#   TS/TSX: hex colours inside string literals and colour functions.
# With --tokens it also runs check-token-usage.mjs over src/ (needs
# `pnpm install`): every var(--ds-*) / var(--sky-*) must exist in the themes.
# Run by syn-landing.yml (copy-lint, build) and `just landing-colour-lint`.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$(cd ../.. && pwd)"
FAIL=0

node "$REPO/packages/syn-ui/scripts/check-css.mjs" src || FAIL=1

# grep exits 0 on a match, 1 on none and 2 on an error; only 0 and 1 are answers.
grep -rnE "[\"'\`]#[0-9a-fA-F]{3,8}[\"'\`]|\b(rgba?|hsla?|oklch|oklab|hwb)\(" src/ --include='*.tsx' --include='*.ts'
rc=$?
if [ "$rc" -eq 0 ]; then
  echo "colour literal in TS/TSX (above): use var(--ds-*) / var(--sky-*)"
  FAIL=1
elif [ "$rc" -gt 1 ]; then
  echo "could not scan src/ (grep exit $rc)"; exit 2
fi

if [ "${1:-}" = "--tokens" ]; then
  # shellcheck disable=SC2046
  (cd "$REPO" && node packages/syn-ui/scripts/check-token-usage.mjs apps/syn-landing/src $(find apps/syn-landing/src -name '*.tsx')) || FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "No colour literals in apps/syn-landing/src."
