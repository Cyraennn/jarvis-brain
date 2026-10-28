"""Ekran / kamera karelerini sunucuya gonderir (motor goruntuyu istedikce).

Sunucu `stream_control {"screen":bool,"webcam":bool}` gonderir (motor `look_at_screen`
aracini cagirinca ya da kullanici ekran/kamera gorusunu acinca). Kare yakalama icin
mevcut `core/screen_streamer.py::ScreenStreamer` ve `core/webcam_streamer.py::WebcamStreamer`
aynen kullanilir; bu modul yalnizca en guncel kareyi aralikla sunucuya iletir.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from loguru import logger

from client.core import JarvisClient


class VisionLink:
    def __init__(self, client: JarvisClient, *, screen_interval: float = 1.2,
                 webcam_interval: float = 1.5) -> None:
        self.client = client
        self.screen_interval = screen_interval
        self.webcam_interval = webcam_interval
        self._want = {"screen": False, "webcam": False}
        self._streamers: dict[str, Any] = {}
        self.frames_sent = 0
        client.on_event("stream_control", self._on_stream_control)
        client.on_event("disconnected", lambda _: self._apply({"screen": False, "webcam": False}))

    def _on_stream_control(self, msg: dict[str, Any]) -> None:
        self._apply({"screen": bool(msg.get("screen")), "webcam": bool(msg.get("webcam"))})

    def _apply(self, want: dict[str, bool]) -> None:
        for source, on in want.items():
            if on == self._want.get(source):
                continue
            self._want[source] = on
            streamer = self._streamer(source) if on else self._streamers.get(source)
            if streamer is None:
                continue
            try:
                (streamer.start if on else streamer.stop)()
                logger.info(f"{'Ekran' if source == 'screen' else 'Kamera'} gorusu "
                            f"{'ACIK - kareler sunucuya gidiyor' if on else 'kapali'}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"{source} akisi degistirilemedi: {exc!r}")

    def _streamer(self, source: str) -> Any:
        if source in self._streamers:
            return self._streamers[source]
        try:
            from config.settings import get_settings

            s = get_settings()
            if source == "screen":
                from core.screen_streamer import ScreenStreamer

                obj = ScreenStreamer(monitor=s.screen_monitor, jpeg_quality=s.screen_jpeg_quality,
                                     interval=s.screen_interval)
            else:
                from core.webcam_streamer import WebcamStreamer

                obj = WebcamStreamer(index=s.webcam_index, jpeg_quality=s.webcam_jpeg_quality)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"{source} yakalayici kurulamadi: {exc!r}")
            obj = None
        self._streamers[source] = obj
        return obj

    async def run(self) -> None:
        last: dict[str, bytes | None] = {"screen": None, "webcam": None}
        tick = min(self.screen_interval, self.webcam_interval)
        elapsed = {"screen": 0.0, "webcam": 0.0}
        interval = {"screen": self.screen_interval, "webcam": self.webcam_interval}
        while True:
            await asyncio.sleep(tick)
            for source in ("screen", "webcam"):
                elapsed[source] += tick
                if not self._want[source] or elapsed[source] < interval[source]:
                    continue
                elapsed[source] = 0.0
                streamer = self._streamers.get(source)
                if streamer is None:
                    continue
                jpeg = streamer.get_latest_jpeg()
                if not jpeg or jpeg is last[source]:
                    continue
                last[source] = jpeg
                if await self.client.send_frame(source, jpeg):
                    self.frames_sent += 1

    def close(self) -> None:
        for streamer in self._streamers.values():
            if streamer is not None:
                with contextlib.suppress(Exception):
                    streamer.stop()
