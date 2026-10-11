"""run_server.py: guvenlik kapisi (_check_remote_safety) ve web-kontrol koprusu
(_make_on_control) - tam asyncio akisini calistirmadan (bu manuel duman testiyle
yapilir, bkz. docs/remote_setup.md)."""
import pytest

from config.settings import Settings
from run_server import _check_remote_safety, _make_on_control


def _settings(**overrides) -> Settings:
    base = dict(gemini_api_key="test-key")
    base.update(overrides)
    return Settings(**base)


def test_remote_safety_requires_tokens_in_network_mode():
    settings = _settings(audio_mode="network", web_console_token="", remote_audio_token="")
    with pytest.raises(SystemExit):
        _check_remote_safety(settings)


def test_remote_safety_requires_both_tokens_not_just_one():
    settings = _settings(audio_mode="network", web_console_token="only-web", remote_audio_token="")
    with pytest.raises(SystemExit):
        _check_remote_safety(settings)


def test_remote_safety_passes_with_both_tokens():
    settings = _settings(audio_mode="network", web_console_token="w", remote_audio_token="a")
    _check_remote_safety(settings)  # raise etmemeli


def test_remote_safety_skips_check_in_local_mode():
    settings = _settings(audio_mode="local", web_console_token="", remote_audio_token="")
    _check_remote_safety(settings)  # local modda token zorunlulugu yok


class _FakeLoop:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def call_soon_threadsafe(self, fn, *args):
        self.calls.append((fn, args))
        fn(*args)  # testte senkron calistir - gercek loop'ta baska thread'den guvenli


class _FakeEngine:
    def __init__(self) -> None:
        self.mic_muted_calls: list[bool] = []
        self.output_muted_calls: list[bool] = []

    def set_mic_muted(self, muted: bool) -> None:
        self.mic_muted_calls.append(muted)

    def set_output_muted(self, muted: bool) -> None:
        self.output_muted_calls.append(muted)


def test_on_control_mic_toggle_marshals_through_loop():
    engine, loop = _FakeEngine(), _FakeLoop()
    on_control = _make_on_control(engine, loop)

    assert on_control("mic_off") == {"mic": False}
    assert engine.mic_muted_calls == [True]

    assert on_control("mic_on") == {"mic": True}
    assert engine.mic_muted_calls == [True, False]


def test_on_control_away_toggle_mutes_both_mic_and_output():
    engine, loop = _FakeEngine(), _FakeLoop()
    on_control = _make_on_control(engine, loop)

    assert on_control("away_on") == {"away": True}
    assert engine.mic_muted_calls == [True]
    assert engine.output_muted_calls == [True]

    assert on_control("away_off") == {"away": False}
    assert engine.mic_muted_calls == [True, False]
    assert engine.output_muted_calls == [True, False]


def test_on_control_unknown_action_returns_error():
    engine, loop = _FakeEngine(), _FakeLoop()
    on_control = _make_on_control(engine, loop)
    assert on_control("bilinmeyen-eylem") == {"error": "bilinmeyen"}
