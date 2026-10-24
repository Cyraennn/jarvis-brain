"""HUD veri karti: Zoey OS cam yuzeyi (ustu isikli, ici koyu gradyan) + baslik seridi, katlanabilir govde."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from ui import theme

RADIUS = theme.CARD_RADIUS   # kose yaricapi (px)
HEAD_H = 30      # baslik seridi yuksekligi; ayirici cizgi bunun altina cizilir
MARK = 5.0       # baslik onundeki isaret (px)
SHADOW_R = 2     # golgenin saga tasmasi (px)
SHADOW_B = 5     # golgenin alta tasmasi (px)

_EDGE = QColor(255, 255, 255, 28)        # Zoey --glass-border (#ffffff1c)
_EDGE_LIGHT = QColor(255, 255, 255, 41)  # Zoey inset ust isik (#ffffff29)


def paint_surface(
    p: QPainter, w: float, h: float, top: str, bottom: str,
    stops: tuple[tuple[float, str], ...] | None = None,
) -> QRectF:
    """Cam yuzey cizer: (varsa) alta dusen golge, ustten alta gradyan, ust kenarda isik cizgisi.

    `stops` verilirse iki renkli gradyan yerine bu duraklar kullanilir. Yuzeyin (golge payi
    dusulmus) dikdortgenini doner.
    """
    rect = QRectF(0.5, 0.5, w - 1.0 - SHADOW_R, h - 1.0 - SHADOW_B)
    r, g, b, a = theme.SHADOW
    p.setPen(Qt.PenStyle.NoPen)
    if a:
        for i, k in enumerate((0.28, 0.55, 1.0)):       # distan ice koyulasan 3 katman
            off = SHADOW_B - i * 1.6
            p.setBrush(QColor(r, g, b, int(a * k)))
            p.drawRoundedRect(rect.translated(SHADOW_R * (1 - i / 3), off), RADIUS + 1, RADIUS + 1)
    fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    for at, color in stops or ((0.0, top), (1.0, bottom)):
        fill.setColorAt(at, QColor(color))
    p.setPen(QPen(_EDGE, 1.0))
    p.setBrush(fill)
    p.drawRoundedRect(rect, RADIUS, RADIUS)
    p.setPen(QPen(_EDGE_LIGHT, 1.0))    # ust kenar isigi
    p.drawLine(QPointF(rect.left() + RADIUS, rect.top() + 0.5), QPointF(rect.right() - RADIUS, rect.top() + 0.5))
    return rect


class HudCard(QFrame):
    def __init__(
        self,
        title: str,
        *,
        collapsible: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("hudCard")
        self._tick = QColor(theme.HUD_TICK)
        self._edge = QColor(theme.HUD_EDGE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 0, 12 + SHADOW_R, 10 + SHADOW_B)
        outer.setSpacing(8)

        head_box = QWidget()
        head_box.setFixedHeight(HEAD_H)
        head = QHBoxLayout(head_box)
        head.setContentsMargins(int(MARK) + 8, 0, 0, 0)   # soldaki kare isarete yer
        head.setSpacing(7)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("hudCardTitle")
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("hudCardMeta")
        head.addWidget(self.meta_label)
        self._toggle: QToolButton | None = None
        if collapsible:
            self._toggle = QToolButton()
            self._toggle.setObjectName("hudCardToggle")
            self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self._toggle.setText("▾")
            self._toggle.setToolTip("Kartı daralt / genişlet")
            self._toggle.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
            head.addWidget(self._toggle)
        outer.addWidget(head_box)

        self._body_widget = QWidget()
        self.body = QVBoxLayout(self._body_widget)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(4)
        outer.addWidget(self._body_widget, 1)
        self.collapsed = False

    # ------------------------------------------------------------------ API
    def refresh_theme(self) -> None:
        """Kisilik paleti degisti: isaret ve kenar rengini yeniden oku."""
        self._tick = QColor(theme.HUD_TICK)
        self._edge = QColor(theme.HUD_EDGE)
        self.update()

    def set_meta(self, text: str) -> None:
        self.meta_label.setText(text)

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        self._body_widget.setVisible(not collapsed)
        if self._toggle is not None:
            self._toggle.setText("▸" if collapsed else "▾")
        self.update()

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = paint_surface(p, self.width(), self.height(), theme.CARD_TOP, theme.CARD_BOTTOM,
                             theme.CARD_STOPS)
        if not self.collapsed:
            p.setPen(QPen(self._edge, 1.0))
            p.drawLine(QPointF(rect.left() + 1, HEAD_H + 0.5), QPointF(rect.right() - 1, HEAD_H + 0.5))
        # baslik isareti: Zoey'deki gibi parlayan turuncu nokta
        p.setPen(Qt.PenStyle.NoPen)
        center = QPointF(12.0 + MARK / 2.0, HEAD_H / 2.0)
        glow = QColor(self._tick)
        glow.setAlpha(60)
        p.setBrush(glow)
        p.drawEllipse(center, MARK, MARK)
        p.setBrush(self._tick)
        p.drawEllipse(center, MARK / 2.0, MARK / 2.0)
        p.end()
