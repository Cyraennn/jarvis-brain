"""Cevrimdisi sesli sohbet: yerel STT -> OfflineChat -> yerel TTS dongusu (sahte arka uclarla)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from core.brain_engine import BrainEngine
from core.events import EngineObserver
from core.offline_voice import LocalSTT, LocalTTS, OfflineVoice, resample_int16
from core.wake_word import WakeGate


class Rec(EngineObserver):
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_connection(self, status: str) -> None:
        self.events.append(("conn", status))

    def on_user_transcript(self, text: str, final: bool) -> None:
        self.events.append(("user", text))

    def on_state(self, state: str) -> None:
        self.events.append(("state", state))


class Transport:
    is_open = True

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.reads = 0

    async def read_chunk(self, _size: int) -> bytes:
        self.reads += 1
        await asyncio.sleep(0)
        return b"\x01\x00" * 8

    async def write_chunk(self, data: bytes) -> None:
        self.written.append(data)


class FakeSTT:
    """n. parcada bir cumle 'duyar'."""

    def __init__(self, script: dict[int, str], ok: bool = True) -> None:
        self.script, self.ok, self.fed, self.resets = script, ok, 0, 0
        self.available: bool | None = None

    def load(self) -> bool:
        self.available = self.ok
        return self.ok

    def reset(self) -> None:
        self.resets += 1

    def feed(self, _pcm: bytes) -> str | None:
        self.fed += 1
        return self.script.get(self.fed)


class FakeTTS:
    def __init__(self, ok: bool = True) -> None:
        self.ok, self.spoken = ok, []
        self.available: bool | None = None

    def load(self) -> bool:
        self.available = self.ok
        return self.ok

    def synthesize(self, text: str) -> bytes:
        self.spoken.append(text)
        return b"\x05\x00" * 4800  # 0.2 sn @ 24 kHz


class FakeChat:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def reply(self, text: str) -> str:
        self.asked.append(text)
        return "Saat 21:05, efendim."


def _engine(voice: OfflineVoice, *, enabled: bool = True) -> BrainEngine:
    eng = BrainEngine.__new__(BrainEngine)
    eng.settings = SimpleNamespace(
        audio=SimpleNamespace(chunk_size=8, send_sample_rate=16000,
                              receive_sample_rate=24000, sample_width=2),
        offline_voice_enabled=enabled, wake_word_threshold=0.5,
    )
    eng.observer = Rec()
    eng.audio_transport = Transport()
    eng._playback_active = asyncio.Event()
    eng._speaking = False
    eng._mic_muted = False
    eng._output_muted = False
    eng._wake_enabled = False
    eng._gate = WakeGate(window_s=8)
    eng._offline_chat = FakeChat()
    eng._offline_voice_io = voice
    eng._offline_voice_task = None
    eng._offline_listening = False
    eng._get_offline_chat = lambda: eng._offline_chat
    return eng


async def _until(cond, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        assert loop.time() < end, "kosul zamaninda saglanmadi"
        await asyncio.sleep(0.01)


def test_spoken_question_is_answered_aloud_then_session_takes_the_mic_back():
    async def run():
        stt, tts = FakeSTT({3: "saat kaç"}), FakeTTS()
        eng = _engine(OfflineVoice(stt, tts))
        eng._start_offline_voice()
        await _until(lambda: eng.audio_transport.written and not eng._playback_active.is_set())
        assert eng._offline_chat.asked == ["saat kaç"]
        assert tts.spoken == ["Saat 21:05, efendim."]
        assert b"".join(eng.audio_transport.written) == b"\x05\x00" * 4800
        assert ("conn", "offline-voice") in eng.observer.events
        assert ("user", "saat kaç") in eng.observer.events
        assert stt.resets >= 2  # basta + konustuktan sonra (kendi sesini cumle sanmasin)
        assert eng._offline_status() == "offline-voice"

        await eng._stop_offline_voice()  # internet geldi: canli oturum mikrofonu devralir
        assert eng._offline_voice_task is None and eng._offline_status() == "offline"
        reads = eng.audio_transport.reads
        await asyncio.sleep(0.05)
        assert eng.audio_transport.reads == reads  # artik kimse okumuyor

    asyncio.run(run())


def test_mic_is_ignored_while_cyraen_is_speaking_or_muted():
    async def run():
        stt = FakeSTT({1: "bir sey"})
        eng = _engine(OfflineVoice(stt, FakeTTS()))
        eng._mic_muted = True
        eng._start_offline_voice()
        await _until(lambda: eng.audio_transport.reads > 5)
        assert stt.fed == 0 and eng._offline_chat.asked == []
        await eng._stop_offline_voice()

    asyncio.run(run())


def test_output_muted_plays_nothing_but_still_answers():
    async def run():
        eng = _engine(OfflineVoice(FakeSTT({1: "saat kaç"}), FakeTTS()))
        eng._output_muted = True
        eng._start_offline_voice()
        await _until(lambda: eng._offline_chat.asked and not eng._playback_active.is_set()
                     and ("state", "idle") in eng.observer.events)
        assert eng.audio_transport.written == []
        await eng._stop_offline_voice()

    asyncio.run(run())


def test_missing_backend_falls_back_to_text_only_and_is_not_retried():
    async def run():
        voice = OfflineVoice(FakeSTT({}, ok=False), FakeTTS())
        eng = _engine(voice)
        eng._start_offline_voice()
        await _until(lambda: eng._offline_voice_task is None)
        assert voice.failed and eng._offline_status() == "offline"
        assert ("conn", "offline-voice") not in eng.observer.events
        eng._start_offline_voice()
        assert eng._offline_voice_task is None  # tekrar denenmez

    asyncio.run(run())


def test_not_started_when_disabled_or_no_local_model():
    async def run():
        eng = _engine(OfflineVoice(FakeSTT({}), FakeTTS()), enabled=False)
        eng._start_offline_voice()
        assert eng._offline_voice_task is None
        eng2 = _engine(OfflineVoice(FakeSTT({}), FakeTTS()))
        eng2._get_offline_chat = lambda: None  # Ollama kapali / devre disi
        eng2._start_offline_voice()
        assert eng2._offline_voice_task is None

    asyncio.run(run())


def test_resample_keeps_duration():
    pcm = (np.sin(np.linspace(0, 40, 22050)) * 8000).astype(np.int16).tobytes()
    out = resample_int16(pcm, 22050, 24000)
    assert len(out) == 24000 * 2
    assert resample_int16(pcm, 24000, 24000) is pcm and resample_int16(b"", 1, 2) == b""


def test_unavailable_backends_degrade_quietly(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_vosk(name, *a, **k):
        if name == "vosk":
            raise ImportError("yok")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_vosk)
    stt = LocalSTT(model_path=str(tmp_path / "yok"))
    assert stt.load() is False and stt.feed(b"\0\0" * 100) is None
    tts = LocalTTS(backend="piper", voice_path=tmp_path / "yok.onnx")
    assert tts.load() is False and tts.synthesize("merhaba") == b""


VOICE = Path(__file__).resolve().parents[1] / "data" / "piper" / "tr_TR-dfki-medium.onnx"


@pytest.mark.skipif(os.getenv("CYRAEN_LIVE_TESTS") != "1", reason="gercek vosk + Piper modelleri")
def test_live_piper_speech_is_understood_by_vosk():
    tts = LocalTTS(backend="piper", voice_path=VOICE, rate=24000)
    pcm = tts.synthesize("Yarın hangi derslerim var?")
    assert len(pcm) > 24000  # > 0.5 sn ses
    stt = LocalSTT()
    assert stt.load()
    heard = None
    data = resample_int16(pcm, 24000, 16000) + b"\0" * 32000
    for i in range(0, len(data), 2048):
        heard = stt.feed(data[i:i + 2048]) or heard
    assert heard and "ders" in heard
