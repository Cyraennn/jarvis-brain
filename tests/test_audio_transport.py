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


# --------------------------------------------------- PC <-> telefon gecisi
class _FakeLocal(AudioTransport):
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.opened = False
        self.written: list[bytes] = []

    @property
    def is_open(self) -> bool:
        return self.opened

    def open(self, attempts: int = 6, delay: float = 2.0) -> None:
        if self.fail:
            raise RuntimeError("cihaz yok")
        self.opened = True

    def close(self) -> None:
        self.opened = False

    async def read_chunk(self, chunk_size: int) -> bytes:
        await asyncio.sleep(0)
        return b"pc"

    async def write_chunk(self, data: bytes) -> None:
        self.written.append(data)


def _switchable(local, server):
    from core.audio_transport import SwitchableAudioTransport

    t = SwitchableAudioTransport(local, server, receive_rate=24000, sample_width=2)
    t.open()
    return t


def test_switchable_uses_pc_until_phone_connects():
    server = _FakeAudioServer()
    server._connected = False
    local = _FakeLocal()
    t = _switchable(local, server)

    async def go():
        assert await t.read_chunk(10) == b"pc"
        await t.write_chunk(b"\x00\x00")
        server._connected = True
        await server.feed_mic(b"phone")
        assert await t.read_chunk(10) == b"phone"
        await t.write_chunk(b"\x01\x01")

    asyncio.run(go())
    assert local.written == [b"\x00\x00"]
    assert server.sent == [b"\x01\x01"]
    assert t.route == "phone"


def test_switchable_returns_to_pc_when_phone_drops_mid_read():
    server = _FakeAudioServer()
    local = _FakeLocal()
    t = _switchable(local, server)

    async def go():
        read = asyncio.create_task(t.read_chunk(10))  # telefon sessiz: bekler
        await asyncio.sleep(0.05)
        server._connected = False                     # telefon koptu
        return await asyncio.wait_for(read, 2)

    assert asyncio.run(go()) == b"pc"
    assert t.route == "pc"


def test_switchable_without_pc_device_still_serves_phone():
    server = _FakeAudioServer()
    t = _switchable(_FakeLocal(fail=True), server)  # PC cihazi acilamadi: hata firlatmaz
    assert t.is_open is True

    async def go():
        await server.feed_mic(b"phone")
        return await t.read_chunk(10)

    assert asyncio.run(go()) == b"phone"


def test_switchable_paces_phone_playback_in_real_time():
    import time

    server = _FakeAudioServer()
    t = _switchable(None, server)
    second = b"\x00" * 48000  # 24 kHz * 2 bayt = 1 sn ses

    async def go():
        start = time.monotonic()
        await t.write_chunk(second)
        return time.monotonic() - start

    elapsed = asyncio.run(go())
    assert 0.6 < elapsed < 1.0  # ~1 sn - 0,25 sn tampon
    assert server.sent == [second]
