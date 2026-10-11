"""Ses I/O soyutlamasi: BrainEngine'in mikrofon/hoparlor kaynagini degistirilebilir yapar.

Iki uygulama:
  - `LocalAudioTransport` : bugunku davranis - PyAudio ile BU makinenin mikrofonu/
                             hoparloru (main.py, run_ui.py / masaustu uygulamasi).
  - `NetworkAudioTransport`: PyAudio kullanmaz - `net/audio_server.py::NetworkAudioServer`
                             uzerinden baglanan UZAK bir istemcinin mikrofon/hoparloru
                             (run_server.py / lab-sunucu modu).

BrainEngine, `_listen_audio`/`_play_audio`/`retry_audio`/`aclose` icinde dogrudan
PyAudio yerine bu arayuzu kullanir; iki taraf da ayni sozlesmeyi (16 kHz giris,
24 kHz cikis, int16 PCM, `AudioConfig.chunk_size` boyutunda parcalar) izler.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import pyaudio

    from config.settings import Settings

# pyaudio yalnizca LocalAudioTransport'ta (bu makinenin mikrofonu) gerekir; sunucuda
# (VPS, ag-ses modu) kurulu olmasi gerekmesin diye tembel import edilir.
_PYAUDIO_FORMAT = 8  # pyaudio.paInt16


class AudioTransport(abc.ABC):
    """Mikrofon/hoparlor kaynagi sozlesmesi. Tum metotlar motorun kendi
    (asyncio) dongusunden cagrilir; PyAudio gibi bloklayici IO icerenler
    kendi ic implementasyonunda `asyncio.to_thread` kullanmalidir."""

    @abc.abstractmethod
    def open(self, attempts: int = 6, delay: float = 2.0) -> None:
        """Kaynagi acmayi dener. Basarisizsa RuntimeError firlatir (motor
        bunu 'sessiz mod' olarak ele alir, bkz. BrainEngine.run())."""

    @abc.abstractmethod
    def close(self) -> None:
        """Akislari durdurur/kapatir (yeniden deneme icin de kullanilir). Idempotent olmali."""

    def shutdown(self) -> None:
        """Motor tamamen kapanirken BIR KEZ cagrilir - tam kaynak birakma.
        Varsayilan: `close()` ile ayni. Local implementasyon PyAudio motorunu
        da burada sonlandirir (retry sirasinda degil, sadece kesin kapanista)."""
        self.close()

    @property
    @abc.abstractmethod
    def is_open(self) -> bool:
        """Su an okuma/yazma icin hazir mi (mikrofon + hoparlor akisi acik)."""

    def reopen(self, attempts: int = 3, delay: float = 1.0) -> None:
        """Bozulan akislari kapatip yeniden acar (PortAudio hatasi / cihaz degisimi)."""
        self.close()
        self.open(attempts=attempts, delay=delay)

    @abc.abstractmethod
    async def read_chunk(self, chunk_size: int) -> bytes:
        """Bir sonraki mikrofon parcasini bekler ve dondurur (int16 PCM)."""

    @abc.abstractmethod
    async def write_chunk(self, data: bytes) -> None:
        """Bir hoparlor parcasini (int16 PCM) calar/gonderir."""


class LocalAudioTransport(AudioTransport):
    """Bugunku davranis: PyAudio ile bu makinenin mikrofonu/hoparloru."""

    def __init__(self, settings: "Settings") -> None:
        import pyaudio

        self._settings = settings
        self._pya = pyaudio.PyAudio()
        self._mic_stream: "pyaudio.Stream | None" = None
        self._spk_stream: "pyaudio.Stream | None" = None

    @property
    def is_open(self) -> bool:
        return self._mic_stream is not None and self._spk_stream is not None

    def open(self, attempts: int = 6, delay: float = 2.0) -> None:
        audio = self._settings.audio
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._mic_stream = self._pya.open(
                    format=_PYAUDIO_FORMAT,
                    channels=audio.channels,
                    rate=audio.send_sample_rate,
                    input=True,
                    frames_per_buffer=audio.chunk_size,
                )
                self._spk_stream = self._pya.open(
                    format=_PYAUDIO_FORMAT,
                    channels=audio.channels,
                    rate=audio.receive_sample_rate,
                    output=True,
                )
                logger.info(
                    f"Ses akislari acildi (giris {audio.send_sample_rate} Hz / "
                    f"cikis {audio.receive_sample_rate} Hz)."
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self.close()
                logger.warning(
                    f"Ses cihazi acilamadi (deneme {attempt}/{attempts}): {exc}"
                )
                if attempt < attempts:
                    time.sleep(delay)

        logger.error("Ses cihazlari acilamadi - tum denemeler basarisiz.")
        raise RuntimeError(f"PyAudio baslatilamadi: {last_exc}") from last_exc

    def close(self) -> None:
        for stream in (self._mic_stream, self._spk_stream):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.stop_stream()
                    stream.close()
        self._mic_stream = None
        self._spk_stream = None

    def reopen(self, attempts: int = 3, delay: float = 1.0) -> None:
        """PortAudio cihaz listesini baslangicta onbellege alir; varsayilan cihaz
        degistiyse (kulaklik takildi/cikti) eski motorla acilan akis yine olur.
        Bu yuzden motoru da sifirdan baslatip akislari yeniden acar."""
        import pyaudio

        self.close()
        with contextlib.suppress(Exception):
            self._pya.terminate()
        self._pya = pyaudio.PyAudio()
        self.open(attempts=attempts, delay=delay)

    def shutdown(self) -> None:
        """Akislari kapatir VE PyAudio motorunu sonlandirir (bir kez, motor kapanirken)."""
        self.close()
        with contextlib.suppress(Exception):
            self._pya.terminate()

    async def read_chunk(self, chunk_size: int) -> bytes:
        stream = self._mic_stream
        if stream is None:
            raise RuntimeError("Mikrofon akisi yok.")
        return await asyncio.to_thread(stream.read, chunk_size, exception_on_overflow=False)

    async def write_chunk(self, data: bytes) -> None:
        stream = self._spk_stream
        if stream is None:
            raise RuntimeError("Hoparlor akisi yok.")
        await asyncio.to_thread(stream.write, data)


class NetworkAudioTransport(AudioTransport):
    """PyAudio kullanmaz - uzak istemcinin (`net/audio_server.py`) mikrofon/
    hoparlorunu kullanir. `open()` her zaman basarili doner (fiziksel cihaz
    yok); gercek hazirlik `audio_server`'a bir istemcinin baglanmis olmasidir."""

    def __init__(self, audio_server: "NetworkAudioServerLike") -> None:
        self._server = audio_server

    @property
    def is_open(self) -> bool:
        return True  # motor tarafinda her zaman "acik" - gercek hazirlik client_connected

    def open(self, attempts: int = 6, delay: float = 2.0) -> None:
        logger.info(
            "Ag-ses modu: mikrofon/hoparlor uzak istemciden beklenecek "
            f"(port {self._server.port})."
        )

    def close(self) -> None:
        pass

    async def read_chunk(self, chunk_size: int) -> bytes:
        return await self._server.read_mic_chunk()

    async def write_chunk(self, data: bytes) -> None:
        await self._server.send_speaker_chunk(data)


class NetworkAudioServerLike:
    """Tip ipucu icin minimal protokol (gercek sinif: net/audio_server.py)."""

    port: int

    async def read_mic_chunk(self) -> bytes:  # pragma: no cover - protokol
        raise NotImplementedError

    async def send_speaker_chunk(self, data: bytes) -> None:  # pragma: no cover
        raise NotImplementedError

    @property
    def client_connected(self) -> bool:  # pragma: no cover
        raise NotImplementedError
