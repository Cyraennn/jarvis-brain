"""Gizli deger katmani: keyring yoksa sessiz geri donus, varsa oncelik ve .env yedegi."""
import sys
import types

from config import secrets


def test_no_keyring_is_silent(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # import -> ImportError
    assert secrets.get_secret("X") is None
    assert secrets.set_secret("X", "1") is False


def test_keyring_roundtrip(monkeypatch):
    store = {}
    fake = types.SimpleNamespace(
        get_password=lambda svc, name: store.get((svc, name)),
        set_password=lambda svc, name, val: store.__setitem__((svc, name), val),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert secrets.set_secret("PIN", "1234") is True
    assert secrets.get_secret("PIN") == "1234"


def test_keyring_errors_do_not_raise(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no backend")

    fake = types.SimpleNamespace(get_password=boom, set_password=boom)
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert secrets.get_secret("PIN") is None
    assert secrets.set_secret("PIN", "1") is False


def test_persist_pin_prefers_keyring_and_never_touches_env_file(monkeypatch, tmp_path):
    from tools import adb_tool

    monkeypatch.setenv("CYRAEN_ADB_UNLOCK_PIN", "")  # teardown ortami geri yukler
    saved = {}
    monkeypatch.setattr(adb_tool, "set_secret", lambda n, v: saved.__setitem__(n, v) or True)
    monkeypatch.setattr(adb_tool, "APP_DIR", tmp_path)
    monkeypatch.setattr(adb_tool, "BASE_DIR", tmp_path)
    res = adb_tool._persist_unlock_pin("12-34 56")
    assert res["store"] == "keyring" and res["digits"] == 6
    assert saved["CYRAEN_ADB_UNLOCK_PIN"] == "123456"
    assert not (tmp_path / ".env").exists()


def test_persist_pin_validates_length(monkeypatch):
    from tools import adb_tool

    assert "error" in adb_tool._persist_unlock_pin("12")
