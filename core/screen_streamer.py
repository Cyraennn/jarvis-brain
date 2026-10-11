"""Thread-safe 'latest-frame' ekran yakalayici (mss).

Ekran kendi arka plan thread'inde belirli araliklarla yakalanir; sadece EN GUNCEL
JPEG karesi bellekte tutulur. WebcamStreamer ile ayni arayuz.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import cv2
import numpy as np
from loguru import logger


class ScreenStreamer:
    def __init__(
        self,
        monitor: int = 0,
        jpeg_quality: int = 55,
        interval: float = 1.0,
        max_width: int = 1600,
    ) -> None:
        # mss monitor indeksi: 0 => tum ekranlar birlesik, 1 => birincil, 2.. => digerleri
        self._monitor = monitor
        self._jpeg_quality = int(max(1, min(100, jpeg_quality)))
        self._interval = max(0.2, interval)
        self._max_width = max_width

        self._latest: Optional[bytes] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ API
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="screen-streamer", daemon=True)
        self._thread.start()
        logger.info(f"Ekran akisi baslatildi (monitor={self._monitor}).")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        with self._lock:
            self._latest = None
        logger.info("Ekran akisi durduruldu.")

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -------------------------------------------------------------- internal
    def _run(self) -> None:
        try:
            import mss
        except Exception as exc:  # noqa: BLE001
            logger.error(f"mss yuklenemedi, ekran akisi devre disi: {exc}")
            return

        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                index = self._monitor if 0 <= self._monitor < len(monitors) else 0
                region = monitors[index]

                while not self._stop.is_set():
                    try:
                        shot = sct.grab(region)
                        frame = np.asarray(shot)  # BGRA
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                        if frame.shape[1] > self._max_width:
                            scale = self._max_width / frame.shape[1]
                            frame = cv2.resize(
                                frame,
                                (self._max_width, int(frame.shape[0] * scale)),
                                interpolation=cv2.INTER_AREA,
                            )
                        ok, buffer = cv2.imencode(".jpg", frame, encode_params)
                        if ok:
                            with self._lock:
                                self._latest = buffer.tobytes()
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(f"Ekran karesi alinamadi: {exc!r}")
                    if self._stop.wait(self._interval):
                        break
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Ekran akisi hatasi: {exc!r}")
