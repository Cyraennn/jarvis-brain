"""Ag uzerinden mikrofon/hoparlor ses akisi - lab sunucusu <-> ev istemcisi.

`run_server.py` (lab bilgisayari) `NetworkAudioServer`'i baslatir; `remote_client/
run_remote_client.py` (ev bilgisayari) buna baglanir. `core/audio_transport.py::
NetworkAudioTransport` bu sunucuyu `BrainEngine`'in mikrofon/hoparlor kaynagi olarak
kullanir - PyAudio motorun calistigi makinede DEGIL, istemcide acilir.

Cerceve formati (websockets binary mesaj): 1 byte etiket + PCM16 payload.
  0x01 = istemciden mikrofon (16 kHz, `AudioConfig.send_sample_rate`) sunucuya
  0x02 = sunucudan hoparlor (24 kHz, `AudioConfig.receive_sample_rate`) istemciye
  0x03 = ping/pong (bos payload, baglanti canliligi/gecikme olcumu)

Tek aktif istemci desteklenir (ev<->lab tek-kullanicili senaryo); biri baglıyken
ikinci bir baglanti denemesi HTTP 409 ile reddedilir. Auth deseni `web/console_server.py`
ile aynidir: token bossa sadece localhost'a izin verilir (bind zorla 127.0.0.1'e duser).
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
from urllib.parse import parse_qs, urlparse

from loguru import logger
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from web.event_bus import BUS

TAG_MIC = 0x01
TAG_SPEAKER = 0x02
TAG_PING = 0x03


class NetworkAudioServer:
    def __init__(self, *, port: int = 8771, bind: str = "0.0.0.0", token: str = "") -> None:
        self.port = int(port)
        self.token = token or ""
        # Token yoksa LAN/Tailscale'e ACMA: yalnizca bu PC (console_server.py ile ayni kural)
        self.bind = (bind or "0.0.0.0") if self.token else "127.0.0.1"
        self._mic_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=400)
        self._client: ServerConnection | None = None

    @property
    def client_connected(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------ auth
    def _authed(self, request: Request) -> bool:
        if not self.token:
            return True  # bind zaten 127.0.0.1'e dusurulmus
        qs = parse_qs(urlparse(request.path).query)
        given = qs.get("key", [""])[0]
        return hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8"))

    async def _process_request(
        self, connection: ServerConnection, request: Request
    ) -> "Response | None":
        if not self._authed(request):
            return connection.respond(401, "gecersiz veya eksik key")
        if self._client is not None:
            return connection.respond(409, "zaten bagli bir ses istemcisi var")
        return None  # handshake'e devam et

    # ------------------------------------------------------------- baglanti
    async def _handler(self, connection: ServerConnection) -> None:
        self._client = connection
        BUS.push("remote_audio", {"connected": True})
        logger.success("Uzaktan ses istemcisi baglandi.")
        try:
            async for message in connection:
                if not isinstance(message, (bytes, bytearray)) or not message:
                    continue
                tag, payload = message[0], bytes(message[1:])
                if tag == TAG_MIC:
                    try:
                        self._mic_queue.put_nowait(payload)
                    except asyncio.QueueFull:
                        logger.debug("Uzak mikrofon kuyrugu dolu, paket dusuruldu.")
                elif tag == TAG_PING:
                    with contextlib.suppress(ConnectionClosed):
                        await connection.send(bytes([TAG_PING]))
        except ConnectionClosed:
            pass
        finally:
            if self._client is connection:
                self._client = None
            BUS.push("remote_audio", {"connected": False})
            logger.warning("Uzaktan ses istemcisi baglantisi kesildi.")

    # --------------------------------------------------- AudioTransport arayuzu
    async def read_mic_chunk(self) -> bytes:
        return await self._mic_queue.get()

    async def send_speaker_chunk(self, data: bytes) -> None:
        client = self._client
        if client is None:
            return  # istemci yok - sessizce dusur (motor "ses yok" gibi davranmaya devam eder)
        with contextlib.suppress(ConnectionClosed):
            await client.send(bytes([TAG_SPEAKER]) + data)

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        if not self.token:
            logger.warning(
                "CYRAEN_REMOTE_AUDIO_TOKEN bos - uzak ses sunucusu SADECE localhost'a acik "
                "(ev bilgisayarindan baglanamazsiniz)."
            )
        async with serve(
            self._handler,
            self.bind,
            self.port,
            process_request=self._process_request,
            max_size=None,  # PCM parcalari kucuk; varsayilan 1MB limiti gereksiz
        ):
            logger.success(
                f"Uzak ses sunucusu dinliyor: ws://{self.bind}:{self.port} "
                f"(token {'ayarli' if self.token else 'YOK'})."
            )
            await asyncio.Future()  # TaskGroup iptal edene kadar calis
