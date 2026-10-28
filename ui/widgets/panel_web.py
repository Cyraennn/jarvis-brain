"""Icerik panelinin web gorunumu (QtWebEngine): YouTube oynatici, Wikipedia/site sayfasi, PDF,
3B Izmir haritasi (`web3d/` `?view=map`). Harita koprusu: sayfa hazir olunca baslik
"jarvis:ready:<n>" olur; ardindan `window.jarvis.show({lat, lon, zoom, label, route?})` ve
`window.jarvis.command("zoom_in|zoom_out|rotate|reset")`. Rota cizgisi URL'ye sigmadigi icin
yuk her zaman hazir sinyalinden SONRA gonderilir.

PySide6-Addons ister. Kurulu degilse bu modul ice aktarilamaz; `content_panel` o durumda
icerigi sistem tarayicisinda acar. Bu yuzden yalnizca `content_panel._load_webengine`
uzerinden, tembel ice aktarilir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QWidget

from ui import theme

_Attr = QWebEngineSettings.WebAttribute

# Oynatici bir https sayfasinin icinde olmali: referer'siz gomme YouTube'da "hata 153" verir.
_PLAYER_BASE = QUrl("https://jarvis.local/")
# Durum Qt'ye sayfa basligi uzerinden bildirilir (QWebChannel gerekmez): bitti / sahibi engelledi.
_PLAYER_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="referrer" content="strict-origin-when-cross-origin">
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
#p,iframe{position:absolute;inset:0;width:100%;height:100%;border:0}</style></head>
<body><div id="p"></div>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
function onYouTubeIframeAPIReady(){
  new YT.Player('p',{host:'https://www.youtube-nocookie.com',videoId:'__ID__',width:'100%',height:'100%',
    playerVars:{autoplay:1,rel:0,playsinline:1,modestbranding:1},
    events:{onStateChange:function(e){if(e.data===0)document.title='jarvis:ended';
                                      else if(e.data===1)document.title='jarvis:playing';},
            onError:function(e){document.title='jarvis:error:'+e.data;}}});
}
</script></body></html>"""

_profile_ref: QWebEngineProfile | None = None


def _profile(storage_dir: Path) -> QWebEngineProfile:
    """Tek, kalici profil (site girisleri hatirlansin). Uygulama omrunce yasar: sayfalar
    profilden once silinmeli, bu yuzden profil gorunume degil QApplication'a baglidir."""
    global _profile_ref
    if _profile_ref is None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        prof = QWebEngineProfile("jarvis-panel", QApplication.instance())
        prof.setPersistentStoragePath(str(storage_dir / "storage"))
        prof.setCachePath(str(storage_dir / "cache"))
        _profile_ref = prof
    return _profile_ref


class _PanelPage(QWebEnginePage):
    def __init__(self, profile: QWebEngineProfile, parent: QWidget) -> None:
        super().__init__(profile, parent)
        self.pinned_suffix = ""          # doluysa: bu alan adinin disina giden baglantilar tarayicida acilir
        self.allowed_file = QUrl()       # panelin kendi actigi yerel dosya (PDF)
        self._popups: list[QWebEnginePage] = []

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802, ANN001
        if url.scheme() == "file":
            return url == self.allowed_file   # sayfalar yerel dosyalara gidemez
        if (is_main_frame and self.pinned_suffix
                and nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked):
            host = url.host().lower()
            if host != self.pinned_suffix.lstrip(".") and not host.endswith(self.pinned_suffix):
                QDesktopServices.openUrl(url)
                return False
        return True

    def createWindow(self, _type):  # noqa: N802, ANN001, ANN201
        """Yeni sekme/pencere isteyen baglantilar sistem tarayicisinda acilir."""
        popup = QWebEnginePage(self.profile(), self)
        self._popups.append(popup)

        def _handoff(url: QUrl) -> None:
            if url.scheme() in ("http", "https"):
                QDesktopServices.openUrl(url)
            if popup in self._popups:
                self._popups.remove(popup)
            popup.deleteLater()

        popup.urlChanged.connect(_handoff)
        return popup


