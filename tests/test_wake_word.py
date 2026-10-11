"""Uyandirma kelimesi: WakeGate durum makinesi + BrainEngine ses kapisi (sahte detektorle)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from core.brain_engine import BrainEngine
from core.events import EngineObserver
from core.wake_word import FRAME_SAMPLES, WakeGate, WakeWordDetector


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_gate_wake_touch_and_sleep():
    c = Clock()
    g = WakeGate(window_s=8, preroll_chunks=3, clock=c)
    assert not g.awake and g.transition() is None
    for i in range(5):
        g.remember(bytes([i]))
    assert g.wake() == [b"\x02", b"\x03", b"\x04"]  # son 3 parca
    assert g.awake and g.transition() is True and g.transition() is None
    c.t += 6
    g.touch()
    c.t += 6
    assert g.awake  # dokunus pencereyi uzatti
    c.t += 3
    assert not g.awake and g.transition() is False


def test_touch_does_not_wake_but_keep_awake_does():
    c = Clock()
    g = WakeGate(window_s=5, clock=c)
    g.touch()
    assert not g.awake
    g.keep_awake()
    assert g.awake


def test_max_awake_caps_extensions_from_background_speech():
    c = Clock()
    g = WakeGate(window_s=8, clock=c, max_awake_s=20)
    g.wake()
    for _ in range(10):  # ortamda surekli konusma: her 5 sn'de bir dokunus
        c.t += 5
        g.touch()
        g.keep_awake(fresh=False)  # model ortam sesine yanit veriyor: tavani sifirlamaz
    assert not g.awake  # 20 sn tavani asildi: yeniden "Hey JARVIS" gerekir


def test_reply_reopens_the_window_only_within_the_cap():
    c = Clock()
    g = WakeGate(window_s=8, clock=c, max_awake_s=20)
    g.wake()
    c.t += 12  # arac calisirken pencere kapandi
    assert not g.awake
    g.keep_awake(fresh=False)  # yanit geldi, tavan dolmadi: kullanici devam edebilir
    assert g.awake
    c.t += 30
    g.keep_awake(fresh=False)
    assert not g.awake


def test_uncapped_gate_keeps_old_behaviour():
    c = Clock()
    g = WakeGate(window_s=8, clock=c)
    g.keep_awake(fresh=False)
    assert g.awake


def test_keep_awake_from_sleep_starts_a_fresh_window():
    c = Clock()
    g = WakeGate(window_s=8, clock=c, max_awake_s=20)
    g.wake()
    c.t += 30
    assert not g.awake
    g.keep_awake()  # hatirlatici okundu: kullanici cevap verebilsin
    c.t += 7
    assert g.awake
    g.touch()
    c.t += 7
    assert g.awake  # yeni pencerenin kendi 20 sn'lik tavani var
    c.t += 7
    assert not g.awake


def test_detector_frames_and_unavailable():
    d = WakeWordDetector("hey_jarvis")
    assert d.score(b"\0\0" * 4000) == 0.0  # yuklenmemis -> 0

    seen: list[int] = []

    class FakeModel:
        def predict(self, frame):
            seen.append(frame.size)
            return {"hey_jarvis": 0.9 if len(seen) == 2 else 0.1}

        def reset(self):
            seen.clear()

    d.available, d._model = True, FakeModel()
    pcm = np.zeros(1024, dtype=np.int16).tobytes()
    assert d.score(pcm) == 0.0  # 1024 < 1280: kare tamamlanmadi
    assert d.score(pcm) == pytest.approx(0.1)  # 2048 -> 1 kare
    assert d.score(pcm) == pytest.approx(0.9)  # 3072 -> 2. kare
    assert seen == [FRAME_SAMPLES, FRAME_SAMPLES]
    d.reset()
    assert d._buf.size == 0 and seen == []


def test_detector_load_failure_disables(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_oww(name, *a, **k):
        if name.startswith("openwakeword"):
            raise ImportError("yok")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_oww)
    d = WakeWordDetector()
    assert d.load() is False and d.available is False


# ------------------------------------------------------------------ motor kapisi

class Rec(EngineObserver):
    def __init__(self) -> None:
        self.wakes: list[bool] = []

    def on_wake(self, awake: bool) -> None:
        self.wakes.append(awake)


class FakeDetector:
    def __init__(self, scores: list[float]) -> None:
        self.scores = list(scores)
        self.available = True
        self.resets = 0

    def load(self) -> bool:
        return True

    def score(self, pcm: bytes) -> float:
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self) -> None:
        self.resets += 1


def _engine(scores: list[float], clock: Clock) -> BrainEngine:
    eng = BrainEngine.__new__(BrainEngine)
    eng.settings = SimpleNamespace(wake_word_threshold=0.5)
    eng.observer = Rec()
    eng.out_queue = asyncio.Queue(maxsize=200)
    eng._wake_enabled = True
    eng._wake = FakeDetector(scores)
    eng._gate = WakeGate(window_s=8, preroll_chunks=4, clock=clock)
    return eng


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_engine_gate_sleeps_wakes_and_sends_preroll():
    async def run():
        c = Clock()
        eng = _engine([0.1, 0.2, 0.9], c)
        sent = []
        for i in range(3):  # uykuda: hicbiri gonderilmez, 3.'su uyandirir
            sent.append(await eng._gate_audio(b"x", f"b{i}", 0.0))
        assert sent == [False, False, False]
        assert [b for _, b in _drain(eng.out_queue)] == ["b0", "b1", "b2"]  # on-dolum
        assert eng.observer.wakes == [True] and eng._wake.resets == 1

        assert await eng._gate_audio(b"x", "b3", 0.2) is True  # uyanik: konusma gecer
        c.t += 7.9
        assert await eng._gate_audio(b"x", "b4", 0.0) is True  # 0.2 seviyesi pencereyi uzatmisti
        c.t += 8.1
        assert await eng._gate_audio(b"x", "b5", 0.0) is False  # sessizlik -> uyku
        assert eng.observer.wakes == [True, False]
        assert ("audio_end", None) in _drain(eng.out_queue)

    asyncio.run(run())


def test_set_wake_word_enabled_reports_state():
    eng = _engine([], Clock())
    eng.set_wake_word_enabled(False)
    assert eng.wake_word_enabled is False and eng.observer.wakes[-1] is True
    eng.set_wake_word_enabled(True)
    assert eng.observer.wakes[-1] is False and not eng._gate.awake


def test_unavailable_detector_means_always_listening():
    async def run():
        eng = _engine([], Clock())
        eng._wake.available = None

        def fail():
            eng._wake.available = False
            return False

        eng._wake.load = fail
        assert await eng._wake_ready() is False
        assert eng.observer.wakes == [True]

    asyncio.run(run())
