"""JARVIS gomulu varliklarini uretir: applause.wav + jarvis ikonu (png/ico).

Calistir:  python assets/generate_assets.py
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import numpy as np

ASSETS = Path(__file__).resolve().parent


def make_applause(path: Path, seconds: float = 2.6, sample_rate: int = 44_100) -> None:
    """Cok sayida kisa 'clap' patlamasini ust uste bindirerek alkis sentezler."""
    rng = np.random.default_rng(7)
    total = int(seconds * sample_rate)
    out = np.zeros(total, dtype=np.float64)

    n_claps = 520
    for _ in range(n_claps):
        # zamanla yogunlasip sonra sonen dagilim
        t0 = (rng.random() ** 0.75) * (seconds - 0.12)
        i0 = int(t0 * sample_rate)
        length = int(rng.integers(int(0.004 * sample_rate), int(0.018 * sample_rate)))
        burst = rng.standard_normal(length)
        env = np.exp(-np.linspace(0.0, 7.0, length))
        burst *= env * (0.25 + 0.75 * rng.random())
        end = min(total, i0 + length)
        out[i0:end] += burst[: end - i0]

    # genel zarf: hizli yukselis, uzun dusus
    gain = np.ones(total)
    rise = int(0.12 * sample_rate)
    fall = int(1.1 * sample_rate)
    gain[:rise] = np.linspace(0.0, 1.0, rise)
    gain[-fall:] = np.linspace(1.0, 0.0, fall) ** 1.5
    out *= gain

    # hafif alcak-gecirgen (komsu ortalama) -> daha yumusak
    kernel = np.ones(3) / 3.0
    out = np.convolve(out, kernel, mode="same")

    peak = np.max(np.abs(out)) or 1.0
    out = (out / peak) * 0.72
    pcm = np.clip(out * 32767, -32768, 32767).astype("<i2")

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    print(f"yazildi: {path}  ({seconds:.1f}s)")


def make_icon(png_path: Path, ico_path: Path) -> None:
    """HUD halkasi seklinde bir ikon cizer (PySide6 varsa)."""
    try:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
    except Exception as exc:  # noqa: BLE001
        print(f"PySide6 yok, ikon atlandi: {exc}")
        return

    _app = QGuiApplication.instance() or QGuiApplication([])
    size = 256
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    accent = QColor("#22d3ee")
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#05080d"))
    p.drawEllipse(8, 8, size - 16, size - 16)

    for width, alpha in ((26, 40), (12, 110), (5, 255)):
        pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha))
        pen.setWidth(width)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(38, 38, size - 76, size - 76))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(accent)
    p.drawEllipse(QRectF(size / 2 - 26, size / 2 - 26, 52, 52))

    pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 180))
    pen.setWidth(6)
    p.setPen(pen)
    p.drawArc(QRectF(24, 24, size - 48, size - 48), 30 * 16, 120 * 16)
    p.drawArc(QRectF(24, 24, size - 48, size - 48), 210 * 16, 90 * 16)
    p.end()

    png_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(png_path), "PNG")
    print(f"yazildi: {png_path}")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    if not img.save(str(ico_path), "ICO"):
        # Qt ICO yazamazsa PNG'yi .ico adiyla birak (PyInstaller yine kabul eder)
        img.save(str(ico_path.with_suffix(".png")), "PNG")
        print("ICO yazilamadi; PNG kullanin (jarvis.png).")
    else:
        print(f"yazildi: {ico_path}  {sizes}")


if __name__ == "__main__":
    make_applause(ASSETS / "applause.wav")
    make_icon(ASSETS / "jarvis.png", ASSETS / "jarvis.ico")
