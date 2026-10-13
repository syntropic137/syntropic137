#!/usr/bin/env bash
# Copy lint: no em dashes in user-facing files (src, index.html, README.md).
# Matches the literal U+2014 em dash and the CSS \2014 escape (optional leading
# zeros). Run by .github/workflows/syn-landing.yml (copy-lint) and
# `just landing-copy-lint`; runs from any directory.
set -uo pipefail
cd "$(dirname "$0")/.."

PATTERN='—|\\0*2014'
FAIL=0

# grep exits 0 on a match, 1 on none and 2 on an error; only 0 and 1 are answers.
grep -rnE "$PATTERN" src/ --include='*.tsx' --include='*.ts' --include='*.css'
rc=$?
if [ "$rc" -eq 0 ]; then FAIL=1; elif [ "$rc" -gt 1 ]; then echo "could not scan src/ (grep exit $rc)"; exit 2; fi

for f in index.html README.md; do
  if [ -f "$f" ] && grep -HnE "$PATTERN" "$f"; then
    FAIL=1
  fi
done

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "Em dashes found in user-facing files."
  echo "Replace with period, comma, or colon (or \\00b7 middle dot in CSS)."
  exit 1
fi
echo "No em dashes found."
