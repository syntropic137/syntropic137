# Blender: Syntropic137 hero renders

`build_hero.py` builds the hero scene from the **same geometry and palette as the Skyline design boards**, so the render lines up with the vector version on the site. It builds:
- the run city: one cube per day of agent runs, taller on busier days; a few glow blue (live), coral (failed) or amber (errored);
- the Syntropic137 S standing in it, in cubes: blue top row, one glass cube, dark lower cubes, the same grid as `logo.png`.

Open any shot in Blender to art-direct it (lighting, materials, camera, animation), or render headless.

## Quick start
```bash
# build and open in the Blender UI to play with it
blender -P build_hero.py -- --shot hero
# headless still
blender -b -P build_hero.py -- --shot hero --res 1600x900 --samples 64 --out renders/hero.png
# animation: the city rises, then the S drops in cube by cube, bottom first
blender -b -P build_hero.py -- --shot hero --animate --seconds 5 --res 1920x1080 --out renders/frames/hero_####
# save a .blend to keep working on by hand
blender -b -P build_hero.py -- --shot hero --save hero.blend
```

| Flag | Values |
|---|---|
| `--shot` | `hero` (16:9, isometric, the S in the city), `banner` (3:1 header or social), `mark` (the S alone, perspective close-up) |
| `--animate` / `--seconds` / `--fps` | Rise-and-drop animation |
| `--device` | `CPU` or `GPU` (picks Metal, OptiX, CUDA or HIP automatically) |
| `--samples`, `--res`, `--accent` | Quality, size, accent colour (default `#4D80FF`) |
| `--no-denoise` | Only for Blender builds without OpenImageDenoise (Ubuntu's apt build) |

## Where to render
- **Mac mini (recommended):** run `./render_mac_mini.sh` there. It renders the final stills at 256 samples on the GPU plus the animation, then calls `encode_web.sh`. The cloud session couldn't reach the Mac mini over Tailscale, so copy this folder over and run it there.
- **The previews in `renders/`** were made in the cloud session with Blender 4.0.2 (CPU, 48 samples, no denoiser). That's why they're grainy; the Mac mini renders with the denoiser will be clean.

## Web delivery (landing page rules)
`./encode_web.sh <frames-dir> <out-dir>` produces:
- `hero-poster.avif`/`.webp`, the last frame, used as the LCP image (aim for about 150 KB or less);
- `hero.webm` (AV1) and `hero.mp4` (H.264), aim for about 1.5 MB or less.

On the page, the clip plays **once** and holds on its last frame: no `loop`, because the idle-CPU test fails otherwise. Under `prefers-reduced-motion`, show only the poster. The headline, terminal and floating cards stay as live HTML on top. See `LANDING-MIGRATION-PLAN.md`, decision "Hero visual, two layers".

## Known issues and art-direction notes
- **A faint grey rectangle appears behind the S** in the preview stills. It's a light reflection. Toggle the area lights' `visible_glossy` one at a time (the `S Spot` light is the likely cause), or move it.
- **The S reads best from the isometric angle (`hero`).** In `mark`, the camera crops the top; adjust `cam.location` or the lens.
- **Ideas:**
  - a slow push-in on the camera during the drop;
  - emission pulses on the live blocks;
  - a light sweep across the S at the end;
  - depth of field on `mark`.
