"""Panelin yerel gorunumleri: haber listesi, fiyat grafigi, hava durumu, bilgi karti.
QtWebEngine gerekmez; gercek Chromium ACILMAZ."""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.ui.test_content_panel import FakeWeb
from ui import theme
from ui.widgets import content_panel
from ui.widgets.content_panel import ContentPanel
from ui.widgets.panel_views import ChartView, InfoView, NewsView, WeatherView, fmt_number, fmt_when

NEWS = {"kind": "news", "title": "Gündem", "subtitle": "Google Haberler · 2 başlık",
        "url": "https://news.google.com/?hl=tr",
        "items": [{"title": "Birinci haber", "source": "AA", "published": "2026-10-11T22:09:00+03:00",
                   "url": "https://example.com/1"},
                  {"title": "İkinci haber", "source": "", "published": "", "url": "https://example.com/2"}]}
STATS = {"price": 12150.67, "currency": "TRY", "change": -2085.13, "change_pct": -14.65,
         "high": 14235.8, "low": 11947.2, "as_of": 1_791_800_000}
CHART = {"kind": "chart", "title": "BIST 100", "subtitle": "XU100.IS · 1 AY", "stats": STATS,
         "url": "https://finance.yahoo.com/quote/XU100.IS",
         "points": [[1_791_000_000 + i * 86_400, 14_000.0 - i * 90] for i in range(21)]}
WEATHER = {"kind": "weather", "title": "İzmir, Türkiye", "subtitle": "HAVA DURUMU",
           "now": {"sicaklik": 18.5, "hissedilen": 20.9, "nem": 91, "ruzgar_kmh": 1.1, "durum": "saganak"},
           "days": [{"gun": "2026-10-12", "min": 16.0, "max": 26.0, "durum": "saganak"},
                    {"gun": "2026-10-13", "min": 15.0, "max": 23.0, "durum": "gok gurultulu"},
                    {"gun": "bozuk", "min": None, "max": 21.0, "durum": "acik"}]}
INFO = {"kind": "info", "title": "Menemen tarifi", "subtitle": "BİLGİ KARTI",
        "body": "## Malzemeler\n- 3 yumurta\n\n![x](https://example.com/izle.png)\n\n[baglanti](https://example.com)"}


def _hover(widget, x: float, y: float) -> None:
    """Dugmesiz fare hareketi (offscreen'de QTest.mouseMove izleme olayini iletmiyor)."""
    pos = QPointF(x, y)
    QApplication.sendEvent(widget, QMouseEvent(QEvent.Type.MouseMove, pos, widget.mapToGlobal(pos),
                                               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                               Qt.KeyboardModifier.NoModifier))


