#!/usr/bin/env bash
# Render the share image from og.html with headless Chrome (real fonts, unlike rsvg-convert).
#   design/brand/og-image.png                              1200 x 630  (Open Graph / Twitter card)
#   design/brand/social/github-social-preview-1280x640.png 1280 x 640  (GitHub repo social preview)
#   apps/syn-landing/public/og-image.png                   copy served by syntropic137.com
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; brand="$(dirname "$here")"; root="$(cd "$brand/../.." && pwd)"
chrome="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
shot() { "$chrome" --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files \
  --force-device-scale-factor=1 --window-size="$1,$2" --virtual-time-budget=3000 \
  --screenshot="$3" "file://$here/og.html?w=$1&h=$2" 2>/dev/null; }
shot 1200 630 "$brand/og-image.png"
shot 1280 640 "$brand/social/github-social-preview-1280x640.png"
cp "$brand/og-image.png" "$root/apps/syn-landing/public/og-image.png"
echo "wrote og-image.png, social/github-social-preview-1280x640.png, apps/syn-landing/public/og-image.png"
