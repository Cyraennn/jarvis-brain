"""Mikrofon -> sunucu, sunucu -> hoparlor ses kopru (mevcut uzak ses kanali, port 8771).

`remote_client/run_remote_client.py`'deki akisin aynisi, istemci cekirdegiyle ayni surecte
calisacak sekilde sinifa alindi. Cerceve formati `net/audio_server.py` ile ORTAK sabitlerden
gelir (1 byte etiket + PCM16; 16 kHz mikrofon, 24 kHz hoparlor). Koparsa ustel geri
cekilmeyle yeniden baglanir. Sunucuda ayni anda tek ses istemcisi olabilir (409).
"""

from __future__ import annotations

import asyncio
import contextlib

from loguru import logger
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from client.core import backoff_delay
from config.settings import AudioConfig
from net.audio_server import TAG_MIC, TAG_SPEAKER


class AudioLink:
    def __init__(self, url: str, *, max_backoff: float = 30.0) -> None:
        self.url = url
        self.max_backoff = max_backoff
        self.audio = AudioConfig()
        self.connected = False
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        import pyaudio

        pya = pyaudio.PyAudio()
        attempt = 0
        try:
            while not self._stop.is_set():
                try:
                    await self._run_once(pya)
                    attempt = 0
                except InvalidStatus as exc:
                    attempt += 1
                    code = getattr(exc.response, "status_code", "?")
                    hint = {401: "token eslesmiyor", 409: "sunucuda zaten baska bir ses istemcisi var"}
                    logger.warning(f"Ses sunucusu reddetti: HTTP {code} ({hint.get(code, '')})")
                except (asyncio.CancelledError, KeyboardInterrupt):
                    raise
                except Exception as exc:  # noqa: BLE001 - kopma / ses cihazi hatasi -> tekrar dene
                    attempt += 1
                    logger.warning(f"Ses baglantisi sorunu: {exc!r}")
                self.connected = False
                delay = backoff_delay(max(1, attempt), cap=self.max_backoff)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
        finally:
            pya.terminate()

    async def _run_once(self, pya) -> None:  # noqa: ANN001
        a = self.audio
        fmt = 8  # pyaudio.paInt16
        mic = pya.open(format=fmt, channels=a.channels, rate=a.send_sample_rate,
                       input=True, frames_per_buffer=a.chunk_size)
        spk = pya.open(format=fmt, channels=a.channels, rate=a.receive_sample_rate, output=True)
        try:
            async with connect(self.url, max_size=None, open_timeout=15) as ws:
                self.connected = True
                logger.success("Ses kanali BAGLANDI - konusabilirsiniz.")

                async def send_mic() -> None:
                    while True:
                        data = await asyncio.to_thread(mic.read, a.chunk_size,
                                                       exception_on_overflow=False)
                        await ws.send(bytes([TAG_MIC]) + data)

                async def recv_speaker() -> None:
                    async for message in ws:
                        if isinstance(message, (bytes, bytearray)) and message and message[0] == TAG_SPEAKER:
                            await asyncio.to_thread(spk.write, bytes(message[1:]))

                async with asyncio.TaskGroup() as tg:
                    tg.create_task(send_mic())
                    tg.create_task(recv_speaker())
        finally:
            for stream in (mic, spk):
                with contextlib.suppress(Exception):
                    stream.stop_stream()
                    stream.close()
