"""Uygulama/site acma: dogrulama basarisiz olunca dogrudan aciliya dusme."""
import sys

import pytest

from tools import app_launcher as al

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows yolu")


@pytest.fixture()
def native(monkeypatch):
    launched = []
    monkeypatch.setattr(al, "_launch_native", lambda target: launched.append(target))
    monkeypatch.setattr(al, "_match_shortcut", lambda name: None)
    monkeypatch.setattr(al, "close_search", lambda: {"status": "kapatildi"})
    monkeypatch.setattr(al.time, "sleep", lambda *_: None)
    monkeypatch.setattr(al, "snapshot_windows", lambda: {})
    monkeypatch.setattr(al, "get_foreground_window", lambda: 0)
    return launched


def test_search_verified_returns_without_native_launch(monkeypatch, native):
    monkeypatch.setattr(al, "_search_mode_settings", lambda: (True, 0.0))
    monkeypatch.setattr(al, "search_and_open", lambda *a, **k: {"status": "ok"})
    monkeypatch.setattr(al, "_confirm_launched", lambda *a, **k: "Hesap Makinesi")
    r = al.open_application("hesap makinesi")
    assert r["verified"] is True and r["window"] == "Hesap Makinesi"
    assert native == []


def test_unverified_search_falls_back_to_native(monkeypatch, native):
    monkeypatch.setattr(al, "_search_mode_settings", lambda: (True, 0.0))
    monkeypatch.setattr(al, "search_and_open", lambda *a, **k: {"status": "ok"})
    monkeypatch.setattr(al, "_confirm_launched", lambda *a, **k: None)
    r = al.open_application("hesap makinesi")
    assert r["status"] == "acildi" and "dogrulanamadi" in r["note"]
    assert native == ["calc.exe"]


def test_failed_search_falls_back_to_native(monkeypatch, native):
    monkeypatch.setattr(al, "_search_mode_settings", lambda: (True, 0.0))
    monkeypatch.setattr(al, "search_and_open", lambda *a, **k: {"error": "panel acilmadi"})
    r = al.open_application("notepad")
    assert r["status"] == "acildi" and "basarisiz" in r["note"]
    assert native and native[0] == "notepad.exe"


def test_search_text_prefers_alias_then_shortcut(monkeypatch):
    monkeypatch.setattr(al, "_match_shortcut", lambda n: ("google chrome", al.Path("C:/x/Google Chrome.lnk")))
    assert al._search_text_for("hesap makinesi", "hesap makinesi") == "calc"
    assert al._search_text_for("krom", "krom") == "Google Chrome"


def test_confirm_launched_detects_new_window(monkeypatch):
    seq = iter([
        {},
        {1: ("Hesap Makinesi", "calculatorapp.exe", 999999)},
    ])
    monkeypatch.setattr(al, "snapshot_windows", lambda: next(seq))
    monkeypatch.setattr(al, "get_foreground_window", lambda: 0)
    monkeypatch.setattr(al.time, "sleep", lambda *_: None)
    assert al._confirm_launched({}, 0, timeout=5) == "Hesap Makinesi"


def test_confirm_launched_ignores_search_host_and_times_out(monkeypatch):
    monkeypatch.setattr(al, "snapshot_windows", lambda: {5: ("Ara", "searchhost.exe", 4242)})
    monkeypatch.setattr(al, "get_foreground_window", lambda: 5)
    monkeypatch.setattr(al.time, "sleep", lambda *_: None)
    ticks = iter(range(0, 1000))
    monkeypatch.setattr(al.time, "monotonic", lambda: next(ticks) * 0.5)
    assert al._confirm_launched({}, 0, timeout=1.0) is None


def test_open_website_falls_back_when_typing_fails(monkeypatch, native):
    import tools.keyboard_input as kb

    monkeypatch.setattr(al, "_browser_type_settings", lambda: (True, 0.0, 0.0))
    monkeypatch.setattr(kb, "type_in_browser", lambda *a, **k: {"error": "Tarayici on plana gelmedi"})
    r = al.open_website("youtube")
    assert r["status"] == "acildi" and r["via"] == "dogrudan"
    assert native == ["https://www.youtube.com"]


def test_browser_typing_never_opens_about_blank():
    """Regresyon: about:blank Windows'ta 'Birlikte ac' (openwith.exe) diyalogunu acip
    yazilanlari ona gonderiyordu."""
    import inspect

    import tools.keyboard_input as kb

    src = inspect.getsource(kb.type_in_browser)
    assert "about:blank" not in src.replace("NOT:", "").split("open_new_tab")[1].split("\n")[0]
    assert kb._BLANK_URL.startswith("https://")