class PanelWebView(QWebEngineView):
    video_ended = Signal()
    video_blocked = Signal(int)   # YouTube oynatici hata kodu (100/101/150/153)

    def __init__(self, storage_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video = False
        self._map = False          # harita sayfasi yuklu
        self._map_ready = False    # ... ve window.jarvis.show cagrilabilir
        self._map_pending: dict[str, Any] | None = None   # sayfa hazir olunca gonderilecek yuk
        self._page = _PanelPage(_profile(storage_dir), self)
        self._page.setBackgroundColor(QColor(theme.BG_SPACE))
        self.setPage(self._page)
        s = self._page.settings()
        s.setAttribute(_Attr.PlaybackRequiresUserGesture, False)   # video kendiliginden baslasin
        s.setAttribute(_Attr.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(_Attr.PdfViewerEnabled, True)
        self.titleChanged.connect(self._on_title)

    def _prepare(self, *, video: bool = False, pdf: bool = False, pin: str = "", file: QUrl | None = None,
                 map_: bool = False) -> None:
        self._video = video
        self._map, self._map_ready, self._map_pending = map_, False, None
        self._page.pinned_suffix = pin
        self._page.allowed_file = file or QUrl()
        self._page.settings().setAttribute(_Attr.PluginsEnabled, pdf)   # yerlesik PDF goruntuleyici

    def play_video(self, video_id: str) -> None:
        self._prepare(video=True)
        self.setHtml(_PLAYER_HTML.replace("__ID__", video_id), _PLAYER_BASE)

    def open_url(self, url: str, pin: str = "") -> None:
        self._prepare(pin=pin)
        self.load(QUrl(url))

    @staticmethod
    def _map_data(place: dict[str, Any]) -> dict[str, Any]:
        data = {"lat": float(place.get("lat", 0)), "lon": float(place.get("lon", 0)),
                "zoom": float(place.get("zoom", 12)), "label": str(place.get("label", ""))}
        if isinstance(place.get("route"), dict):
            data["route"] = place["route"]
        return data

    def _map_js(self, call: str, arg: Any) -> None:
        self._page.runJavaScript(f"window.jarvis && window.jarvis.{call}({json.dumps(arg)})")

    def open_map(self, base_url: str, place: dict[str, Any]) -> None:
        """Harita sayfasi hazirsa yeri/rotayi yerinde gosterir (kamera suzulur); degilse sayfayi
        yukler ve yuku hazir sinyaline kadar bekletir."""
        data = self._map_data(place)
        if self._map and self._map_ready:
            self._map_js("show", data)
            return
        if not self._map:
            self._prepare(map_=True)
            self.load(QUrl(f"{base_url}?view=map&embedded=1"))
        self._map_pending = data   # yuklenirken gelen yeni istek oncekinin yerine gecer

    def map_command(self, action: str) -> bool:
        """Acik haritaya kamera komutu; harita hazir degilse False."""
        if not (self._map and self._map_ready):
            return False
        self._map_js("command", action)
        return True

    def open_pdf(self, path: str) -> None:
        url = QUrl.fromLocalFile(path)
        self._prepare(pdf=True, file=url)
        self.load(url)

    def stop(self) -> None:
        """Sayfayi bosaltir (video/ses de durur)."""
        self._prepare()
        self.setUrl(QUrl("about:blank"))

    def _on_title(self, title: str) -> None:
        if self._map and title.startswith("jarvis:ready"):
            self._map_ready = True
            if self._map_pending is not None:
                self._map_js("show", self._map_pending)
                self._map_pending = None
            return
        if not self._video or not title.startswith("jarvis:"):
            return
        if title == "jarvis:ended":
            self.video_ended.emit()
        elif title.startswith("jarvis:error:"):
            try:
                self.video_blocked.emit(int(title.rsplit(":", 1)[1]))
            except ValueError:
                self.video_blocked.emit(0)
