"""Cevrimdisi ses: yerel konusma tanima (vosk) + yerel seslendirme (Piper / Windows SAPI).

Internet yokken Gemini Live calismaz; `BrainEngine._offline_voice` mikrofonu buradaki
`LocalSTT`'ye verir, cikan metni `core/offline_chat.py` (yerel model) yanitlar ve yanit
`LocalTTS` ile hoparlorden okunur. Hicbir sey buluta gitmez.

Iki sinif da tembel yuklenir ve yuklenemezse `available=False` olur: motor bu durumda
sessizce yalniz YAZILI cevrimdisi sohbete duser.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from core.tts import speakable

MIN_TEXT_CHARS = 2  # vosk sessizlikte tek harflik sacma sonuclar uretebilir

_SAPI_SCRIPT = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and "
    "$_.VoiceInfo.Culture.Name -like ($env:JARVIS_TTS_LANG + '*') } | Select-Object -First 1;"
    "if ($null -eq $v) { exit 3 };"
    "$s.SelectVoice($v.VoiceInfo.Name);"
    "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
    "[int]$env:JARVIS_TTS_RATE, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
    "[System.Speech.AudioFormat.AudioChannel]::Mono);"
    "$s.SetOutputToWaveFile($env:JARVIS_TTS_OUT, $f);"
    "$s.Speak($env:JARVIS_TTS_TEXT);"
    "$s.Dispose()"
)


def resample_int16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Mono int16 PCM'i dogrusal aradegerle yeniden ornekler."""
    if src_rate == dst_rate or not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    count = max(1, int(round(samples.size * dst_rate / src_rate)))
    positions = np.linspace(0, samples.size - 1, count)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.int16).tobytes()


class LocalSTT:
    """vosk ile akan 16 kHz int16 PCM'den Turkce metin. `feed` cumle bitince metni dondurur."""

    def __init__(self, model_path: str = "", lang: str = "tr", sample_rate: int = 16_000) -> None:
        self.model_path = model_path
        self.lang = lang
        self.sample_rate = sample_rate
        self._model: Any = None
        self._rec: Any = None
        self.available: bool | None = None  # None = henuz denenmedi

    def load(self) -> bool:
        if self.available is not None:
            return self.available
        try:
            from vosk import Model, SetLogLevel

            SetLogLevel(-1)
            # yol verilmezse ~/.cache/vosk'taki dil modeli (yoksa ve internet varsa indirir)
            self._model = Model(self.model_path) if self.model_path else Model(lang=self.lang)
            self.reset()
            self.available = True
            logger.success(f"Cevrimdisi konusma tanima hazir (vosk, {self.lang}).")
        except BaseException as exc:  # noqa: BLE001 - vosk model bulamayinca SystemExit atabiliyor
            if isinstance(exc, KeyboardInterrupt):
                raise
            self.available = False
            logger.warning(f"Cevrimdisi konusma tanima yuklenemedi ({exc!r}); yalniz yazili sohbet.")
        return self.available

    def reset(self) -> None:
        """Yarim kalmis cumleyi at (JARVIS konustuktan sonra kendi sesini duymasin)."""
        if self._model is not None:
            from vosk import KaldiRecognizer

            self._rec = KaldiRecognizer(self._model, self.sample_rate)

    def feed(self, pcm: bytes) -> str | None:
        if not self.available or self._rec is None or not pcm:
            return None
        if not self._rec.AcceptWaveform(pcm):
            return None
        text = (json.loads(self._rec.Result()).get("text") or "").strip()
        return text if len(text) >= MIN_TEXT_CHARS else None


