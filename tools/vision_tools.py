"""Ekran goruntusu, OCR (Gemini vision), ekran kaydi. Self-contained."""

from __future__ import annotations

import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from config.settings import APP_DIR, get_settings

_SHOTS = APP_DIR / "data" / "screenshots"
_RECS = APP_DIR / "data" / "recordings"


def _grab_png(monitor: int | None = None) -> bytes:
    import mss
    import mss.tools

    with mss.mss() as sct:
        mons = sct.monitors
        idx = monitor if (monitor and 0 <= monitor < len(mons)) else get_settings().screen_monitor
        idx = idx if 0 <= idx < len(mons) else 1
        shot = sct.grab(mons[idx])
        return mss.tools.to_png(shot.rgb, shot.size)


def save_screenshot(path: str = "") -> dict[str, Any]:
    """Ekran goruntusu alir ve kaydeder (verilmezse data/screenshots/)."""
    try:
        png = _grab_png()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Ekran alinamadi: {exc}"}
    if path.strip():
        out = Path(path).expanduser()
        if out.is_dir():
            out = out / f"jarvis_{datetime.now():%Y%m%d_%H%M%S}.png"
    else:
        _SHOTS.mkdir(parents=True, exist_ok=True)
        out = _SHOTS / f"{datetime.now():%Y%m%d_%H%M%S}.png"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)
    except OSError as exc:
        return {"error": f"Kaydedilemedi: {exc}"}
    return {"status": "kaydedildi", "path": str(out), "size_kb": round(len(png) / 1024, 1)}


@lru_cache(maxsize=1)
def _genai():  # noqa: ANN202
    from google import genai
    from google.genai import types

    s = get_settings()
    return genai.Client(
        api_key=s.gemini_api_key,
        http_options=types.HttpOptions(api_version=s.agents_api_version, timeout=45_000),
    ), types


async def _ocr_bytes(data: bytes, mime: str, instruction: str) -> str:
    from agents.genai_util import generate_with_retry

    client, types = _genai()
    s = get_settings()
    resp = await generate_with_retry(
        client,
        model=s.agent_model_chain,
        contents=[types.Part.from_bytes(data=data, mime_type=mime), types.Part(text=instruction)],
        config=types.GenerateContentConfig(temperature=0.0),
    )
    return (getattr(resp, "text", None) or "").strip()


async def ocr_screen(instruction: str = "") -> dict[str, Any]:
    """Ekran goruntusundeki tum metni cikarir (Gemini vision - Tesseract gerekmez)."""
    try:
        png = _grab_png()
        prompt = instruction.strip() or (
            "Bu ekran goruntusundeki TUM okunabilir metni cikar. Duzeni koru, "
            "gereksiz yorum ekleme."
        )
        text = await _ocr_bytes(png, "image/png", prompt)
        return {"status": "ok", "text": text or "(metin bulunamadi)", "chars": len(text)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"OCR basarisiz: {exc}"}


async def ocr_image(path: str, instruction: str = "") -> dict[str, Any]:
    """Bir gorsel dosyasindaki metni cikarir."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"error": f"Dosya yok: {p}"}
    ext = p.suffix.lower().lstrip(".")
    mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"
    try:
        text = await _ocr_bytes(p.read_bytes(), mime,
                                instruction.strip() or "Bu gorseldeki tum metni cikar.")
        return {"status": "ok", "path": str(p), "text": text or "(metin yok)"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"OCR basarisiz: {exc}"}


def record_screen(seconds: float = 8.0, fps: int = 10) -> dict[str, Any]:
    """Ekrani belirtilen sure boyunca kaydeder (mp4). Uzun kayitlar buyuk dosya olusturur."""
    try:
        import cv2
        import mss
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Kayit icin opencv/mss gerekli: {exc}"}
    dur = max(1.0, min(120.0, float(seconds)))
    fps = max(2, min(30, int(fps)))
    _RECS.mkdir(parents=True, exist_ok=True)
    out = _RECS / f"{datetime.now():%Y%m%d_%H%M%S}.mp4"
    try:
        with mss.mss() as sct:
            mon = sct.monitors[get_settings().screen_monitor
                               if get_settings().screen_monitor < len(sct.monitors) else 1]
            w, h = mon["width"], mon["height"]
            vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
            frames = int(dur * fps)
            spf = 1.0 / fps
            for _ in range(frames):
                t0 = time.time()
                frame = np.asarray(sct.grab(mon))
                vw.write(cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR))
                dt = spf - (time.time() - t0)
                if dt > 0:
                    time.sleep(dt)
            vw.release()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Kayit basarisiz: {exc}"}
    return {"status": "kaydedildi", "path": str(out), "seconds": dur,
            "size_mb": round(out.stat().st_size / 1_048_576, 1)}
