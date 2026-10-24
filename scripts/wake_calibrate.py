"""Uyandirma kelimesi ("Hey CYRAEN") esik kalibrasyonu - gercek mikrofonla.

    python scripts/wake_calibrate.py            # 10 sn arka plan + 5 deneme
    python scripts/wake_calibrate.py --tries 8

CYRAEN KAPALIYKEN calistirin (mikrofonu ayni anda iki surec acamayabilir).
1. Adim: 10 sn boyunca normal ortam / normal konusma -> yanlis tetik skorlari.
2. Adim: her denemede "Hey CYRAEN" deyin -> gercek tetik skorlari.
Sonunda .env'e yazilacak `CYRAEN_WAKE_WORD_THRESHOLD=` satiri onerilir.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from core.wake_word import FRAME_SAMPLES, WakeWordDetector  # noqa: E402

MIN_THRESHOLD = 0.2
MAX_THRESHOLD = 0.8


def suggest_threshold(background: list[float], triggers: list[float]) -> tuple[float, str]:
    """(onerilen esik, aciklama). Arka plan tepesi ile en zayif tetik arasinin ortasi."""
    bg_max = max(background, default=0.0)
    if not triggers or max(triggers) <= bg_max:
        return 0.5, "UYARI: 'Hey CYRAEN' arka plandan ayristirilamadi; mikrofonu/ortami kontrol edin."
    hits = [t for t in triggers if t > bg_max]
    weakest = min(hits)
    value = round(min(MAX_THRESHOLD, max(MIN_THRESHOLD, (bg_max + weakest) / 2)), 2)
    note = f"{len(hits)}/{len(triggers)} deneme arka plan tepesinin ({bg_max:.2f}) uzerinde."
    if len(hits) < len(triggers):
        note += " Kacan denemeler icin daha net/yakindan soyleyin."
    return value, note


def _bar(score: float, width: int = 30) -> str:
    filled = int(score * width)
    return "#" * filled + "." * (width - filled)


def _record(stream, detector: WakeWordDetector, seconds: float, label: str) -> list[float]:
    scores: list[float] = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        s = detector.score(stream.read(FRAME_SAMPLES, exception_on_overflow=False))
        scores.append(s)
        print(f"\r  {label} [{_bar(s)}] {s:.2f}  ", end="", flush=True)
    print()
    return scores


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--background", type=float, default=10.0, help="arka plan kaydi (sn)")
    ap.add_argument("--tries", type=int, default=5, help="'Hey CYRAEN' deneme sayisi")
    args = ap.parse_args()

    import pyaudio

    settings = get_settings()
    detector = WakeWordDetector(settings.wake_word_model)
    if not detector.load():
        print("Uyandirma modeli yuklenemedi (openwakeword kurulu mu?).")
        return 1

    pya = pyaudio.PyAudio()
    stream = pya.open(format=pyaudio.paInt16, channels=1, rate=16_000, input=True,
                      frames_per_buffer=FRAME_SAMPLES)
    try:
        print(f"\n1) {args.background:.0f} sn ARKA PLAN: normal konusun / ortam sesi olsun, "
              "'Hey CYRAEN' DEMEYIN.")
        background = _record(stream, detector, args.background, "arka plan")

        triggers: list[float] = []
        for i in range(1, args.tries + 1):
            input(f"\n2) Deneme {i}/{args.tries}: Enter'a basin, sonra 'Hey CYRAEN' deyin...")
            detector.reset()
            peak = max(_record(stream, detector, 3.0, f"deneme {i}"), default=0.0)
            triggers.append(peak)
            print(f"  tepe skor: {peak:.2f}")
    except KeyboardInterrupt:
        print("\nIptal edildi.")
        return 130
    finally:
        stream.stop_stream()
        stream.close()
        pya.terminate()

    value, note = suggest_threshold(background, triggers)
    bg_sorted = sorted(background)
    p99 = bg_sorted[int(len(bg_sorted) * 0.99) - 1] if bg_sorted else 0.0
    print("\n--- SONUC ---")
    print(f"Arka plan: max {max(background, default=0):.2f} · p99 {p99:.2f}")
    print("Tetikler : " + ", ".join(f"{t:.2f}" for t in triggers))
    print(f"Simdiki esik: {settings.wake_word_threshold:.2f}")
    print(note)
    print(f"\n.env'e yazin:\nCYRAEN_WAKE_WORD_THRESHOLD={value:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
