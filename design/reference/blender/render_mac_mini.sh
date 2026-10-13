#!/usr/bin/env bash
# Production renders on the Mac mini (Apple Silicon, Metal GPU). Run ON the Mac mini, e.g.:
#   scp -r blender/ mac-mini:~/syn137-blender && ssh mac-mini 'cd ~/syn137-blender && ./render_mac_mini.sh'
# Uses the official Blender app (has OpenImageDenoise + Metal).
set -euo pipefail
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
mkdir -p renders/final renders/frames
"$BLENDER" -b -P build_hero.py -- --shot hero   --device GPU --res 2560x1440 --samples 256 --out renders/final/syn137_hero.png
"$BLENDER" -b -P build_hero.py -- --shot banner --device GPU --res 3000x1000 --samples 256 --out renders/final/syn137_banner.png
"$BLENDER" -b -P build_hero.py -- --shot mark   --device GPU --res 2048x2048 --samples 256 --out renders/final/syn137_mark.png
"$BLENDER" -b -P build_hero.py -- --shot hero   --device GPU --animate --seconds 5 --res 1920x1080 --samples 128 --out renders/frames/hero_####
./encode_web.sh renders/frames renders/web
