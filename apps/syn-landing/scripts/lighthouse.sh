#!/usr/bin/env bash
# Local mirror of syn-landing.yml `lighthouse`: serve dist/ with vite preview and
# run Lighthouse CI with lighthouserc.json (desktop preset, one run; minimums
# Performance 90, Accessibility 90, Best Practices 85, SEO 90). Build first
# (`just landing-build`). LANDING_LH_PORT picks the port (default 8080);
# CHROME_PATH picks the browser if lhci cannot find one.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${LANDING_LH_PORT:-8080}"
LHCI="@lhci/cli@0.15.1"

if [ ! -f dist/index.html ]; then
  echo "dist/ is missing; run \`just landing-build\` first" >&2
  exit 1
fi

pnpm exec vite preview --port "$PORT" --strictPort > /dev/null 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -sf "http://localhost:$PORT/" > /dev/null && break
  sleep 1
done
curl -sf "http://localhost:$PORT/" > /dev/null || { echo "vite preview did not answer on :$PORT" >&2; exit 1; }

rm -rf .lighthouseci
pnpm dlx "$LHCI" collect --config=lighthouserc.json --url="http://localhost:$PORT/"
node -e '
const fs = require("fs");
for (const f of fs.readdirSync(".lighthouseci").filter((f) => /^lhr-.*\.json$/.test(f))) {
  const lhr = JSON.parse(fs.readFileSync(".lighthouseci/" + f, "utf8"));
  for (const c of Object.values(lhr.categories)) console.log(`${c.title}: ${Math.round(c.score * 100)}`);
}'
pnpm dlx "$LHCI" assert --config=lighthouserc.json
