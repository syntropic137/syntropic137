"""Generate placeholder app icons for the Tauri bundle (src-tauri/icons).

Placeholder art until the canvas has a real app icon: a dark rounded tile
with a three-bar skyline. Run: python3 apps/syn-desktop/scripts/make-icons.py
Needs Pillow. `pnpm tauri icon <1024px png>` replaces these with real art.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src-tauri" / "icons"
BG = (11, 15, 20, 255)
FG = (52, 230, 196, 255)


def tile(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 5
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)
    # three bars of a skyline, baseline at 78%
    base = int(size * 0.78)
    w = int(size * 0.14)
    gap = int(size * 0.07)
    x0 = (size - (3 * w + 2 * gap)) // 2
    for i, h in enumerate((0.30, 0.52, 0.40)):
        x = x0 + i * (w + gap)
        d.rectangle([x, base - int(size * h), x + w, base], fill=FG)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = tile(1024)
    big.resize((32, 32), Image.LANCZOS).save(OUT / "32x32.png")
    big.resize((128, 128), Image.LANCZOS).save(OUT / "128x128.png")
    big.resize((256, 256), Image.LANCZOS).save(OUT / "128x128@2x.png")
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / "icon.icns")
    print(f"wrote icons to {OUT}")


if __name__ == "__main__":
    main()
