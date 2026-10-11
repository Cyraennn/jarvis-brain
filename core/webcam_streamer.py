"""Thread-safe 'latest-frame' webcam yakalayici.

Kamera kendi arka plan thread'inde surekli okunur; sadece EN GUNCEL JPEG karesi
bellekte tutulur. Boylece beyin motoru istedigi anda gecikmesiz kare alabilir ve
yavas encode/okuma islemleri asyncio dongusunu tikamaz.
"""

from __future__ import annotations

import sys
import threading
from typing import Optional

import cv2
from loguru import logger


class WebcamStreamer:
    def __init__(
        self,
        index: int = 0,
        jpeg_quality: int = 70,
        width: int = 1280,
        height: int = 720,
        reopen_delay: float = 2.0,
    ) -> None:
        self._index = index
        self._jpeg_quality = int(max(1, min(100, jpeg_quality)))
        self._width = width
        self._height = height
        self._reopen_delay = reopen_delay

        self._latest: Optional[bytes] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ API

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="webcam-streamer", daemon=True
        )
        self._thread.start()
        logger.info(f"Webcam akisi baslatildi (index={self._index}).")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        with self._lock:
            self._latest = None
        logger.info("Webcam akisi durduruldu.")

    def get_latest_jpeg(self) -> Optional[bytes]:
        """En guncel JPEG karesini dondurur (yoksa None)."""
        with self._lock:
            return self._latest

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -------------------------------------------------------------- internal

    def _open_capture(self) -> cv2.VideoCapture:
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(self._index, backend)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _run(self) -> None:
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
        cap: Optional[cv2.VideoCapture] = self._open_capture()

        while not self._stop.is_set():
            if cap is None or not cap.isOpened():
                logger.warning("Kamera acilamadi, yeniden denenecek...")
                if cap is not None:
                    cap.release()
                if self._stop.wait(self._reopen_delay):
                    break
                cap = self._open_capture()
                continue

            ok, frame = cap.read()
            if not ok or frame is None:
                if self._stop.wait(0.1):
                    break
                # Ust uste okuma hatasi => kaynagi tazele
                cap.release()
                cap = self._open_capture()
                continue

            ok, buffer = cv2.imencode(".jpg", frame, encode_params)
            if ok:
                with self._lock:
                    self._latest = buffer.tobytes()

            if self._stop.wait(0.03):  # ~30 FPS ust siniri
                break

        if cap is not None:
            cap.release()
