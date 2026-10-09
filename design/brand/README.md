# Brand

The S mark: nine isometric cubes in one vertical plane, grid `BBG / B.. / DDD / ..D / DDD`
(blue top row, one glass cube, dark lower cubes). Traced from the original raster logo.

| File | Use |
|---|---|
| `s-mark.svg` | Fixed colours. README, social images, anywhere CSS variables don't work. Keep its embedded provenance metadata. |
| `s-mark.themable.svg` | Reads `--ac`. Reference for the `SMark` component; the component is built from `skyline-core`'s `sMark()` geometry, not from this file. |
| `favicon.svg`, `favicon-32x32.png` | Browser tab icon, transparent, square viewBox around the mark |
| `app-icon.svg` | Mark on the ground colour (`--ds-color-bg`, `#0A0C14`), source for the raster icons below |
| `apple-touch-icon.png` (180), `icon-192.png`, `icon-512.png` | iOS home screen and PWA manifest icons |

Regenerate the PNGs with `rsvg-convert`:

```bash
rsvg-convert -w 32 -h 32 favicon.svg -o favicon-32x32.png
rsvg-convert -w 180 -h 180 app-icon.svg -o apple-touch-icon.png
for s in 192 512; do rsvg-convert -w $s -h $s app-icon.svg -o icon-$s.png; done
```

The social image (the S over the run city) is made from `skyline-core`'s `isoCity()` and `sMark()` once they land, so it uses the same geometry as the page.
