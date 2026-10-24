"""JARVIS -> CYRAEN ad degisikligi: eski kurulumlar bozulmadan calismaya devam etmeli."""

from types import SimpleNamespace

from config.legacy_env import alias_legacy_env
from config.settings import Settings
from core import personas
from core.tts import speakable
from core.whatsapp_handler import _ADMIN_PREFIX_RE


def test_legacy_env_is_copied_to_new_name():
    env = {"JARVIS_WEB_PORT": "8770", "OTHER": "x"}
    assert alias_legacy_env(env) == ["CYRAEN_WEB_PORT"]
    assert env["CYRAEN_WEB_PORT"] == "8770"
    assert "CYRAEN_OTHER" not in env


def test_new_env_name_wins_over_legacy():
    env = {"JARVIS_WEB_PORT": "1", "CYRAEN_WEB_PORT": "2"}
    alias_legacy_env(env)
    assert env["CYRAEN_WEB_PORT"] == "2"


def test_saved_legacy_persona_key_maps_to_cyraen(tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path)
    (tmp_path / "persona.json").write_text('{"persona": "jarvis"}', encoding="utf-8")
    assert personas.load_active(settings).key == "cyraen"
    assert personas.get(settings, "friday").key == "friday"


def test_name_is_spoken_as_siren():
    assert speakable("Ben CYRAEN.") == "Ben Siren."
    assert speakable("C.Y.R.A.E.N. hazir") == "Siren hazir"
    assert speakable("CYRAEN'in sesi") == "Siren'in sesi"
    assert speakable("Cyraenx") == "Cyraenx"  # kelime sinirina dikkat


def test_whatsapp_admin_prefix_accepts_name_pronunciation_and_legacy():
    for text in ("cyraen durum", "/siren sessiz", "jarvis: yardim", "cyraen"):
        assert _ADMIN_PREFIX_RE.match(text), text
    for text in ("sirene gidiyorum", "cyraenx durum", "merhaba cyraen"):
        assert not _ADMIN_PREFIX_RE.match(text), text


def test_wake_phrase_follows_the_model_actually_loaded():
    base = Settings.model_construct()
    assert base.model_copy(update={"wake_word_model": "hey_jarvis"}).wake_phrase == "Hey Jarvis"
    custom = base.model_copy(update={"wake_word_model": "C:/modeller/hey_siren.onnx"})
    assert custom.wake_phrase == "Hey Siren"
