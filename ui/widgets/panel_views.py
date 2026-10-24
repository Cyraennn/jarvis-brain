"""Icerik panelinin yerel gorunumleri: haber listesi, fiyat grafigi, hava durumu, bilgi karti.

Hepsi saf Qt'dir (QtWebEngine gerektirmez). Veri `tools/panel_tools.py`'den dogrulanmis
olarak gelir; burada yalnizca cizilir.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QTextDocument
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.hud.stat_cards import _WEATHER_TR, DAYS_TR, MONTHS_TR

_MONTHS_SHORT = tuple(m[:3] for m in MONTHS_TR)


def fmt_number(value: float, decimals: int | None = None) -> str:
    """Turkce sayi bicimi (1.234,56). Ondalik verilmezse buyukluge gore secilir."""
    if decimals is None:
        decimals = 0 if abs(value) >= 10_000 else 2 if abs(value) >= 1 else 4
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_when(iso: str) -> str:
    """ISO zaman -> "22:09" (bugun) ya da "11 Eki 22:09"."""
    try:
        at = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    if at.date() == datetime.now(at.tzinfo).date():
        return at.strftime("%H:%M")
    return f"{at.day} {_MONTHS_SHORT[at.month - 1]} {at:%H:%M}"


def _label(text: str, name: str, *, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


# ==================================================================== haberler
class _NewsItem(QFrame):
    clicked = Signal()

    def __init__(self, index: int, item: dict[str, Any]) -> None:
        super().__init__()
        self.setObjectName("newsItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(14)
        row.addWidget(_label(f"{index:02d}", "newsIndex"), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title_label = _label(str(item.get("title", "")), "newsTitle", wrap=True)
        col.addWidget(self.title_label)
        meta = " · ".join(x for x in (str(item.get("source", "")), fmt_when(str(item.get("published", "")))) if x)
        self.meta_label = _label(meta, "newsMeta")
        col.addWidget(self.meta_label)
        row.addLayout(col, 1)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class NewsView(QScrollArea):
    """Kaydirilabilir baslik kartlari; karta tiklaninca haberin adresi istenir."""

    link_requested = Signal(str, str)   # url, baslik

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panelScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("panelScrollBody")
        self._lay = QVBoxLayout(body)
        self._lay.setContentsMargins(16, 14, 16, 14)
        self._lay.setSpacing(8)
        self._lay.addStretch(1)
        self.setWidget(body)
        self.items: list[_NewsItem] = []

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.clear()
        for i, item in enumerate(items, 1):
            card = _NewsItem(i, item)
            url, title = str(item.get("url", "")), str(item.get("title", ""))
            card.clicked.connect(lambda u=url, t=title: self.link_requested.emit(u, t))
            self._lay.insertWidget(self._lay.count() - 1, card)
            self.items.append(card)
        self.verticalScrollBar().setValue(0)

    def clear(self) -> None:
        for card in self.items:
            self._lay.removeWidget(card)
            card.deleteLater()
        self.items = []


# ====================================================================== grafik
class ChartView(QWidget):
    """Fiyat grafigi: ustte son fiyat + donem degisimi, altta cizgi/alan grafigi. Fare ile
    uzerine gelinen noktanin tarihi ve degeri gosterilir."""

    PAD_L, PAD_R, PAD_T, PAD_B = 22, 76, 112, 34

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.points: list[tuple[int, float]] = []
        self.stats: dict[str, Any] = {}
        self._hover: int | None = None

    def set_data(self, points: list, stats: dict[str, Any]) -> None:
        self.points = [(int(t), float(v)) for t, v in points or []]
        self.stats = dict(stats or {})
        self._hover = None
        self.update()

    def clear(self) -> None:
        self.set_data([], {})

    # --------------------------------------------------------------- metinler
    def rising(self) -> bool:
        return float(self.stats.get("change", 0.0)) >= 0

    def price_text(self) -> str:
        if "price" not in self.stats:
            return "—"
        return f"{fmt_number(float(self.stats['price']))} {self.stats.get('currency', '')}".strip()

    def change_text(self) -> str:
        if "change" not in self.stats:
            return ""
        change, pct = float(self.stats["change"]), float(self.stats.get("change_pct", 0.0))
        arrow = "▲" if change >= 0 else "▼"
        # kusurat fiyatla ayni duyarlilikta: 49,32'lik kurda 0,06; 12.151'lik endekste 2.085,13
        decimals = 4 if abs(float(self.stats.get("price", 1.0))) < 1 else 2
        return (f"{arrow} {fmt_number(abs(change), decimals)}  "
                f"({'+' if change >= 0 else '−'}%{fmt_number(abs(pct), 2)})")

    def _time_text(self, ts: int, *, with_clock: bool) -> str:
        at = datetime.fromtimestamp(ts)
        day = f"{at.day} {_MONTHS_SHORT[at.month - 1]}"
        return f"{day} {at:%H:%M}" if with_clock else f"{day} {at.year}"

    def _intraday(self) -> bool:
        return len(self.points) > 1 and self.points[-1][0] - self.points[0][0] < 8 * 86_400

    # ---------------------------------------------------------------- geometri
    def _plot(self) -> QRectF:
        return QRectF(self.PAD_L, self.PAD_T, max(10.0, self.width() - self.PAD_L - self.PAD_R),
                      max(10.0, self.height() - self.PAD_T - self.PAD_B))

    def _range(self) -> tuple[float, float]:
        values = [v for _t, v in self.points]
        lo, hi = min(values), max(values)
        pad = (hi - lo) * 0.08 or abs(hi) * 0.01 or 1.0
        return lo - pad, hi + pad

    def _xy(self, i: int, plot: QRectF, lo: float, hi: float) -> QPointF:
        x = plot.left() + plot.width() * i / max(1, len(self.points) - 1)
        y = plot.bottom() - plot.height() * (self.points[i][1] - lo) / (hi - lo)
        return QPointF(x, y)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        if len(self.points) < 2:
            return
        plot = self._plot()
        k = (event.position().x() - plot.left()) / plot.width()
        self._hover = max(0, min(len(self.points) - 1, round(k * (len(self.points) - 1))))
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = None
        self.update()

    # ------------------------------------------------------------------ cizim
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(theme.ACCENT if self.rising() else theme.BAD)
        text, dim, faint = QColor(theme.TEXT), QColor(theme.TEXT_DIM), QColor(theme.TEXT_FAINT)

        f = QFont(p.font())
        f.setPointSize(26)
        f.setBold(True)
        p.setFont(f)
        p.setPen(text)
        p.drawText(QRectF(self.PAD_L, 16, self.width() - 2 * self.PAD_L, 44),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.price_text())
        f.setPointSize(11)
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(self.PAD_L, 62, self.width() - 2 * self.PAD_L, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.change_text())
        if "high" in self.stats:
            f.setPointSize(9)
            f.setBold(False)
            p.setFont(f)
            p.setPen(dim)
            hilo = (f"EN YÜKSEK  {fmt_number(float(self.stats['high']))}      "
                    f"EN DÜŞÜK  {fmt_number(float(self.stats['low']))}")
            p.drawText(QRectF(self.PAD_L, 16, self.width() - 2 * self.PAD_L, 22),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, hilo)

        if len(self.points) < 2:
            p.setPen(dim)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Grafik verisi yok")
            p.end()
            return

        plot = self._plot()
        lo, hi = self._range()
        f.setPointSize(8)
        f.setBold(False)
        p.setFont(f)
        for i in range(5):                                   # yatay izgara + fiyat etiketleri
            y = plot.top() + plot.height() * i / 4
            p.setPen(QPen(QColor(theme.BORDER), 1.0))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(faint)
            p.drawText(QRectF(plot.right() + 8, y - 8, self.PAD_R - 12, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fmt_number(hi - (hi - lo) * i / 4))
        intraday = self._intraday()
        for i in range(4):                                   # zaman etiketleri
            idx = round((len(self.points) - 1) * i / 3)
            x = plot.left() + plot.width() * i / 3
            align = (Qt.AlignmentFlag.AlignLeft if i == 0 else
                     Qt.AlignmentFlag.AlignRight if i == 3 else Qt.AlignmentFlag.AlignHCenter)
            p.drawText(QRectF(x - 70, plot.bottom() + 8, 140, 16).translated(70 if i == 0 else -70 if i == 3 else 0, 0),
                       align, self._time_text(self.points[idx][0], with_clock=intraday))

        pts = [self._xy(i, plot, lo, hi) for i in range(len(self.points))]
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        area = QPainterPath(line)
        area.lineTo(QPointF(pts[-1].x(), plot.bottom()))
        area.lineTo(QPointF(pts[0].x(), plot.bottom()))
        area.closeSubpath()
        fill = QLinearGradient(plot.topLeft(), plot.bottomLeft())
        fill.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 80))
        fill.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        p.fillPath(area, fill)
        p.setPen(QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(line)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(pts[-1], 3.5, 3.5)

        if self._hover is not None:
            pt = pts[self._hover]
            p.setPen(QPen(QColor(theme.BORDER_LIGHT), 1.0, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(pt.x(), plot.top()), QPointF(pt.x(), plot.bottom()))
            p.setPen(QPen(QColor(theme.BG_CARD), 2.0))
            p.setBrush(color)
            p.drawEllipse(pt, 5.0, 5.0)
            ts, value = self.points[self._hover]
            tip = f"{self._time_text(ts, with_clock=intraday)}   {fmt_number(value)}"
            f.setPointSize(9)
            f.setBold(True)
            p.setFont(f)
            wtip = p.fontMetrics().horizontalAdvance(tip) + 18
            x = min(max(plot.left(), pt.x() - wtip / 2), plot.right() - wtip)
            box = QRectF(x, plot.top() - 26, wtip, 22)
            p.setPen(QPen(QColor(theme.BORDER_LIGHT), 1.0))
            p.setBrush(QColor(theme.BG_CARD))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(text)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, tip)
        p.end()


# ======================================================================== hava
class _RangeBar(QWidget):
    """Gunun min-max sicakligini, tum gunlerin araligina gore konumlanmis cubuk olarak cizer."""

    def __init__(self, lo: float, hi: float, span: tuple[float, float]) -> None:
        super().__init__()
        self.lo, self.hi, self.span = lo, hi, span
        self.setMinimumSize(120, 14)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, mid = self.width(), self.height() / 2
        a, b = self.span
        width = (b - a) or 1.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(QRectF(0, mid - 2, w, 4), 2, 2)
        x0, x1 = w * (self.lo - a) / width, w * (self.hi - a) / width
        grad = QLinearGradient(QPointF(x0, 0), QPointF(x1, 0))
        grad.setColorAt(0.0, QColor(theme.USER_COLOR))
        grad.setColorAt(1.0, QColor(theme.GOLD))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(x0, mid - 3, max(6.0, x1 - x0), 6), 3, 3)
        p.end()


class WeatherView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(18)
        self.temp_label = _label("—", "weatherTemp")
        top.addWidget(self.temp_label)
        side = QVBoxLayout()
        side.setSpacing(2)
        self.cond_label = _label("", "weatherCond")
        self.detail_label = _label("", "newsMeta")
        side.addStretch(1)
        side.addWidget(self.cond_label)
        side.addWidget(self.detail_label)
        side.addStretch(1)
        top.addLayout(side, 1)
        lay.addLayout(top)
        lay.addSpacing(14)
        self._days = QGridLayout()
        self._days.setHorizontalSpacing(16)
        self._days.setVerticalSpacing(12)
        self._days.setColumnStretch(2, 1)
        lay.addLayout(self._days)
        lay.addStretch(1)
        self.day_rows: list[tuple[str, str]] = []

    def set_data(self, now: dict[str, Any], days: list[dict[str, Any]]) -> None:
        self.clear()
        temp = now.get("sicaklik")
        self.temp_label.setText(f"{round(temp)}°" if isinstance(temp, (int, float)) else "—")
        cond = str(now.get("durum", ""))
        self.cond_label.setText(_WEATHER_TR.get(cond, cond).capitalize())
        parts = []
        if isinstance(now.get("hissedilen"), (int, float)):
            parts.append(f"hissedilen {round(now['hissedilen'])}°")
        if isinstance(now.get("nem"), (int, float)):
            parts.append(f"nem %{round(now['nem'])}")
        if isinstance(now.get("ruzgar_kmh"), (int, float)):
            parts.append(f"rüzgar {round(now['ruzgar_kmh'])} km/s")
        self.detail_label.setText("  ·  ".join(parts))

        valid = [d for d in days if isinstance(d.get("min"), (int, float)) and isinstance(d.get("max"), (int, float))]
        if not valid:
            return
        span = (min(d["min"] for d in valid), max(d["max"] for d in valid))
        for row, d in enumerate(valid):
            try:
                name = DAYS_TR[datetime.fromisoformat(str(d.get("gun", ""))).weekday()]
            except ValueError:
                name = str(d.get("gun", ""))
            if row == 0:
                name = "Bugün"
            cond = str(d.get("durum", ""))
            text = f"{round(d['min'])}° / {round(d['max'])}°"
            self._days.addWidget(_label(name, "weatherDay"), row, 0)
            self._days.addWidget(_label(_WEATHER_TR.get(cond, cond), "newsMeta"), row, 1)
            self._days.addWidget(_RangeBar(d["min"], d["max"], span), row, 2)
            self._days.addWidget(_label(text, "weatherDay"), row, 3, Qt.AlignmentFlag.AlignRight)
            self.day_rows.append((name, text))

    def clear(self) -> None:
        while self._days.count():
            item = self._days.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.day_rows = []


# ================================================================== bilgi karti
class InfoView(QTextBrowser):
    """JARVIS'in yazdigi Markdown govde. Baglantilar acilmaz, uzak kaynak (gorsel) yuklenmez."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panelInfo")
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.document().setDocumentMargin(22)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Basliklar vurgu renginde; kisilik paleti degisince sonraki icerik yeni renkle yazilir."""
        self.document().setDefaultStyleSheet(
            f"h1, h2, h3 {{ color: {theme.ACCENT}; margin-top: 14px; margin-bottom: 6px; }} "
            f"a {{ color: {theme.TEXT}; text-decoration: none; }} li {{ margin-bottom: 3px; }} "
            f"table {{ border-color: {theme.BORDER_LIGHT}; margin-top: 10px; }} "
            f"th {{ color: {theme.ACCENT}; background-color: {theme.BG_INPUT}; padding: 6px 12px; }} "
            f"td {{ padding: 6px 12px; }} code {{ color: {theme.GOLD}; }}"
        )

    def loadResource(self, kind: int, name: QUrl):  # noqa: N802, ANN201
        return None   # hicbir dis kaynak (http gorsel, dosya) yuklenmez

    def set_body(self, body: str) -> None:
        # Markdown dogrudan yuklenince varsayilan stil sayfasi uygulanmaz; HTML'e cevrilip yuklenir
        doc = QTextDocument()
        font = QFont("Segoe UI")
        font.setPointSize(11)
        doc.setDefaultFont(font)
        doc.setMarkdown(body)
        self.setHtml(doc.toHtml())
        self.verticalScrollBar().setValue(0)