class LocalTTS:
    """Metni hoparlor formatinda (mono int16, `rate` Hz) PCM'e cevirir.

    backend: "piper" (noral, `voice_path` .onnx gerekir) | "sapi" (Windows'un kurulu Turkce
    sesi) | "auto" (Piper kullanilabiliyorsa o, degilse SAPI).
    """

    def __init__(
        self,
        backend: str = "auto",
        voice_path: Path | str | None = None,
        rate: int = 24_000,
        lang: str = "tr",
    ) -> None:
        self.backend = (backend or "auto").strip().lower()
        self.voice_path = Path(voice_path) if voice_path else None
        self.rate = rate
        self.lang = lang
        self._piper: Any = None
        self.active = ""  # yuklenen arka uc: "piper" | "sapi"
        self.available: bool | None = None

    def load(self) -> bool:
        if self.available is not None:
            return self.available
        if self.backend in ("auto", "piper") and self._load_piper():
            self.active = "piper"
        elif self.backend in ("auto", "sapi") and self._sapi(self.lang.upper()):
            self.active = "sapi"  # kisa bir deneme sentezi basarili oldu
        self.available = bool(self.active)
        if self.available:
            logger.success(f"Cevrimdisi seslendirme hazir ({self.active}).")
        else:
            logger.warning("Cevrimdisi seslendirme yok (Piper sesi / Turkce SAPI sesi bulunamadi).")
        return self.available

    def synthesize(self, text: str) -> bytes:
        """Bloklar (thread'de cagir). Basarisizlikta bos bytes."""
        clean = speakable(text)
        if not clean or not self.load():
            return b""
        try:
            return self._piper_pcm(clean) if self.active == "piper" else self._sapi(clean)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Cevrimdisi seslendirme basarisiz ({self.active}): {exc!r}")
            return b""

    # ------------------------------------------------------------------ piper

    def _load_piper(self) -> bool:
        if self.voice_path is None or not self.voice_path.exists():
            return False
        try:
            from piper import PiperVoice

            self._piper = PiperVoice.load(str(self.voice_path))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Piper yuklenemedi: {exc!r}")
            return False

    def _piper_pcm(self, text: str) -> bytes:
        out = bytearray()
        for chunk in self._piper.synthesize(text):
            out += resample_int16(chunk.audio_int16_bytes, chunk.sample_rate, self.rate)
        return bytes(out)

    # ------------------------------------------------------------------- sapi

    def _sapi(self, text: str) -> bytes:
        if sys.platform != "win32":
            return b""
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="jarvis_tts_")
        os.close(fd)
        env = {**os.environ, "JARVIS_TTS_TEXT": text, "JARVIS_TTS_OUT": path,
               "JARVIS_TTS_RATE": str(self.rate), "JARVIS_TTS_LANG": self.lang}
        # PowerShell 7 (pwsh) Windows'un yeni "OneCore" seslerini de (or. Turkce Tolga) gorur;
        # eski Windows PowerShell yalniz klasik SAPI seslerini listeler.
        shell = shutil.which("pwsh") or "powershell"
        try:
            done = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", _SAPI_SCRIPT],
                env=env, capture_output=True, timeout=60, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if done.returncode != 0:
                logger.debug(f"SAPI seslendirme kodu {done.returncode}: {done.stderr[-200:]!r}")
                return b""
            with wave.open(path, "rb") as wav:
                pcm = wav.readframes(wav.getnframes())
                return resample_int16(pcm, wav.getframerate(), self.rate)
        except (OSError, subprocess.SubprocessError, wave.Error, EOFError) as exc:
            logger.debug(f"SAPI seslendirme hatasi: {exc!r}")
            return b""
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class OfflineVoice:
    """STT + TTS cifti. Ikisi de yuklenebiliyorsa `load()` True doner."""

    def __init__(self, stt: LocalSTT, tts: LocalTTS) -> None:
        self.stt = stt
        self.tts = tts

    def load(self) -> bool:
        return bool(self.stt.load() and self.tts.load())

    @property
    def failed(self) -> bool:
        """Yukleme denendi ve basarisiz oldu (tekrar denemenin anlami yok)."""
        return self.stt.available is False or self.tts.available is False


def build_offline_voice(settings: Any) -> OfflineVoice:
    audio = settings.audio
    return OfflineVoice(
        LocalSTT(model_path=settings.offline_stt_model, sample_rate=audio.send_sample_rate),
        LocalTTS(backend=settings.offline_tts, voice_path=settings.offline_tts_voice,
                 rate=audio.receive_sample_rate),
    )
