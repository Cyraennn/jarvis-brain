"""PWA ikonlarini `assets/cyraen.png`'den uretir.

    python assets/generate_pwa_icons.py

Cikti (assets/):
    icon-192.png, icon-512.png          - standart (any)
    icon-maskable-512.png               - maskable (guvenli bolge dolgulu)
    apple-touch-icon.png (180x180)      - iOS ana ekran
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

_HERE = Path(__file__).resolve().parent
_SRC = _HERE / "cyraen.png"
_BG = (5, 7, 13, 255)  # #05070d - HUD uzay-siyahi


def _fit(src: Image.Image, size: int, pad_ratio: float = 0.0) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), _BG)
    inner = int(size * (1 - 2 * pad_ratio))
    icon = src.resize((inner, inner), Image.LANCZOS)
    off = (size - inner) // 2
    canvas.alpha_composite(icon, (off, off))
    return canvas


def main() -> None:
    if not _SRC.is_file():
        raise SystemExit(f"kaynak yok: {_SRC} (once assets/generate_assets.py calistirin)")
    src = Image.open(_SRC).convert("RGBA")
    _fit(src, 192).save(_HERE / "icon-192.png")
    _fit(src, 512).save(_HERE / "icon-512.png")
    _fit(src, 512, pad_ratio=0.14).save(_HERE / "icon-maskable-512.png")
    _fit(src, 180).save(_HERE / "apple-touch-icon.png")
    print("PWA ikonlari uretildi:", ", ".join(
        p.name for p in _HERE.glob("icon-*.png")
    ), "+ apple-touch-icon.png")


if __name__ == "__main__":
    main()
