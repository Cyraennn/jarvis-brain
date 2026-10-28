"""Sohbet gecmisi. Kesinlesen (final) mesajlari balon olarak listeler.

Kismi/canli transkript burada degil, orb'un altindaki 'caption' etiketinde gosterilir
(bkz. MainWindow).

Performans: en fazla `MAX_BUBBLES` parca (balon/sistem satiri) tutulur; asilinca en eskiler
toplu silinir. Kullanici yukari kaydirmissa yeni mesaj onu en alta ZORLAMAZ.
"""

from __future__ import annotations

import html

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextEdit, QWidget

from ui import theme

MAX_BUBBLES = 400
_TRIM_SLACK = 40   # sinir asilinca bir seferde bu kadar fazlasini birlikte at (her mesajda silme yok)


class TranscriptView(QTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("transcript")
        self._starts: list[int] = []   # her parcanin belge icindeki baslangic konumu

    @property
    def bubble_count(self) -> int:
        return len(self._starts)

    # ------------------------------------------------------------------ API
    def add_user(self, text: str) -> None:
        self._bubble("user", text)

    def add_assistant(self, text: str) -> None:
        self._bubble("assistant", text)

    def add_system(self, text: str) -> None:
        self._append(
            f'<div style="margin:10px 4px;color:{theme.TEXT_FAINT};'
            f'font-size:11px;letter-spacing:1px;">— {html.escape(text)} —</div>'
        )

    # ------------------------------------------------------------- internal
    def _bubble(self, role: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        who = "SEN" if role == "user" else theme.branding()["name"]
        color = theme.USER_COLOR if role == "user" else theme.JARVIS_COLOR
        align = "right" if role == "user" else "left"
        self._append(
            f'<table width="100%" style="margin:6px 0;"><tr><td align="{align}">'
            f'<div style="display:inline-block;text-align:left;'
            f'background:{theme.BG_PANEL_ALT};border:1px solid {theme.BORDER};'
            f'border-radius:12px;padding:8px 12px;">'
            f'<div style="color:{color};font-size:10px;font-weight:700;'
            f'letter-spacing:2px;margin-bottom:3px;">{who}</div>'
            f'<div style="color:{theme.TEXT};">{html.escape(text)}</div>'
            f"</div></td></tr></table>"
        )

    def _append(self, fragment: str) -> None:
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._starts.append(cursor.position())
        cursor.insertHtml(fragment)
        self._trim()
        if at_bottom:
            bar.setValue(bar.maximum())

    def _trim(self) -> None:
        """Sinir asildiysa en eski parcalari toplu sil (konumlari kaydir)."""
        if len(self._starts) <= MAX_BUBBLES + _TRIM_SLACK:
            return
        drop = len(self._starts) - MAX_BUBBLES
        cut = self._starts[drop]
        cursor = QTextCursor(self.document())
        cursor.setPosition(0)
        cursor.setPosition(cut, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._starts = [s - cut for s in self._starts[drop:]]
