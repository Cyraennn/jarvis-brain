"""Icerik paneli: video, Wikipedia, web sitesi, yerel belge, Spotify karti, haberler, fiyat
grafigi, 3B Izmir haritasi, hava durumu ve bilgi karti JARVIS penceresinin ICINDE acilir (beyin haritasinin / komuta grafinin yerinde).

Yuk (`payload`) `tools/panel_tools.py`'den gelir ve orada dogrulanmistir:
    {"kind": "video",   "video_id", "title", "subtitle", "url"}
    {"kind": "wiki",    "url", "title", "subtitle"}
    {"kind": "web",     "url", "title", "subtitle"}
    {"kind": "doc",     "path", "doc_type": "pdf|metin", "title", "subtitle"}
    {"kind": "spotify", "title", "subtitle"}
    {"kind": "news",    "items": [{title, source, published, url}], "url", "title", "subtitle"}
    {"kind": "chart",   "points": [[ts, deger]], "stats": {...}, "url", "title", "subtitle"}
    {"kind": "weather", "now": {...}, "days": [...], "title", "subtitle"}
    {"kind": "map",     "lat", "lon", "zoom", "label", "url", "title", "subtitle", "route"?: {coords, origin, destination, ...}}
    (harita komutlari {"kind": "map_control", "action"} panel acmaz: MainWindow -> `map_command`)
    {"kind": "info",    "body" (Markdown), "title", "subtitle"}

Web icerigi QtWebEngine (PySide6-Addons) ister; kurulu degilse icerik sistem tarayicisinda
acilir. Harita `web3d/` sayfasinin `?view=map` gorunumudur (derlenmemisse OSM tarayicida acilir). Metin belgeleri, Spotify karti, haber, grafik, hava ve bilgi karti yereldir
(`ui/widgets/panel_views.py`), ek paket istemez.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from loguru import logger
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.settings import APP_DIR
from ui import theme
from ui.widgets.panel_views import ChartView, InfoView, NewsView, WeatherView

_TAGS = {"video": "▶ YOUTUBE", "wiki": "W WIKIPEDIA", "web": "◎ WEB", "doc": "▤ BELGE", "spotify": "♫ SPOTIFY",
         "news": "▦ HABERLER", "chart": "◢ PİYASA", "weather": "☼ HAVA", "info": "◆ JARVIS",
         "map": "⌖ HARİTA"}
_MAX_TEXT_BYTES = 2 * 1024 * 1024
_VIDEO_CLOSE_DELAY_MS = 1200
_SPOTIFY_POLL_MS = 3000

StateFn = Callable[[], dict[str, Any]]
ControlFn = Callable[[str], dict[str, Any]]


def _load_webengine():  # noqa: ANN202
    """`PanelWebView` sinifi; QtWebEngine (PySide6-Addons) kurulu degilse None."""
    try:
        from ui.widgets.panel_web import PanelWebView
    except ImportError as exc:
        logger.warning(f"QtWebEngine yok ({exc}); panel icerigi tarayicida acilacak. "
                       "`pip install PySide6-Addons` ile kurulur.")
        return None
    return PanelWebView


def _map_page_url() -> str:
    """Derlenmis web3d sayfasinin yerel adresi; sayfa/QtWebEngine yoksa bos (harita tarayicida acilir)."""
    from ui.hud import boot3d

    return boot3d.serve() if boot3d.available() else ""


def _mmss(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 60}:{s % 60:02d}"


class SpotifyCard(QWidget):
    """Yerel "su an caliyor" karti. Oynatma Spotify cihazinda surer; kart Web API'den durumu
    okur ve onceki / duraklat-devam / sonraki komutlarini yollar."""

    _state_ready = Signal(dict)
    _cover_ready = Signal(str, bytes)

    def __init__(self, fetch_state: StateFn | None = None, control: ControlFn | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if fetch_state is None or control is None:
            from tools.spotify_tool import spotify_control, spotify_playback_state

            fetch_state = fetch_state or spotify_playback_state
            control = control or spotify_control
        self._fetch_state, self._control = fetch_state, control
        self._busy = False
        self._playing = False
        self._pos = self._dur = 0
        self._cover_url = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(8)
        lay.addStretch(1)
        self.cover = QLabel()
        self.cover.setObjectName("spotifyCover")
        self.cover.setFixedSize(240, 240)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setText("♫")
        lay.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        self.track = QLabel("Spotify")
        self.track.setObjectName("spotifyTrack")
        self.artist = QLabel("")
        self.artist.setObjectName("spotifyArtist")
        self.device = QLabel("")
        self.device.setObjectName("panelSub")
        for lbl in (self.track, self.artist, self.device):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        self.bar = QProgressBar()
        self.bar.setObjectName("spotifyBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setRange(0, 1000)
        lay.addWidget(self.bar)
        self.time = QLabel("")
        self.time.setObjectName("panelSub")
        self.time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.time)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self.prev_btn = self._button("◀◀", "Önceki", lambda: self._send("previous"))
        self.play_btn = self._button("▶", "Duraklat / devam", self._toggle)
        self.next_btn = self._button("▶▶", "Sonraki", lambda: self._send("next"))
        for b in (self.prev_btn, self.play_btn, self.next_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

        self._state_ready.connect(self.apply_state)
        self._cover_ready.connect(self._apply_cover)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_SPOTIFY_POLL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

    def _button(self, glyph: str, tip: str, slot: Callable[[], None]) -> QToolButton:
        b = QToolButton()
        b.setObjectName("spotifyBtn")
        b.setText(glyph)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(slot)
        return b

    # ------------------------------------------------------------- yasam dongusu
    def start(self) -> None:
        self._poll()
        self._poll_timer.start()
        self._tick_timer.start()

    def stop(self) -> None:
        self._poll_timer.stop()
        self._tick_timer.stop()

    # ---------------------------------------------------------- arka plan isleri
    def _emit(self, signal_name: str, *args: Any) -> None:
        try:
            getattr(self, signal_name).emit(*args)
        except RuntimeError:
            pass   # kart bu arada silindi

    def _poll(self) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._fetch, name="jarvis-spotify-card", daemon=True).start()

    def _fetch(self) -> None:
        try:
            state = self._fetch_state()
        except Exception as exc:  # noqa: BLE001 - kart asla cokmez
            state = {"error": f"{type(exc).__name__}: {exc}"}
        url = str(state.get("image") or "")
        if url and url != self._cover_url:
            try:
                import httpx

                data = httpx.get(url, timeout=8.0, follow_redirects=True).content
                self._emit("_cover_ready", url, data)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Spotify kapagi alinamadi: {exc!r}")
        self._emit("_state_ready", state)

    def _send(self, action: str) -> None:
        def run() -> None:
            try:
                self._control(action)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Spotify komutu basarisiz [{action}]: {exc!r}")
            self._busy = False
            self._fetch()

        threading.Thread(target=run, name="jarvis-spotify-card", daemon=True).start()

    def _toggle(self) -> None:
        self._send("pause" if self._playing else "resume")

    # ------------------------------------------------------------------ gorunum
    def apply_state(self, state: dict) -> None:
        self._busy = False
        if "error" in state:
            self.track.setText("Spotify'a ulaşılamadı")
            self.artist.setText(str(state["error"])[:140])
            self._playing = False
            self._refresh_progress()
            return
        if not state.get("active"):
            self.track.setText("Şu an bir şey çalmıyor")
            self.artist.setText("")
            self.device.setText("")
            self._playing = False
            self._pos = self._dur = 0
            self._refresh_progress()
            return
        self._playing = bool(state.get("playing"))
        self.track.setText(str(state.get("track") or ""))
        album = str(state.get("album") or "")
        self.artist.setText(" · ".join(x for x in (str(state.get("artist") or ""), album) if x))
        self.device.setText(str(state.get("device") or "").upper())
        self._pos, self._dur = int(state.get("progress_ms") or 0), int(state.get("duration_ms") or 0)
        self._refresh_progress()

    def _apply_cover(self, url: str, data: bytes) -> None:
        pm = QPixmap()
        if pm.loadFromData(data):
            self._cover_url = url
            self.cover.setPixmap(pm.scaled(self.cover.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                           Qt.TransformationMode.SmoothTransformation))

    def _tick(self) -> None:
        if self._playing and self._dur:
            self._pos = min(self._dur, self._pos + 1000)
            self._refresh_progress()

    def _refresh_progress(self) -> None:
        self.play_btn.setText("II" if self._playing else "▶")
        self.bar.setValue(int(1000 * self._pos / self._dur) if self._dur else 0)
        self.time.setText(f"{_mmss(self._pos)} / {_mmss(self._dur)}" if self._dur else "")


class ContentPanel(QFrame):
    closed = Signal()   # kullanici ✕'e basti ya da video bitti

    def __init__(self, parent: QWidget | None = None, *, storage_dir: Path | None = None,
                 spotify_state: StateFn | None = None, spotify_control: ControlFn | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("contentPanel")
        self._storage_dir = storage_dir or (APP_DIR / "data" / "panel_profile")
        self._spotify_fns = (spotify_state, spotify_control)
        self._payload: dict[str, Any] = {}
        self._web = None           # PanelWebView (tembel)
        self._web_tried = False
        self._spotify: SpotifyCard | None = None
        self._news_payload: dict[str, Any] | None = None   # haberden acilan sayfadan listeye donus

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        head = QFrame()
        head.setObjectName("panelHead")
        h = QHBoxLayout(head)
        h.setContentsMargins(12, 7, 8, 7)
        h.setSpacing(10)
        self.tag_label = QLabel("")
        self.tag_label.setObjectName("panelTag")
        h.addWidget(self.tag_label)
        self.title_label = QLabel("")
        self.title_label.setObjectName("panelTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        h.addWidget(self.title_label, 1)
        self.sub_label = QLabel("")
        self.sub_label.setObjectName("panelSub")
        h.addWidget(self.sub_label)
        self.back_btn = self._chip("◀ HABERLER", "Haber listesine dön", "hudChip")
        self.back_btn.clicked.connect(self._back_to_news)
        self.back_btn.hide()
        h.addWidget(self.back_btn)
        self.external_btn = self._chip("TARAYICIDA AÇ ↗", "İçeriği varsayılan uygulamada aç", "hudChip")
        self.external_btn.clicked.connect(self.open_external)
        h.addWidget(self.external_btn)
        self.close_btn = self._chip("✕", "Paneli kapat (Esc)", "hudChipDanger")
        self.close_btn.clicked.connect(self.closed)
        h.addWidget(self.close_btn)
        outer.addWidget(head)

        self._stack = QStackedWidget()
        self.message = QLabel("")
        self.message.setObjectName("panelMessage")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self._stack.addWidget(self.message)
        self.text_view = QPlainTextEdit()
        self.text_view.setObjectName("panelText")
        self.text_view.setReadOnly(True)
        self._stack.addWidget(self.text_view)
        self.news_view = NewsView()
        self.news_view.link_requested.connect(self._open_news_link)
        self.chart_view = ChartView()
        self.weather_view = WeatherView()
        self.info_view = InfoView()
        for view in (self.news_view, self.chart_view, self.weather_view, self.info_view):
            self._stack.addWidget(view)
        outer.addWidget(self._stack, 1)

    @staticmethod
    def _chip(text: str, tip: str, name: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName(name)
        b.setText(text)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    # ------------------------------------------------------------------ API
    @property
    def kind(self) -> str:
        return str(self._payload.get("kind", ""))

    def show_content(self, payload: dict[str, Any]) -> bool:
        """Icerigi panelde acar. Panelde gosterilemiyorsa (QtWebEngine yok) sistem
        tarayicisinda acar ve False doner."""
        # Harita acikken yeni yer: sayfa bosaltilmaz, kamera yerinde suzulur
        self.clear(keep_web=payload.get("kind") == "map" and self.kind == "map")
        self._payload = dict(payload)
        kind = self.kind
        tag = f"◆ {theme.branding()['name']}" if kind == "info" else _TAGS.get(kind, kind.upper())
        self.tag_label.setText(tag)
        self.title_label.setText(str(payload.get("title", "")))
        self.title_label.setToolTip(str(payload.get("title", "")))
        self.sub_label.setText(str(payload.get("subtitle", "")))
        self.external_btn.setVisible(bool(payload.get("url") or payload.get("path")))

        native = self._show_native(kind, payload)
        if native is not None:
            self._stack.setCurrentWidget(native)
            return True

        if kind == "spotify":
            if self._spotify is None:
                self._spotify = SpotifyCard(*self._spotify_fns)
                self._stack.addWidget(self._spotify)
            self._stack.setCurrentWidget(self._spotify)
            self._spotify.start()
            return True
        if kind == "doc" and payload.get("doc_type") == "metin":
            self.text_view.setPlainText(self._read_text(str(payload.get("path", ""))))
            self._stack.setCurrentWidget(self.text_view)
            return True

        web = self._web_view()
        if web is None:
            self.open_external()
            self._payload = {}
            return False
        if kind == "map":
            base = _map_page_url()
            if not base:
                self.open_external()
                self._payload = {}
                return False
            web.open_map(base, payload)
        elif kind == "video":
            web.play_video(str(payload.get("video_id", "")))
        elif kind == "wiki":
            web.open_url(str(payload.get("url", "")), pin=".wikipedia.org")
        elif kind == "web":
            web.open_url(str(payload.get("url", "")))
        elif kind == "doc":
            web.open_pdf(str(payload.get("path", "")))
        else:
            self._payload = {}
            return False
        self._stack.setCurrentWidget(web)
        return True

    def _show_native(self, kind: str, payload: dict[str, Any]) -> QWidget | None:
        """Yerel (web gorunumu gerektirmeyen) turleri doldurur; tur yerel degilse None."""
        if kind == "news":
            self._news_payload = dict(payload)
            self.news_view.set_items(list(payload.get("items") or []))
            return self.news_view
        if kind == "chart":
            self.chart_view.set_data(list(payload.get("points") or []), dict(payload.get("stats") or {}))
            return self.chart_view
        if kind == "weather":
            self.weather_view.set_data(dict(payload.get("now") or {}), list(payload.get("days") or []))
            return self.weather_view
        if kind == "info":
            self.info_view.set_body(str(payload.get("body", "")))
            return self.info_view
        return None

    def map_command(self, action: str) -> bool:
        """Acik haritaya kamera komutu (zoom_in / zoom_out / rotate / reset); harita acik degilse False."""
        return self.kind == "map" and self._web is not None and self._web.map_command(action)

    def _open_news_link(self, url: str, title: str) -> None:
        """Listeden secilen haberi panelde acar; web gorunumu yoksa tarayicida (liste yerinde kalir)."""
        news = self._news_payload
        if self._web_view() is None:
            QDesktopServices.openUrl(QUrl(url))
            return
        self.show_content({"kind": "web", "url": url, "title": title, "subtitle": "HABER"})
        self._news_payload = news
        self.back_btn.setVisible(news is not None)

    def _back_to_news(self) -> None:
        if self._news_payload is not None:
            self.show_content(self._news_payload)

    def clear(self, *, keep_web: bool = False) -> None:
        """Icerigi birakir: video/ses durur, Spotify karti sorgulamayi keser. `keep_web`: web
        sayfasi yerinde kalir (haritadan haritaya gecis)."""
        if self._web is not None and not keep_web:
            self._web.stop()
        if self._spotify is not None:
            self._spotify.stop()
        self.text_view.clear()
        self.news_view.clear()
        self.chart_view.clear()
        self.weather_view.clear()
        self.info_view.clear()
        self._news_payload = None
        self.back_btn.hide()
        self._payload = {}
        self._stack.setCurrentWidget(self.message)
        self.message.setText("")

    def open_external(self) -> None:
        path, url = self._payload.get("path"), self._payload.get("url")
        target = QUrl.fromLocalFile(str(path)) if path else QUrl(str(url or ""))
        if target.isValid() and not target.isEmpty():
            QDesktopServices.openUrl(target)

    # -------------------------------------------------------------- yardimcilar
    def _web_view(self):  # noqa: ANN202
        if not self._web_tried:
            self._web_tried = True
            cls = _load_webengine()
            if cls is not None:
                self._web = cls(self._storage_dir, self)
                self._web.video_ended.connect(self._on_video_ended)
                self._web.video_blocked.connect(self._on_video_blocked)
                self._stack.addWidget(self._web)
        return self._web

    @staticmethod
    def _read_text(path: str) -> str:
        try:
            with open(path, "rb") as fh:
                data = fh.read(_MAX_TEXT_BYTES + 1)
        except OSError as exc:
            return f"Belge okunamadı: {exc}"
        text = data[:_MAX_TEXT_BYTES].decode("utf-8", errors="replace")
        return text + ("\n\n… (belgenin devamı gösterilmiyor)" if len(data) > _MAX_TEXT_BYTES else "")

    def _on_video_ended(self) -> None:
        payload = self._payload
        # Bu arada baska icerik acildiysa kapatma
        QTimer.singleShot(_VIDEO_CLOSE_DELAY_MS, lambda: self._payload is payload and self.closed.emit())

    def _on_video_blocked(self, code: int) -> None:
        logger.info(f"YouTube oynatici videoyu panelde oynatmadi (hata {code}).")
        if self._web is not None:
            self._web.stop()
        self.message.setText("Bu video yalnızca YouTube'da izlenebiliyor efendim.\n“TARAYICIDA AÇ” ile açabilirsiniz.")
        self._stack.setCurrentWidget(self.message)
