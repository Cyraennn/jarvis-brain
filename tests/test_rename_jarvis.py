"""CYRAEN -> JARVIS geri donusu: kisa sureli CYRAEN adiyla yapilmis kurulumlar bozulmamali."""

from types import SimpleNamespace

from config.legacy_env import alias_legacy_env
from config.settings import Settings
from core import personas
from core.tts import speakable
from core.whatsapp_handler import _ADMIN_PREFIX_RE


def test_legacy_cyraen_env_is_copied_to_jarvis():
    env = {"CYRAEN_WEB_PORT": "8770", "OTHER": "x"}
    assert alias_legacy_env(env) == ["JARVIS_WEB_PORT"]
    assert env["JARVIS_WEB_PORT"] == "8770"
    assert "JARVIS_OTHER" not in env


def test_jarvis_env_name_wins_over_legacy():
    env = {"CYRAEN_WEB_PORT": "1", "JARVIS_WEB_PORT": "2"}
    alias_legacy_env(env)
    assert env["JARVIS_WEB_PORT"] == "2"


def test_saved_cyraen_persona_key_maps_to_jarvis(tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path)
    (tmp_path / "persona.json").write_text('{"persona": "cyraen"}', encoding="utf-8")
    assert personas.load_active(settings).key == "jarvis"
    assert personas.get(settings, "friday").key == "friday"


def test_name_is_not_rewritten_by_tts():
    assert speakable("Ben JARVIS.") == "Ben JARVIS."


def test_whatsapp_admin_prefix_accepts_jarvis_and_legacy_cyraen():
    for text in ("jarvis durum", "/jarvis sessiz", "jarvis: yardim", "cyraen durum", "jarvis"):
        assert _ADMIN_PREFIX_RE.match(text), text
    for text in ("jarvisx durum", "merhaba jarvis", "siren durum"):
        assert not _ADMIN_PREFIX_RE.match(text), text


def test_wake_phrase_follows_the_model_actually_loaded():
    base = Settings.model_construct()
    assert base.model_copy(update={"wake_word_model": "hey_jarvis"}).wake_phrase == "Hey Jarvis"
    custom = base.model_copy(update={"wake_word_model": "C:/modeller/hey_ozel.onnx"})
    assert custom.wake_phrase == "Hey Ozel"
