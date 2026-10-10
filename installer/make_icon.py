"""Draws assets/ominvox.ico (the app icon) with Pillow. Run by build_exe.bat."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "ominvox.ico"


def draw(size: int) -> Image.Image:
    s = size * 4                                   # supersample, then downscale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=(124, 92, 252, 255))
    c, r = s / 2, s * 0.30                          # outer diamond
    d.polygon([(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=(255, 255, 255, 255))
    r2 = s * 0.15                                   # inner cut-out
    d.polygon([(c, c - r2), (c + r2, c), (c, c + r2), (c - r2, c)], fill=(124, 92, 252, 255))
    r3 = s * 0.06                                   # centre dot
    d.polygon([(c, c - r3), (c + r3, c), (c, c + r3), (c - r3, c)], fill=(92, 204, 252, 255))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big = draw(256)
    big.save(OUT, sizes=[(n, n) for n in sizes])
    print(f"wrote {OUT}")
