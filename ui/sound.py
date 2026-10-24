"""Basit ses efekti calma (acilis alkisi vb.).

Windows'ta stdlib `winsound`; diger platformlarda `aplay`/`afplay` denenir.
Baska bagimlilik gerektirmez.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from loguru import logger


def _play_blocking(path: Path) -> None:
    try:
        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME)
        elif sys.platform == "darwin":
            import subprocess

            subprocess.run(["afplay", str(path)], check=False)
        else:
            import subprocess

            subprocess.run(["aplay", "-q", str(path)], check=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Ses calinamadi ({path.name}): {exc!r}")


def play(path: str | Path, block: bool = False) -> None:
    """Bir WAV dosyasini calar. `block=False` ise arka planda."""
    p = Path(path)
    if not p.is_file():
        logger.debug(f"Ses dosyasi yok: {p}")
        return
    if block:
        _play_blocking(p)
    else:
        threading.Thread(target=_play_blocking, args=(p,), daemon=True, name="cyraen-sound").start()


def play_chime() -> None:
    """Uyandirma kelimesi algilaninca kisa iki tonlu 'bip' (arka planda, bloklamaz)."""
    def _beep() -> None:
        try:
            import winsound

            winsound.Beep(880, 70)
            winsound.Beep(1320, 90)
        except Exception as exc:  # noqa: BLE001 - ses yoksa sessiz gec
            logger.debug(f"Uyandirma sesi calinamadi: {exc}")

    threading.Thread(target=_beep, daemon=True, name="cyraen-chime").start()


def play_startup(settings) -> None:  # noqa: ANN001
    """Ayar acaksa acilis alkisini calar."""
    if not getattr(settings, "startup_sound", True):
        return
    play(getattr(settings, "startup_sound_path", ""), block=False)
