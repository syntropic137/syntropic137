#!/usr/bin/env bash
# Render the share image from og.html with headless Chrome (real fonts, unlike rsvg-convert).
#   design/brand/v2/link-preview/og-image.png                1200 x 630  (Open Graph / Twitter card)
#   design/brand/v2/social/github/social-preview-1280x640.png 1280 x 640  (GitHub repo social preview)
#   apps/syn-landing/public/og-image.png                      copy served by syntropic137.com
#   design/brand/v2/social/x/header-1500x500.png              X header (x-header.html: text clear of the avatar)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; style="$(dirname "$here")"; root="$(cd "$style/../../.." && pwd)"
chrome="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
shot() { "$chrome" --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files \
  --force-device-scale-factor=1 --window-size="$1,$2" --virtual-time-budget=3000 \
  --screenshot="$3" "file://$here/$4" 2>/dev/null; }
shot 1200 630 "$style/link-preview/og-image.png" "og.html?w=1200&h=630"
shot 1280 640 "$style/social/github/social-preview-1280x640.png" "og.html?w=1280&h=640"
shot 1500 500 "$style/social/x/header-1500x500.png" "x-header.html"
cp "$style/link-preview/og-image.png" "$root/apps/syn-landing/public/og-image.png"
echo "wrote link-preview/og-image.png, social/github/social-preview-1280x640.png, social/x/header-1500x500.png, apps/syn-landing/public/og-image.png"
