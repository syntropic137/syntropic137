#!/usr/bin/env python3
"""
Capture a cinematic flythrough of .topology/viz/codecity.html
and produce a GIF + MP4 suitable for blog articles.

Usage:
    uv run python scripts/capture_codecity.py
"""

import asyncio
import base64
import math as _math
import subprocess
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).parent.parent
HTML_SRC = REPO_ROOT / ".topology" / "viz" / "codecity.html"
OUT_DIR = REPO_ROOT / ".topology" / "viz"

# Output resolution (1280x720 keeps GIF manageable; bump to 1920x1080 for MP4)
WIDTH = 1280
HEIGHT = 720

FPS = 30
DURATION_S = 28  # seconds total

# ---------------------------------------------------------------------------
# Two-phase camera:
#
#   Phase 1 — DESCENT (0 → DESCENT_END_S):
#     Smooth ease from bird's eye down to the orbit altitude.
#
#   Phase 2 — ORBIT (DESCENT_END_S → end):
#     Constant-speed rotation at a fixed altitude — perfectly fluid, no stops.
#     phi=1.02 puts the camera at "human scale": standing outside the city
#     looking across at the buildings. Camera height = citySize*r*cos(phi) ≈ 21 u
#     (safely above ~11 u max building height, but low enough to feel the scale).
# ---------------------------------------------------------------------------
DESCENT_END_S = 6.0

ORBIT_PHI = 0.85  # angle from vertical — elevated side view, buildings + layout both visible
ORBIT_R_FACTOR = 1.50  # radius = 1.5x citySize — full city in frame with breathing room
ORBIT_THETA_0 = 0.4  # starting azimuth when orbit begins
ORBIT_PERIOD_S = 21.0  # one full revolution in 21 s (nice leisurely pace)

# Descent start values (bird's eye)
DESCENT_PHI_0 = 0.15
DESCENT_R_0 = 1.85
DESCENT_THETA_0 = 0.0

# Label fade timing
LABEL_FULL_UNTIL_S = 4.0
LABEL_FADE_UNTIL_S = 7.5


def smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def camera_at(frame: int, total: int) -> tuple[float, float, float, float, float]:
    """
    Returns (radius_factor, phi, theta, target_x, target_z).

    Phase 1: smooth descent from bird's eye → orbit altitude.
    Phase 2: constant-speed orbit — no easing, perfectly continuous.
    """
    t_s = frame / FPS

    if t_s <= DESCENT_END_S:
        s = smoothstep(t_s / DESCENT_END_S)
        r_f = lerp(DESCENT_R_0, ORBIT_R_FACTOR, s)
        phi = lerp(DESCENT_PHI_0, ORBIT_PHI, s)
        theta = lerp(DESCENT_THETA_0, ORBIT_THETA_0, s)
        return r_f, phi, theta, 0.0, 0.0
    else:
        # Constant angular velocity — perfectly smooth, zero easing
        t_orbit = t_s - DESCENT_END_S
        omega = 2 * _math.pi / ORBIT_PERIOD_S
        theta = ORBIT_THETA_0 + omega * t_orbit
        return ORBIT_R_FACTOR, ORBIT_PHI, theta, 0.0, 0.0


def patch_html(src: Path, dst: Path) -> None:
    """
    Two patches:
    1. preserveDrawingBuffer:true — keeps the WebGL framebuffer alive after render()
       so canvas.toDataURL() in the same JS call always captures the correct frame.
    2. window.__cc globals — exposes camera controls to page.evaluate().
    """
    text = src.read_text(encoding="utf-8")

    # Patch 1: enable preserveDrawingBuffer so toDataURL() works reliably
    text = text.replace(
        "new THREE.WebGLRenderer({ antialias: true })",
        "new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })",
    )

    # Patch 2: expose globals + hide UI overlays
    inject = (
        "        // --- flythrough capture hook ---\n"
        "        window.__cc = { spherical, target, updateCamera, renderer, labelRenderer, scene, camera, citySize };\n"
        "        document.getElementById('info').style.display = 'none';\n"
        "        document.getElementById('controls').style.display = 'none';\n"
        "        document.getElementById('minimap').style.display = 'none';\n"
        "        document.getElementById('about-btn').style.display = 'none';\n"
        "        window.__cc.labelRenderer.domElement.style.transition = 'none';\n"
        "        // --------------------------------\n"
    )
    text = text.replace("        animate();", inject + "        animate();")
    dst.write_text(text)


