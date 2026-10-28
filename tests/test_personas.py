"""Kisilik modlari (JARVIS / FRIDAY / ULTRON): secim, prompt, ses, robotik efekt, motor gecisi."""
import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from config.settings import get_settings
from core import brain_engine, personas
from core.brain_engine import BrainEngine, _PersonaSwitch
from core.voice_fx import UltronFx, make


@pytest.fixture()
def settings(tmp_path):
    s = get_settings().model_copy()
    s.data_dir = tmp_path
    return s


def test_selection_persists_and_unknown_falls_back_to_jarvis(settings):
    assert personas.load_active(settings).key == "jarvis"  # dosya yok
    personas.save_active(settings, "ultron")
    assert personas.load_active(settings).key == "ultron"
    (settings.data_dir / "persona.json").write_text("bozuk{", encoding="utf-8")
    assert personas.load_active(settings).key == "jarvis"
    assert personas.get(settings, "yok").key == "jarvis"


def test_each_persona_has_its_own_voice_and_only_ultron_is_robotic(settings):
    table = personas.modes(settings)
    assert [m.key for m in table.values()] == ["jarvis", "friday", "ultron"]
    assert len({m.voice_name for m in table.values()}) == 3
    assert table["jarvis"].voice_name == settings.voice_name
    assert [k for k, m in table.items() if m.audio_effect] == ["ultron"]
    settings.ultron_fx = False
    assert personas.get(settings, "ultron").audio_effect == ""


@pytest.mark.parametrize("key, marker", [
    ("jarvis", "Sen JARVIS'sin"),
    ("friday", "Sen FRIDAY'sin"),
    ("ultron", "Sen ULTRON'sun"),
])
def test_prompt_swaps_identity_but_keeps_capabilities(settings, key, marker):
    text = settings.load_system_prompt(key)
    assert text.startswith(marker)
    assert "YETENEKLER" in text and "send_email" in text  # arac kurallari herkeste ortak
    others = {"jarvis": "Sen JARVIS'sin", "friday": "Sen FRIDAY'sin", "ultron": "Sen ULTRON'sun"}
    assert not any(v in text for k, v in others.items() if k != key)


def test_ultron_prompt_still_obeys_in_the_end(settings):
    text = settings.load_system_prompt("ultron")
    assert "SONUNDA HER ZAMAN" in text and "onay al" in text


def test_missing_persona_file_falls_back_to_jarvis(settings):
    assert settings.load_system_prompt("bilinmeyen").startswith("Sen JARVIS'sin")


# ------------------------------------------------------------------ robotik ses

def _pcm(samples: np.ndarray) -> bytes:
    return samples.astype("<i2").tobytes()


def test_ultron_fx_keeps_length_and_range():
    fx = UltronFx()
    t = np.arange(4801) / 24_000
    loud = _pcm(np.sin(2 * np.pi * 180 * t) * 32767)
    out = fx.process(loud + b"\x01")  # tek bayt kuyrugu da korunur
    assert len(out) == len(loud) + 1
    assert fx.process(b"") == b""
    silence = _pcm(np.zeros(2400))
    fx.reset()
    assert fx.process(silence) == silence


def test_ultron_fx_is_continuous_across_chunks():
    t = np.arange(9600) / 24_000
    pcm = _pcm(np.sin(2 * np.pi * 150 * t) * 12000)
    whole = UltronFx().process(pcm)
    fx = UltronFx()
    parts = b"".join(fx.process(pcm[i:i + 1000]) for i in range(0, len(pcm), 1000))
    assert np.array_equal(np.frombuffer(whole, "<i2"), np.frombuffer(parts, "<i2"))


def test_ultron_fx_actually_changes_the_voice():
    t = np.arange(4800) / 24_000
    pcm = _pcm(np.sin(2 * np.pi * 200 * t) * 10000)
    assert UltronFx().process(pcm) != pcm
    assert make("") is None and isinstance(make("ultron"), UltronFx)


# ------------------------------------------------------------------ motor gecisi

def _engine(settings) -> BrainEngine:
    eng = BrainEngine.__new__(BrainEngine)
    eng.settings = settings
    eng.observer = SimpleNamespace(on_persona=lambda key: eng.events.append(key))
    eng.events = []
    eng.session = None
    eng._persona = personas.load_active(settings)
    eng._persona_switch = asyncio.Event()
    eng._fx = None
    eng._resume_handle = "eski-tutamak"
    eng._resume_saved_at = 0.0
    eng._resume_failures = 0
    eng._proactive_audio = False
    eng.settings.session_context_enabled = False
    return eng


def test_set_persona_drops_resume_and_applies_voice_prompt_and_fx(settings, monkeypatch):
    monkeypatch.setattr(brain_engine, "get_tools", lambda: [])
    eng = _engine(settings)
    eng.set_persona("friday")
    assert eng.persona == "friday" and eng.events == ["friday"]
    assert eng._resume_handle is None and eng._fx is None
    assert not eng._persona_switch.is_set()  # oturum yokken: bir sonraki baglantida uygulanir
    cfg = eng._build_config()
    assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == settings.friday_voice
    assert cfg.system_instruction.parts[0].text.startswith("Sen FRIDAY'sin")
    assert personas.load_active(settings).key == "friday"

    eng.session = object()
    eng.set_persona("ultron")
    assert eng._persona_switch.is_set() and isinstance(eng._fx, UltronFx)
    eng.set_persona("ultron")  # ayni secim: tekrar olay yok
    assert eng.events == ["friday", "ultron"]


def test_persona_switch_ends_the_session_task_group(settings):
    eng = _engine(settings)

    async def scenario():
        eng._persona_switch.set()
        with pytest.raises(_PersonaSwitch):
            await asyncio.wait_for(eng._watch_persona_switch(), 1)
        assert not eng._persona_switch.is_set()

    asyncio.run(scenario())


def test_run_loop_reconnects_immediately_without_counting_a_failure(settings, monkeypatch):
    eng = _engine(settings)
    eng._shutdown = asyncio.Event()
    eng.audio_transport = SimpleNamespace(open=lambda: None)
    eng._owns_webcam = eng._owns_screen = False
    calls = []

    async def fake_connect():
        calls.append(len(calls))
        if len(calls) == 1:
            raise BaseExceptionGroup("tg", [_PersonaSwitch()])
        eng._shutdown.set()

    async def no_probe():
        return None

    async def no_close():
        return None

    async def offline_check(**_):
        raise AssertionError("kisilik gecisi backoff/baglanti kontrolune girmemeli")

    eng._connect_and_run = fake_connect
    eng._probe_adb = no_probe
    eng.aclose = no_close
    monkeypatch.setattr("core.connectivity.is_online", offline_check)
    asyncio.run(asyncio.wait_for(eng.run(), 2))
    assert calls == [0, 1]
