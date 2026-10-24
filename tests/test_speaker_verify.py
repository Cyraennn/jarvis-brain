"""Konusmaci dogrulama: SpeakerGate, esik onerisi, profil ve motor kapisi (sahte dogrulayiciyla)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from core.brain_engine import BrainEngine
from core.events import EngineObserver
from core.speaker_verify import (
    SpeakerGate,
    SpeakerVerifier,
    save_profile,
    suggest_threshold,
)
from core.wake_word import WakeGate
from scripts.voice_enroll import leave_one_out


# ------------------------------------------------------------------ saf parcalar
def test_gate_emits_fixed_segments():
    g = SpeakerGate(segment_bytes=8)
    assert g.add(b"abc") is None and g.add(b"def") is None
    assert g.add(b"gh") == b"abcdefgh"
    assert g.add(b"x") is None  # yeni dilim sifirdan baslar


def test_gate_closes_after_consecutive_misses_only():
    g = SpeakerGate(segment_bytes=8, max_misses=2)
    assert g.record(False) is False
    assert g.record(True) is False  # eslesme sayaci sifirlar
    assert g.record(False) is False
    assert g.record(False) is True
    g.reset()
    assert g.misses == 0 and g.record(False) is False


def test_threshold_sits_between_own_voice_and_ambient():
    value, note = suggest_threshold([0.82, 0.78, 0.9], [0.3])
    assert 0.5 <= value < 0.78 and "0.78" in note


def test_threshold_warns_when_voice_does_not_separate():
    value, note = suggest_threshold([0.5, 0.6], [0.7])
    assert "UYARI" in note and 0.45 <= value <= 0.8
    assert "UYARI" in suggest_threshold([], [])[1]


def test_threshold_is_clamped():
    assert suggest_threshold([0.99, 0.98], [0.95])[0] == 0.8
    assert suggest_threshold([0.3], [0.0])[0] == 0.45


def test_leave_one_out_scores_consistency():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert leave_one_out([a, a, a]) == pytest.approx([1.0, 1.0, 1.0])
    assert leave_one_out([a, a, b])[2] == pytest.approx(0.0)
    assert leave_one_out([a]) == []


def test_profile_roundtrip_and_passive_without_profile(tmp_path):
    v = SpeakerVerifier(tmp_path / "model.onnx", tmp_path / "profile.npz")
    assert v.load() is False and v.available is False  # profil yok -> pasif
    assert v.score(b"\0\0" * 16000) == 0.0

    save_profile(tmp_path / "profile.npz",
                 [np.array([3.0, 0.0], np.float32), np.array([1.0, 0.0], np.float32)], 0.66)
    with np.load(tmp_path / "profile.npz") as data:
        assert data["embedding"].tolist() == [1.0, 0.0] and float(data["threshold"]) == pytest.approx(0.66)
    v2 = SpeakerVerifier(tmp_path / "model.onnx", tmp_path / "profile.npz")
    assert v2.load() is False  # profil var ama model dosyasi yok -> yine pasif, hata yok


def test_stored_threshold_used_unless_overridden(tmp_path, monkeypatch):
    save_profile(tmp_path / "p.npz", [np.array([1.0, 0.0], np.float32)], 0.7)
    monkeypatch.setattr(SpeakerVerifier, "load_model", lambda self: True)
    v = SpeakerVerifier(tmp_path / "m.onnx", tmp_path / "p.npz")
    assert v.load() and v.threshold == pytest.approx(0.7)
    v = SpeakerVerifier(tmp_path / "m.onnx", tmp_path / "p.npz", threshold=0.5)
    assert v.load() and v.threshold == 0.5


# ------------------------------------------------------------------ motor kapisi
class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class Detector:
    def __init__(self, scores) -> None:
        self.scores, self.available, self.resets = list(scores), True, 0

    def load(self) -> bool:
        return True

    def score(self, _pcm: bytes) -> float:
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self) -> None:
        self.resets += 1


class FakeVerifier:
    def __init__(self, scores, threshold: float = 0.6, available: bool = True) -> None:
        self.scores, self.threshold, self.available = list(scores), threshold, available
        self.seen: list[int] = []

    def load(self) -> bool:
        return bool(self.available)

    def score(self, pcm: bytes) -> float:
        self.seen.append(len(pcm))
        return self.scores.pop(0) if self.scores else 0.0


class Rec(EngineObserver):
    def __init__(self) -> None:
        self.wakes: list[bool] = []

    def on_wake(self, awake: bool) -> None:
        self.wakes.append(awake)


CHUNK = b"\x01\x00" * 4  # 8 bayt


def _engine(wake_scores, verifier, clock: Clock) -> BrainEngine:
    import collections

    eng = BrainEngine.__new__(BrainEngine)
    eng.settings = SimpleNamespace(wake_word_threshold=0.5)
    eng.observer = Rec()
    eng.out_queue = asyncio.Queue(maxsize=200)
    eng._wake_enabled = True
    eng._wake = Detector(wake_scores)
    eng._gate = WakeGate(window_s=8, preroll_chunks=4, clock=clock)
    eng._last_near_miss = float("-inf")
    eng._speaker = verifier
    eng._speaker_gate = SpeakerGate(segment_bytes=16)  # 2 parca = 1 dilim
    eng._recent_pcm = collections.deque(maxlen=3)
    return eng


async def _settle(eng: BrainEngine) -> None:
    if eng._speaker_task is not None:
        await eng._speaker_task


def test_stranger_cannot_wake_cyraen():
    async def run():
        c = Clock()
        v = FakeVerifier([0.30])
        eng = _engine([0.1, 0.9], v, c)
        assert await eng._gate_audio(CHUNK, "b0", 0.0) is False
        assert await eng._gate_audio(CHUNK, "b1", 0.0) is False  # wake skoru 0.9 ama ses izi 0.30
        assert not eng._gate.awake and eng.observer.wakes == [] and eng.out_queue.empty()
        assert eng._wake.resets == 1  # ayni cumle tekrar tetiklemesin
        assert v.seen == [16]  # son parcalar (uyanis sesi) degerlendirildi

    asyncio.run(run())


def test_owner_wakes_with_looser_threshold_for_the_short_phrase():
    async def run():
        eng = _engine([0.9], FakeVerifier([0.57]), Clock())  # 0.57 >= 0.60 - 0.05
        await eng._gate_audio(CHUNK, "b0", 0.0)
        assert eng._gate.awake and eng.observer.wakes == [True]

    asyncio.run(run())


def test_only_verified_speech_extends_the_window():
    async def run():
        c = Clock()
        eng = _engine([0.9], FakeVerifier([0.9, 0.2]), c)
        await eng._gate_audio(CHUNK, "b0", 0.0)  # uyanis (0.9 eslesti)
        c.t += 6
        for _ in range(2):  # bir dilim: baska biri konusuyor (0.2)
            assert await eng._gate_audio(CHUNK, "x", 0.3) is True
        await _settle(eng)
        c.t += 3  # uyanistan 9 sn sonra: dogrulanmamis ses pencereyi uzatmadi
        assert not eng._gate.awake

    asyncio.run(run())


def test_verified_speech_keeps_the_window_open():
    async def run():
        c = Clock()
        eng = _engine([0.9], FakeVerifier([0.9, 0.8]), c)
        await eng._gate_audio(CHUNK, "b0", 0.0)
        c.t += 6
        for _ in range(2):
            await eng._gate_audio(CHUNK, "x", 0.3)
        await _settle(eng)
        c.t += 3
        assert eng._gate.awake  # 0.8 eslesti -> pencere uzadi

    asyncio.run(run())


def test_two_unmatched_segments_close_the_gate_early():
    async def run():
        c = Clock()
        eng = _engine([0.9], FakeVerifier([0.9, 0.2, 0.1]), c)
        await eng._gate_audio(CHUNK, "b0", 0.0)
        for _ in range(2):  # iki dilim, ikisi de yabanci
            for _ in range(2):
                await eng._gate_audio(CHUNK, "x", 0.3)
            await _settle(eng)
        assert not eng._gate.awake  # 8 sn dolmadan kapandi
        assert await eng._gate_audio(CHUNK, "y", 0.3) is False  # artik modele gitmiyor
        assert eng.observer.wakes == [True, False]

    asyncio.run(run())


def test_without_profile_gate_behaves_as_before():
    async def run():
        c = Clock()
        v = FakeVerifier([], available=False)
        eng = _engine([0.9], v, c)
        await eng._gate_audio(CHUNK, "b0", 0.0)
        assert eng._gate.awake and v.seen == []  # ses izi sorulmadi
        c.t += 6
        await eng._gate_audio(CHUNK, "x", 0.3)  # seviye pencereyi uzatir (eski davranis)
        c.t += 6
        assert eng._gate.awake

    asyncio.run(run())


MODEL = Path(__file__).resolve().parents[1] / "data" / "voice" / "wespeaker_en_voxceleb_resnet34.onnx"
VOICE = Path(__file__).resolve().parents[1] / "data" / "piper" / "tr_TR-dfki-medium.onnx"


@pytest.mark.skipif(os.getenv("CYRAEN_LIVE_TESTS") != "1", reason="gercek ses izi modeli + iki TTS sesi")
def test_live_model_tells_two_voices_apart(tmp_path):
    from core.offline_voice import LocalTTS, resample_int16

    piper = LocalTTS(backend="piper", voice_path=VOICE)
    other = LocalTTS(backend="sapi")

    def say(tts, text):
        return resample_int16(tts.synthesize(text), 24000, 16000)

    enroll = SpeakerVerifier(MODEL, tmp_path / "p.npz")
    assert enroll.load_model()
    clips = [enroll.embed(say(piper, t)) for t in (
        "Bugün hava çok güzel, dışarı çıkıp biraz yürümek istiyorum.",
        "Yarın sabah dokuzda dersim var, bana hatırlatır mısın?", "Hey Cyraen")]
    save_profile(tmp_path / "p.npz", clips, 0.7)

    v = SpeakerVerifier(MODEL, tmp_path / "p.npz")
    assert v.load()
    same = v.score(say(piper, "Müzik çalar mısın, sonra da sesi kısar mısın?"))
    diff = v.score(say(other, "Müzik çalar mısın, sonra da sesi kısar mısın?"))
    assert same >= v.threshold > diff, (same, diff)
