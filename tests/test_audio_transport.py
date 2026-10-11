"""AudioTransport soyutlamasi: NetworkAudioTransport donanimsiz round-trip,
LocalAudioTransport arayuz uyumu (gercek PyAudio donanimina DOKUNMAZ)."""
import asyncio

from core.audio_transport import AudioTransport, LocalAudioTransport, NetworkAudioTransport
from config.settings import Settings


class _FakeAudioServer:
    """`net/audio_server.py::NetworkAudioServer` ile ayni arayuzu tasiyan sahte sunucu."""

    port = 8771

    def __init__(self) -> None:
        self._mic_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.sent: list[bytes] = []
        self._connected = True

    @property
    def client_connected(self) -> bool:
        return self._connected

    async def read_mic_chunk(self) -> bytes:
        return await self._mic_queue.get()

    async def send_speaker_chunk(self, data: bytes) -> None:
        if not self._connected:
            return
        self.sent.append(data)

    async def feed_mic(self, data: bytes) -> None:
        await self._mic_queue.put(data)


def _settings() -> Settings:
    return Settings(gemini_api_key="test-key")


def test_local_audio_transport_starts_closed():
    transport: AudioTransport = LocalAudioTransport(_settings())
    assert transport.is_open is False


def test_network_audio_transport_is_always_open_after_open():
    server = _FakeAudioServer()
    transport = NetworkAudioTransport(server)
    transport.open()  # fiziksel cihaz yok - hep basarili
    assert transport.is_open is True


def test_network_audio_transport_mic_round_trip():
    async def _run():
        server = _FakeAudioServer()
        transport = NetworkAudioTransport(server)
        transport.open()

        await server.feed_mic(b"\x01\x02\x03\x04")
        chunk = await transport.read_chunk(1024)
        assert chunk == b"\x01\x02\x03\x04"

    asyncio.run(_run())


def test_network_audio_transport_speaker_round_trip():
    async def _run():
        server = _FakeAudioServer()
        transport = NetworkAudioTransport(server)
        transport.open()

        await transport.write_chunk(b"\xaa\xbb")
        assert server.sent == [b"\xaa\xbb"]

    asyncio.run(_run())


def test_network_audio_transport_write_is_silent_drop_without_client():
    async def _run():
        server = _FakeAudioServer()
        server._connected = False
        transport = NetworkAudioTransport(server)
        transport.open()

        await transport.write_chunk(b"\xaa\xbb")  # istemci yok - sessizce dusmeli, hata yok
        assert server.sent == []

    asyncio.run(_run())


def test_network_audio_transport_close_and_shutdown_are_noop():
    server = _FakeAudioServer()
    transport = NetworkAudioTransport(server)
    transport.close()
    transport.shutdown()  # taban siniftaki varsayilan: close()'u cagirir, hata firlatmamali
