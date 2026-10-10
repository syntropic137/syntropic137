#!/usr/bin/env bash
# Turn a rendered frame sequence into web hero assets.
#   ./encode_web.sh renders/frames  out/   (frames named hero_0001.png ...)
# Produces: hero-poster.avif + .webp (last frame, the LCP image), hero.webm (AV1), hero.mp4 (H.264).
# The clip plays ONCE and holds its last frame (the landing page's idle-CPU test forbids loops).
# AV1 uses libaom if ffmpeg has it, else libsvtav1 (Homebrew ffmpeg). WebP uses ffmpeg's libwebp, else cwebp.
set -euo pipefail
IN=${1:-renders/frames}; OUT=${2:-out}; FPS=${FPS:-24}; W=${W:-1920}
mkdir -p "$OUT"
LAST=$(ls "$IN"/*.png | sort | tail -1)
ENC=$(ffmpeg -hide_banner -encoders 2>/dev/null)
has() { grep -q " $1 " <<<"$ENC"; }
if [ "${ALPHA:-0}" = 1 ]; then
  # Transparent frames (build_hero.py --transparent). Browsers only play alpha video as
  # VP9 WebM (Chrome, Firefox, Edge) or HEVC .mov/hvc1 (Safari, encoded by macOS VideoToolbox).
  # Clips: hero.* at W, hero-sm.* at SM_W for phones (<source media>).
  # Stills: STILL (a big render of the last frame, default the last frame) as hero-still-<w>.webp for srcset.
  SM_W=${SM_W:-960}; STILL=${STILL:-$LAST}; STILL_WIDTHS=${STILL_WIDTHS:-960 1600 2400 3200}
  # Under alpha ~0 the render leaves glow and sampling noise in RGB; nobody sees it but it
  # costs ~10x the bytes. Zero alpha below 6/255, then premultiply+unpremultiply to clear RGB there.
  CLEAN="format=rgba,lutrgb=a='if(lt(val\\,6)\\,0\\,val)',premultiply=inplace=1,unpremultiply=inplace=1"
  for v in "hero:$W" "hero-sm:$SM_W"; do
    name=${v%%:*}; w=${v##*:}
    ffmpeg -y -loglevel error -framerate "$FPS" -pattern_type glob -i "$IN/*.png" -vf "$CLEAN,scale=$w:-2" -c:v libvpx-vp9 -pix_fmt yuva420p -crf 36 -b:v 0 -row-mt 1 -auto-alt-ref 0 -an "$OUT/$name.webm"
    ffmpeg -y -loglevel error -framerate "$FPS" -pattern_type glob -i "$IN/*.png" -vf "$CLEAN,scale=$w:-2" -c:v hevc_videotoolbox -allow_sw 1 -alpha_quality 0.75 -q:v 55 -tag:v hvc1 -movflags +faststart -an "$OUT/$name.mov"
  done
  for w in $STILL_WIDTHS; do
    cwebp -quiet -q 80 -alpha_q 85 -m 6 -resize "$w" 0 "$STILL" -o "$OUT/hero-still-$w.webp"
  done
  ls -la "$OUT"; exit 0
fi
if has libaom-av1; then
  ffmpeg -y -loglevel error -i "$LAST" -vf "scale=$W:-2" -c:v libaom-av1 -still-picture 1 -crf 32 "$OUT/hero-poster.avif"
  ffmpeg -y -loglevel error -framerate "$FPS" -pattern_type glob -i "$IN/*.png" -vf "scale=$W:-2" -c:v libaom-av1 -crf 36 -b:v 0 -cpu-used 6 -pix_fmt yuv420p -an "$OUT/hero.webm"
elif has libsvtav1; then
  ffmpeg -y -loglevel error -i "$LAST" -vf "scale=$W:-2" -frames:v 1 -c:v libsvtav1 -crf 32 -pix_fmt yuv420p "$OUT/hero-poster.avif"
  ffmpeg -y -loglevel error -framerate "$FPS" -pattern_type glob -i "$IN/*.png" -vf "scale=$W:-2" -c:v libsvtav1 -crf 36 -preset 6 -pix_fmt yuv420p -an "$OUT/hero.webm"
else
  echo "AVIF and AV1 skipped (ffmpeg without libaom or libsvtav1)"
fi
if has libwebp; then
  ffmpeg -y -loglevel error -i "$LAST" -vf "scale=$W:-2" -quality 82 "$OUT/hero-poster.webp"
else
  cwebp -quiet -q 82 -resize "$W" 0 "$LAST" -o "$OUT/hero-poster.webp"
fi
ffmpeg -y -loglevel error -framerate "$FPS" -pattern_type glob -i "$IN/*.png" -vf "scale=$W:-2" -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -movflags +faststart -an "$OUT/hero.mp4"
ls -la "$OUT"
