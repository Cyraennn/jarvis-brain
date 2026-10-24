"""3B zirh acilisi: kopru ayristirma, yerel sunucu ve basliksiz ortamda klasik acilisa dusme.

Sayfanin kendisi (WebGL) burada kosmaz; offscreen Qt'de QtWebEngine baslatilmaz.
"""
import urllib.error
import urllib.request

import pytest

from ui.hud import boot3d
from ui.hud.boot import BootOverlay


@pytest.mark.parametrize(
    ("title", "event"),
    [
        ("cyraen:ready:1", "ready"),
        ("cyraen:done:7", "done"),
        ("cyraen:error:2", "error"),
        ("CYRAEN", ""),
        ("", ""),
        ("baska:done:1", ""),
    ],
)
def test_event_of(title, event):
    assert boot3d.event_of(title) == event


def test_not_available_without_a_real_screen(qapp):
    # testler offscreen kosar: 3B acilis derlenmis olsa bile oynatilmaz
    assert qapp.platformName() == "offscreen"
    assert boot3d.available() is False


def test_hud_falls_back_to_classic_boot(qapp, main_window):
    if not hasattr(main_window, "_play_boot"):
        pytest.skip("klasik pencerede acilis katmani yok")
    main_window.show()
    qapp.processEvents()
    assert isinstance(main_window._boot, BootOverlay)


def test_show_armor_is_a_noop_when_unavailable(qapp, main_window):
    if not hasattr(main_window, "_show_armor"):
        pytest.skip("klasik pencerede 3B zirh yok")
    main_window._booted = True
    main_window._boot = None
    main_window._show_armor()
    assert main_window._boot is None


def test_static_server_serves_only_the_build_dir(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<title>zirh</title>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("gizli", encoding="utf-8")
    monkeypatch.setattr(boot3d, "_server", None)

    base = boot3d.serve(site)
    try:
        assert base.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(base, timeout=5) as res:
            assert b"zirh" in res.read()
            assert res.headers["Cache-Control"] == "no-store"
        # klasorun disina cikilamaz
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "../secret.txt", timeout=5)
        assert err.value.code == 404
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "%2e%2e/secret.txt", timeout=5)
        # sunucu yalnizca bu makineyi dinler
        assert boot3d._server.server_address[0] == "127.0.0.1"
    finally:
        boot3d._server.shutdown()
        boot3d._server.server_close()
