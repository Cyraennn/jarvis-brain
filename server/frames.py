"""Istemciden gelen kamera/ekran karelerini motora sunan kaynak.

`BrainEngine(webcam=..., screen=...)` bu nesneleri `WebcamStreamer`/`ScreenStreamer`
yerine kullanir (motor yalnizca `get_latest_jpeg()` cagirir). Kare cok eskiyse (istemci
koptu / akis durdu) None doner - modele bayat goruntu gitmez.
"""

from __future__ import annotations

import threading
import time


class RemoteFrameSource:
    def __init__(self, name: str, max_age_s: float = 5.0) -> None:
        self.name = name
        self.max_age_s = max_age_s
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._ts = 0.0
        self.frames_received = 0

    # WebcamStreamer / ScreenStreamer ile uyumlu arayuz (motor sahiplenmedigi icin cagrilmaz)
    running = True

    def start(self) -> None:  # pragma: no cover - uyumluluk
        pass

    def stop(self) -> None:  # pragma: no cover - uyumluluk
        pass

    def update(self, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg = jpeg
            self._ts = time.monotonic()
            self.frames_received += 1

    def get_latest_jpeg(self) -> bytes | None:
        with self._lock:
            if self._jpeg is None or time.monotonic() - self._ts > self.max_age_s:
                return None
            return self._jpeg
