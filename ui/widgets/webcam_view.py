"""Canli webcam onizlemesi.

`WebcamStreamer.get_latest_jpeg()`'i bir QTimer ile yoklar (motorla ayni thread-safe
kaynak). Kare yoksa veya akis kapaliysa sik bir yer tutucu gosterir.

Performans: ayni kare tekrar gelirse decode/olcekleme yapilmaz; olceklenmis kare
onbellege alinir (yeniden boyutlandirma / yeni karede bir kez); widget gizliyken
zamanlayici durur.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ui import theme


class WebcamView(QWidget):
    def __init__(
        self,
        frame_provider: Callable[[], bytes | None],
        parent: QWidget | None = None,
        placeholder: str = "KAMERA KAPALI",
    ) -> None:
        super().__init__(parent)
        self._provider = frame_provider
        self._pixmap: QPixmap | None = None
        self._last_data: bytes | None = None
        self._scaled: QPixmap | None = None
        self._scaled_key: tuple | None = None
        self._active = True
        self._placeholder = placeholder
        self.decode_count = 0   # gozlem/test: kac kare decode edildi
        self.scale_count = 0    # gozlem/test: kac kez olceklendi
        self.setMinimumSize(240, 150)

        self._timer = QTimer(self)
        self._timer.setInterval(40)  # ~25 FPS
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active:
            self._pixmap = None
            self._scaled = None
            self._scaled_key = None
            self._last_data = None
        self.update()

    # -------------------------------------------------------------- gorunurluk
    def hideEvent(self, event) -> None:  # noqa: N802, ANN001
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        if not self._timer.isActive():
            self._timer.start()
        super().showEvent(event)

    # ------------------------------------------------------------------ poll
    def _poll(self) -> None:
        if not self._active:
            return
        try:
            data = self._provider()
        except Exception:  # noqa: BLE001
            data = None
        if not data:
            return
        # Ayni kare (ozellikle seyrek guncellenen ekran karesi): decode/olcekleme yok
        if data is self._last_data or data == self._last_data:
            return
        image = QImage.fromData(data, "JPG")
        if image.isNull():
            return
        self._last_data = data
        self._pixmap = QPixmap.fromImage(image)
        self._scaled = None
        self._scaled_key = None
        self.decode_count += 1
        self.update()

    def _scaled_pixmap(self) -> QPixmap | None:
        """Hedef boyuta (DPR dahil) olceklenmis kare; yalnizca gerekince yeniden uretilir."""
        if self._pixmap is None or self._pixmap.isNull():
            return None
        dpr = self.devicePixelRatioF()
        key = (self._pixmap.cacheKey(), self.width(), self.height(), dpr)
        if self._scaled is None or self._scaled_key != key:
            target = self.size() * dpr
            scaled = self._pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            self._scaled, self._scaled_key = scaled, key
            self.scale_count += 1
        return self._scaled

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.BG_PANEL_ALT))
        painter.drawRoundedRect(rect, 10, 10)

        scaled = self._scaled_pixmap()
        if scaled is not None:
            dpr = scaled.devicePixelRatio() or 1.0
            x = int((scaled.width() / dpr - self.width()) // 2)
            y = int((scaled.height() / dpr - self.height()) // 2)
            painter.setClipRect(rect)
            painter.drawPixmap(-x, -y, scaled)
            painter.setClipping(False)
        else:
            painter.setPen(QPen(QColor(theme.TEXT_FAINT)))
            msg = self._placeholder if not self._active else "BEKLENİYOR..."
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, msg)

        # ince cerceve + kose vurgulari
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QPen(QColor(theme.ACCENT_DIM), 2))
        c = 14
        for x, y, dx, dy in (
            (rect.left() + 4, rect.top() + 4, 1, 1),
            (rect.right() - 4, rect.top() + 4, -1, 1),
            (rect.left() + 4, rect.bottom() - 4, 1, -1),
            (rect.right() - 4, rect.bottom() - 4, -1, -1),
        ):
            painter.drawLine(x, y, x + dx * c, y)
            painter.drawLine(x, y, x, y + dy * c)
        painter.end()
