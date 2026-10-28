"""Telefondan PC ekranini gorme + uzaktan kontrol.

  GET  /api/screen/stream  -> MJPEG (multipart/x-mixed-replace), birincil ekran, her parcada Content-Length
  POST /api/remote/input   -> {"type": tap|double|right|move|drag|scroll|keys|text, ...}

Varsayilan KAPALI: `.env` -> `JARVIS_REMOTE_DESKTOP=1`. Token + Tailscale ile korunur; acikken
her yayin baslangici/bitisi loga (HUD gunlugu) ve veriyoluna yazilir.
Koordinatlar telefondan 0-1 gelir, `tools/keyboard_input.py`'nin 0-1000 olcegine cevrilir
(ikisi de birincil ekranin tamami: DPI olcegi fark etmez).
"""

from __future__ import annotations

import time
from typing import Any, Iterator

from loguru import logger

from web.event_bus import BUS

FRAME_MAX = 1280      # uzun kenar (px): telefona yeter, Tailscale'de hafif
DEFAULT_FPS = 8
DEFAULT_QUALITY = 60


def frames(fps: float = DEFAULT_FPS, quality: int = DEFAULT_QUALITY) -> Iterator[bytes]:
    """Birincil ekrandan JPEG kareler uretir (sonsuz)."""
    import cv2
    import mss
    import numpy as np

    fps = max(1.0, min(15.0, float(fps)))
    quality = max(30, min(90, int(quality)))
    period = 1.0 / fps
    with getattr(mss, "MSS", mss.mss)() as sct:
        monitor = sct.monitors[1]  # birincil ekran
        while True:
            start = time.monotonic()
            grab = sct.grab(monitor)
            shot = np.frombuffer(grab.bgra, np.uint8).reshape(grab.height, grab.width, 4)
            h, w = shot.shape[:2]
            scale = FRAME_MAX / max(w, h)
            if scale < 1:  # INTER_LINEAR: INTER_AREA'dan ~4 kat hizli, metin hala okunur
                shot = cv2.resize(shot, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
            shot = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
            ok, jpg = cv2.imencode(".jpg", shot, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if ok:
                yield jpg.tobytes()
            left = period - (time.monotonic() - start)
            if left > 0:
                time.sleep(left)


def stream_started(client: str) -> None:
    logger.warning(f"UZAKTAN EKRAN: telefon PC ekranini izliyor ({client}).")
    BUS.push("remote_desktop", {"active": True})


def stream_stopped(client: str) -> None:
    logger.info(f"Uzaktan ekran izleme bitti ({client}).")
    BUS.push("remote_desktop", {"active": False})


def _pt(data: dict[str, Any], kx: str = "x", ky: str = "y") -> tuple[float, float]:
    """Telefonun 0-1 koordinatini keyboard_input'un 0-1000 olcegine cevirir."""
    x = max(0.0, min(1.0, float(data[kx])))
    y = max(0.0, min(1.0, float(data[ky])))
    return x * 1000.0, y * 1000.0


def handle_input(data: dict[str, Any]) -> dict[str, Any]:
    from tools import keyboard_input as kb

    kind = str(data.get("type", "")).lower()
    try:
        if kind in ("tap", "double", "right"):
            x, y = _pt(data)
            return kb.click_at(x, y, button="right" if kind == "right" else "left", double=kind == "double")
        if kind == "move":
            return kb.move_mouse(*_pt(data))
        if kind == "drag":
            return kb.drag_select(*_pt(data), *_pt(data, "x2", "y2"))
        if kind == "scroll":
            steps = int(data.get("dy", 0))
            return kb.scroll(max(-20, min(20, steps))) if steps else {"status": "yok"}
        if kind == "keys":
            return kb.press_keys(str(data.get("keys", "")))
        if kind == "text":
            text = str(data.get("text", ""))[:2000]
            return kb.type_text(text, per_char=0.01) if text else {"error": "metin bos"}
    except (KeyError, TypeError, ValueError):
        return {"error": "eksik ya da gecersiz koordinat"}
    return {"error": f"bilinmeyen girdi turu: {kind}"}
