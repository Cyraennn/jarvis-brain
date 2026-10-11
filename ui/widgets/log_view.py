"""Sistem / arac / kopru logu paneli.

loguru sink'inden gelen satirlari ve yapisal olaylari (arac cagrisi, kopru mesaji)
renkli ikonlarla gosterir. Satir sayisi sinirlanir.

Performans: satirlar kuyruga alinip 100 ms'de bir toplu eklenir (yogun log akisinda
her satir icin ayri GUI isi yapilmaz). Kullanici yukari kaydirmissa en alta ZORLANMAZ.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from ui import theme

_MAX_BLOCKS = 2000
_FLUSH_MS = 100
_MAX_PER_FLUSH = 200   # bir seferde en fazla bu kadar satir; kalani sonraki turda

_LEVEL_COLOR = {
    "DEBUG": theme.TEXT_FAINT,
    "INFO": theme.TEXT_DIM,
    "SUCCESS": theme.GOOD,
    "WARNING": theme.WARN,
    "ERROR": theme.BAD,
    "CRITICAL": theme.BAD,
}


class LogView(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(_MAX_BLOCKS)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._pending: list[str] = []
        self._timer = QTimer(self)
        self._timer.setInterval(_FLUSH_MS)
        self._timer.timeout.connect(self.flush)

    def add_log(self, level: str, message: str) -> None:
        color = _LEVEL_COLOR.get(level.upper(), theme.TEXT_DIM)
        self._line(color, message)

    def add_event(self, icon: str, message: str, color: str | None = None) -> None:
        self._line(color or theme.ACCENT, f"{icon}  {message}")

    def _line(self, color: str, text: str) -> None:
        self._pending.append(
            f'<span style="color:{color};white-space:pre;">{_esc(text)}</span>'
        )
        if not self._timer.isActive():
            self._timer.start()

    def flush(self) -> None:
        """Bekleyen satirlari toplu ekler; kullanici en alttaysa kaydirir."""
        if not self._pending:
            self._timer.stop()
            return
        batch, self._pending = self._pending[:_MAX_PER_FLUSH], self._pending[_MAX_PER_FLUSH:]
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self.setUpdatesEnabled(False)
        try:
            for html_line in batch:
                self.appendHtml(html_line)
        finally:
            self.setUpdatesEnabled(True)
        if at_bottom:
            bar.setValue(bar.maximum())
        if not self._pending:
            self._timer.stop()


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