@pytest.fixture()
def panel(qapp, tmp_path, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(content_panel, "_load_webengine", lambda: None)
    monkeypatch.setattr(content_panel.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    p = ContentPanel(storage_dir=tmp_path)
    p.resize(700, 520)
    p.opened = opened
    yield p
    p.deleteLater()


def test_number_and_time_formatting():
    assert fmt_number(12150.67) == "12.151"
    assert fmt_number(285.75) == "285,75"
    assert fmt_number(0.01234) == "0,0123"
    assert fmt_number(14.647, 2) == "14,65"
    assert fmt_when("2020-03-05T09:07:00+03:00") == "5 Mar 09:07"
    assert fmt_when("") == "" and fmt_when("bozuk") == ""


# ------------------------------------------------------------------ haberler
def test_news_list_opens_without_webengine(qapp, panel):
    assert panel.show_content(NEWS)
    view = panel._stack.currentWidget()
    assert isinstance(view, NewsView) and len(view.items) == 2
    assert view.items[0].title_label.text() == "Birinci haber"
    assert view.items[0].meta_label.text() == "AA · 11 Eki 22:09"
    assert view.items[1].meta_label.text() == ""               # kaynak/tarih yoksa bos
    assert panel.tag_label.text().endswith("HABERLER") and panel.external_btn.isVisibleTo(panel)
    assert panel.opened == []


def test_news_click_without_webengine_uses_browser_and_keeps_list(qapp, panel):
    panel.show_content(NEWS)
    panel.show()
    qapp.processEvents()
    QTest.mouseClick(panel.news_view.items[1], Qt.MouseButton.LeftButton, pos=QPoint(20, 10))
    assert panel.opened == ["https://example.com/2"]
    assert panel._stack.currentWidget() is panel.news_view     # liste yerinde kalir


def test_news_click_opens_article_in_panel_and_back_returns(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(content_panel, "_load_webengine", lambda: FakeWeb)
    panel = ContentPanel(storage_dir=tmp_path)
    panel.show_content(NEWS)
    assert not panel.back_btn.isVisibleTo(panel)
    panel.news_view.link_requested.emit("https://example.com/1", "Birinci haber")
    assert panel.kind == "web" and ("url", "https://example.com/1", "") in panel._web.calls
    assert panel.title_label.text() == "Birinci haber" and panel.back_btn.isVisibleTo(panel)
    panel.back_btn.click()
    assert panel.kind == "news" and len(panel.news_view.items) == 2
    assert not panel.back_btn.isVisibleTo(panel)
    panel.deleteLater()


# ------------------------------------------------------------------ grafik
def test_chart_shows_price_change_and_hover(qapp, panel):
    assert panel.show_content(CHART)
    view = panel._stack.currentWidget()
    assert isinstance(view, ChartView) and len(view.points) == 21
    assert view.price_text() == "12.151 TRY"
    assert view.change_text() == "▼ 2.085,13  (−%14,65)" and not view.rising()
    panel.show()
    qapp.processEvents()
    plot = view._plot()
    _hover(view, plot.right(), plot.center().y())
    assert view._hover == 20
    _hover(view, plot.left(), plot.center().y())
    assert view._hover == 0
    view.grab()                                                # imlecli cizim cokmez


def test_chart_rising_and_empty_data(qapp):
    view = ChartView()
    view.resize(500, 360)
    view.set_data([[1, 10.0], [2, 10.0]], {"price": 10.0, "currency": "USD", "change": 0.5, "change_pct": 5.0})
    assert view.rising() and view.change_text() == "▲ 0,50  (+%5,00)"
    view.grab()                                                # duz cizgi: sifira bolme yok
    view.set_data([], {})
    assert view.price_text() == "—" and view.change_text() == ""
    view.grab()                                                # bos veriyle cokmez
    view.deleteLater()


# ------------------------------------------------------------------ hava + bilgi
def test_weather_card_lists_valid_days(qapp, panel):
    assert panel.show_content(WEATHER)
    view = panel._stack.currentWidget()
    assert isinstance(view, WeatherView)
    assert view.temp_label.text() == "18°" and view.cond_label.text() == "Sağanak"
    assert view.detail_label.text() == "hissedilen 21°  ·  nem %91  ·  rüzgar 1 km/s"
    assert view.day_rows == [("Bugün", "16° / 26°"), ("Salı", "15° / 23°")]   # eksik gun atlanir
    assert not panel.external_btn.isVisibleTo(panel)           # harici karsiligi yok


def test_info_card_renders_markdown_without_remote_content(qapp, panel):
    assert panel.show_content(INFO)
    view = panel._stack.currentWidget()
    assert isinstance(view, InfoView)
    text = view.toPlainText()
    assert "Malzemeler" in text and "3 yumurta" in text and "##" not in text
    assert view.loadResource(2, "https://example.com/izle.png") is None        # uzak gorsel yuklenmez
    assert not view.openLinks() and not view.openExternalLinks()
    assert theme.ACCENT in view.document().defaultStyleSheet()
    assert panel.opened == []


def test_clear_empties_every_native_view(qapp, panel):
    for payload in (NEWS, CHART, WEATHER, INFO):
        panel.show_content(payload)
    panel.clear()
    assert panel.news_view.items == [] and panel.chart_view.points == []
    assert panel.weather_view.day_rows == [] and panel.info_view.toPlainText() == ""
    assert panel.kind == "" and panel._stack.currentWidget() is panel.message


def test_content_opens_in_place_of_graph_in_both_layouts(qapp, main_window):
    win = main_window
    win._on_panel(CHART)
    assert win._panel_open() and win._content_panel.kind == "chart"
    win._on_panel({"kind": "close"})
    assert not win._panel_open()
