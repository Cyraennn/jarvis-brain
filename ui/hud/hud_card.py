"""HUD veri karti: yari saydam cam zemin, kesik koseler, baslik seridi, katlanabilir govde."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from ui import theme

CUT = 11.0   # kesik kose boyu (px)


class HudCard(QFrame):
    def __init__(
        self,
        title: str,
        index: str = "",
        *,
        collapsible: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("hudCard")
        self._glass = QColor(*theme.HUD_GLASS)
        self._edge = QColor(theme.HUD_EDGE)
        self._tick = QColor(theme.HUD_TICK)
        self._gold = QColor(theme.GOLD)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 10)
        outer.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(7)
        if index:
            idx = QLabel(index)
            idx.setObjectName("hudCardIndex")
            head.addWidget(idx)
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
        outer.addLayout(head)

        self._body_widget = QWidget()
        self.body = QVBoxLayout(self._body_widget)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(4)
        outer.addWidget(self._body_widget, 1)
        self.collapsed = False

    # ------------------------------------------------------------------ API
    def set_meta(self, text: str) -> None:
        self.meta_label.setText(text)

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        self._body_widget.setVisible(not collapsed)
        if self._toggle is not None:
            self._toggle.setText("▸" if collapsed else "▾")

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        w, h = self.width() - 1.0, self.height() - 1.0
        path = QPainterPath(QPointF(CUT, 0.5))
        path.lineTo(w, 0.5)
        path.lineTo(w, h - CUT)
        path.lineTo(w - CUT, h)
        path.lineTo(0.5, h)
        path.lineTo(0.5, CUT)
        path.closeSubpath()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(self._edge, 1.0))
        p.setBrush(self._glass)
        p.drawPath(path)
        # kose isaretleri: sol-ust kesik boyunca cyan, sag-alt kesik boyunca altin
        p.setPen(QPen(self._tick, 2.0))
        p.drawLine(QPointF(0.5, CUT), QPointF(CUT, 0.5))
        p.drawLine(QPointF(CUT, 0.5), QPointF(CUT + 26, 0.5))
        p.setPen(QPen(self._gold, 2.0))
        p.drawLine(QPointF(w, h - CUT), QPointF(w - CUT, h))
        p.end()