async def capture(frame_dir: Path) -> None:
    total_frames = FPS * DURATION_S

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, dir=OUT_DIR) as tf:
        tmp_html = Path(tf.name)

    try:
        patch_html(HTML_SRC, tmp_html)
        print(f"Patched HTML → {tmp_html.name}")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox"],  # keep GPU enabled for WebGL
            )
            page = await browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})

            await page.goto(tmp_html.as_uri())
            print("Waiting for Three.js to render…")
            # Wait for the __cc globals injected by the patch (module fully executed)
            await page.wait_for_function("window.__cc !== undefined", timeout=30000)
            await page.wait_for_timeout(2000)  # let first render settle

            city_size: float = await page.evaluate("window.__cc ? window.__cc.citySize : 150")
            print(f"citySize = {city_size:.1f}")

            label_full_f = int(LABEL_FULL_UNTIL_S * FPS)
            label_gone_f = int(LABEL_FADE_UNTIL_S * FPS)

            print(f"Capturing {total_frames} frames at {FPS} fps ({DURATION_S}s)…")
            for i in range(total_frames):
                r_f, phi, theta, tx, tz = camera_at(i, total_frames)

                # Label opacity: 1.0 → 0.0 over the fade window
                if i <= label_full_f:
                    label_opacity = 1.0
                elif i >= label_gone_f:
                    label_opacity = 0.0
                else:
                    raw = (i - label_full_f) / (label_gone_f - label_full_f)
                    label_opacity = 1.0 - smoothstep(raw)

                # Render and capture canvas in one JS call — before WebGL buffer swap
                png_b64: str = await page.evaluate(
                    f"""
                    (function() {{
                        const cc = window.__cc;
                        cc.spherical.radius = {city_size * r_f};
                        cc.spherical.phi    = {phi};
                        cc.spherical.theta  = {theta};
                        cc.target.set({tx}, 0, {tz});
                        cc.updateCamera();
                        cc.renderer.render(cc.scene, cc.camera);
                        cc.labelRenderer.domElement.style.opacity = '{label_opacity:.4f}';
                        cc.labelRenderer.render(cc.scene, cc.camera);
                        // Capture immediately — preserveDrawingBuffer keeps this valid
                        return cc.renderer.domElement.toDataURL('image/png').split(',')[1];
                    }})();
                    """
                )

                frame_path = frame_dir / f"frame_{i:04d}.png"
                frame_path.write_bytes(base64.b64decode(png_b64))

                if i % FPS == 0:
                    elapsed = i // FPS
                    print(f"  {elapsed:>3}s / {DURATION_S}s  (frame {i})")

            await browser.close()

    finally:
        tmp_html.unlink(missing_ok=True)

    print(f"All frames saved to {frame_dir}")


def encode(frame_dir: Path) -> None:
    mp4_out = OUT_DIR / "codecity_flythrough.mp4"
    gif_out = OUT_DIR / "codecity_flythrough.gif"

    frames_glob = str(frame_dir / "frame_%04d.png")

    print("\nEncoding MP4…")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            frames_glob,
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4_out),
        ],
        check=True,
    )
    print(f"  → {mp4_out}  ({mp4_out.stat().st_size // 1024} KB)")

    print("\nEncoding GIF (palette-optimised)…")
    palette = frame_dir / "palette.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            frames_glob,
            "-vf",
            "fps=15,scale=960:-1:flags=lanczos,palettegen=max_colors=256:stats_mode=diff",
            str(palette),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            frames_glob,
            "-i",
            str(palette),
            "-filter_complex",
            "fps=15,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
            str(gif_out),
        ],
        check=True,
    )
    print(f"  → {gif_out}  ({gif_out.stat().st_size // 1024} KB)")


def main() -> None:
    if not HTML_SRC.exists():
        raise FileNotFoundError(f"Run `just topology` first — {HTML_SRC} not found")

    with tempfile.TemporaryDirectory(prefix="codecity_frames_") as tmp:
        frame_dir = Path(tmp)
        asyncio.run(capture(frame_dir))
        encode(frame_dir)

    print(f"\nDone! Files in {OUT_DIR}/")
    print("  codecity_flythrough.mp4")
    print("  codecity_flythrough.gif")


if __name__ == "__main__":
    main()
