"""Icerik paneli: merkez gorselin yerinde acilir/kapanir. Gercek Chromium ACILMAZ
(web gorunumu sahte); QtWebEngine'siz kurulumda tarayiciya dusme davranisi da sinanir."""
import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from ui.widgets import content_panel
from ui.widgets.content_panel import ContentPanel, SpotifyCard

VIDEO = {"kind": "video", "video_id": "dQw4w9WgXcQ", "title": "Fragman", "subtitle": "Kanal",
         "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
WIKI = {"kind": "wiki", "url": "https://tr.m.wikipedia.org/wiki/Ankara", "title": "Ankara", "subtitle": "Wikipedia · TR"}
STATE = {"ok": True, "active": True, "playing": True, "track": "Danza Kuduro", "artist": "Don Omar",
         "album": "Meet the Orphans", "device": "Sezai-PC", "progress_ms": 30_000, "duration_ms": 120_000, "image": ""}


class FakeWeb(QWidget):
    video_ended = Signal()
    video_blocked = Signal(int)

    def __init__(self, storage_dir, parent=None):
        super().__init__(parent)
        self.calls: list[tuple] = []

    def play_video(self, video_id):
        self.calls.append(("video", video_id))

    def open_url(self, url, pin=""):
        self.calls.append(("url", url, pin))

    def open_pdf(self, path):
        self.calls.append(("pdf", path))

    def open_map(self, base, place):
        self.calls.append(("map", base, place["label"]))

    def map_command(self, action):
        self.calls.append(("cmd", action))
        return True

    def stop(self):
        self.calls.append(("stop",))


@pytest.fixture()
def fake_web(monkeypatch):
    monkeypatch.setattr(content_panel, "_load_webengine", lambda: FakeWeb)


@pytest.fixture()
def no_web(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(content_panel, "_load_webengine", lambda: None)
    monkeypatch.setattr(content_panel.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    return opened


def _spotify_window_fns(win, calls=None):
    win._content_panel._spotify_fns = (lambda: STATE, lambda action: (calls or []).append(action) or {"ok": True})


def test_panel_replaces_center_and_closes(qapp, main_window, fake_web):
    win = main_window
    assert win._center_stack.currentWidget() is win._graph and not win._panel_open()
    win._observer.on_panel(VIDEO)            # motor thread'inden gelen olayin yolu: sinyal -> pencere
    qapp.processEvents()
    panel = win._content_panel
    assert win._panel_open() and panel.kind == "video"
    assert panel.title_label.text() == "Fragman" and panel.tag_label.text() == "▶ YOUTUBE"
    assert panel._web.calls[-1] == ("video", "dQw4w9WgXcQ")

    win._observer.on_panel(WIKI)             # yeni icerik oncekinin yerine gecer
    qapp.processEvents()
    assert panel._web.calls[-1] == ("url", WIKI["url"], ".wikipedia.org")

    win._observer.on_panel({"kind": "close"})
    qapp.processEvents()
    assert not win._panel_open() and win._center_stack.currentWidget() is win._graph
    assert panel._web.calls[-1] == ("stop",) and panel.kind == ""
    assert win._close_panel() is False       # zaten kapali


def test_close_button_and_video_end(qapp, main_window, fake_web, monkeypatch):
    win = main_window
    monkeypatch.setattr(content_panel, "_VIDEO_CLOSE_DELAY_MS", 0)
    win._on_panel(VIDEO)
    win._content_panel.close_btn.click()
    assert not win._panel_open()
    win._on_panel(VIDEO)
    win._content_panel._web.video_ended.emit()
    from tests.ui.conftest import wait_ms

    wait_ms(qapp, 30)
    assert not win._panel_open()             # video bitince zirh geri gelir


def test_blocked_video_shows_message(qapp, fake_web):
    panel = ContentPanel()
    assert panel.show_content(VIDEO)
    panel._web.video_blocked.emit(150)
    assert panel._stack.currentWidget() is panel.message and "YouTube" in panel.message.text()
    assert panel.kind == "video"             # "TARAYICIDA AÇ" hala bu videoyu acar


def test_text_document_is_plain_text(qapp, main_window, tmp_path, no_web):
    doc = tmp_path / "notlar.md"
    doc.write_text("# Baslik\n<script>alert(1)</script>", encoding="utf-8")
    win = main_window
    win._on_panel({"kind": "doc", "path": str(doc), "doc_type": "metin", "title": "notlar.md", "subtitle": "x"})
    panel = win._content_panel
    assert win._panel_open() and panel._stack.currentWidget() is panel.text_view
    assert panel.text_view.toPlainText() == "# Baslik\n<script>alert(1)</script>"   # yorumlanmaz
    assert no_web == []                      # metin belgesi QtWebEngine istemez


def test_without_webengine_opens_in_browser(qapp, main_window, no_web):
    win = main_window
    win._on_panel(VIDEO)
    assert no_web == [VIDEO["url"]] and not win._panel_open()
    win._on_panel({"kind": "doc", "path": "C:/x/a.pdf", "doc_type": "pdf", "title": "a.pdf"})
    assert no_web[-1] == "file:///C:/x/a.pdf" and not win._panel_open()


def test_spotify_card_in_panel(qapp, main_window, no_web):
    win = main_window
    _spotify_window_fns(win)
    win._on_panel({"kind": "spotify", "title": "Spotify", "subtitle": "Sezai-PC"})
    panel = win._content_panel
    assert win._panel_open() and isinstance(panel._stack.currentWidget(), SpotifyCard)
    assert not panel.external_btn.isVisibleTo(panel)
    win._close_panel()
    assert not panel._spotify._poll_timer.isActive()   # kapaninca Spotify'i sorgulamayi keser


def test_spotify_card_state_and_progress(qapp):
    card = SpotifyCard(lambda: STATE, lambda action: {"ok": True})
    card.apply_state(STATE)
    assert card.track.text() == "Danza Kuduro" and card.artist.text() == "Don Omar · Meet the Orphans"
    assert card.device.text() == "SEZAI-PC" and card.time.text() == "0:30 / 2:00" and card.bar.value() == 250
    card._tick()
    assert card.time.text() == "0:31 / 2:00"
    card.apply_state({**STATE, "playing": False})
    card._tick()
    assert card.time.text() == "0:30 / 2:00"           # duraklatilmisken ilerlemez
    card.apply_state({"ok": True, "active": False, "playing": False})
    assert "çalmıyor" in card.track.text() and card.time.text() == ""
    card.apply_state({"error": "Spotify yapilandirilmamis"})
    assert "ulaşılamadı" in card.track.text()


def test_escape_closes_panel_before_fullscreen(qapp, fake_web):
    from agents.qt_observer import QtOrchestratorObserver
    from tests.ui.conftest import FakeWebcam, make_settings
    from ui.hud.hud_window import HudWindow
    from ui.qt_observer import QtEngineObserver

    win = HudWindow(make_settings(), QtEngineObserver(), FakeWebcam(), orch_observer=QtOrchestratorObserver())
    try:
        left = []
        win._leave_fullscreen = lambda: left.append(True)
        win._on_panel(VIDEO)
        win._on_escape()
        assert not win._panel_open() and left == []
        win._on_escape()
        assert left == [True]
    finally:
        win.hide()
        win.deleteLater()
        qapp.processEvents()


MAP = {"kind": "map", "lat": 38.4378, "lon": 27.1428, "zoom": 15, "label": "Alsancak", "title": "Alsancak",
       "subtitle": "İZMİR · 3B HARİTA", "url": "https://www.openstreetmap.org/#map=15/38.43780/27.14280"}


def test_map_opens_in_web_view_and_flies_without_reload(qapp, fake_web, monkeypatch):
    monkeypatch.setattr(content_panel, "_map_page_url", lambda: "http://127.0.0.1:1/")
    panel = ContentPanel()
    assert panel.show_content(MAP) and panel.tag_label.text() == "⌖ HARİTA"
    web = panel._web
    assert web.calls == [("map", "http://127.0.0.1:1/", "Alsancak")]
    panel.show_content({**MAP, "label": "Bornova", "title": "Bornova"})
    assert ("stop",) not in web.calls and web.calls[-1][2] == "Bornova"   # sayfa bosaltilmadi
    panel.show_content({"kind": "web", "url": "https://example.com", "title": "x"})
    assert ("stop",) in web.calls                                          # baska ture geciste bosaltilir


def test_map_without_built_page_opens_osm_in_browser(qapp, fake_web, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(content_panel, "_map_page_url", lambda: "")
    monkeypatch.setattr(content_panel.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    panel = ContentPanel()
    assert not panel.show_content(MAP) and opened == [MAP["url"]]


def test_map_control_moves_open_map_or_opens_izmir(qapp, main_window, fake_web, monkeypatch):
    monkeypatch.setattr(content_panel, "_map_page_url", lambda: "http://127.0.0.1:1/")
    win = main_window
    win._on_panel({"kind": "map_control", "action": "zoom_in"})      # harita kapali: Izmir acilir
    panel = win._content_panel
    assert win._panel_open() and panel.kind == "map" and panel.title_label.text() == "İzmir"
    win._on_panel({"kind": "map_control", "action": "zoom_in"})      # acik: yalnizca kamera
    assert panel._web.calls[-1] == ("cmd", "zoom_in") and panel.title_label.text() == "İzmir"
