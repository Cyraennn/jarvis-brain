"""EngineObserver -> Qt sinyal koprusu.

`BrainEngine` olaylari motor thread'inden gelir; Qt sinyalleri kuyruklu baglanti
ile otomatik olarak GUI thread'ine tasinir. Bu yuzden burada thread guvenligi
Qt tarafindan saglanir.

`confirm()` ozeldir: motor thread'ini BLOKLAYARAK GUI'de bir onay diyalogu acar
ve sonucu (evet/hayir) geri dondurur.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from core.events import EngineObserver
from web.event_bus import BUS


class ConfirmRequest:
    """GUI thread'ine tasinan onay istegi; sonuc bir Event ile geri bildirilir."""

    __slots__ = ("prompt", "_event", "result", "expired")

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt
        self.result = False
        self.expired = False   # motor tarafi zaman asimiyla vazgecti (sonuc artik kullanilmaz)
        self._event = threading.Event()

    def resolve(self, approved: bool) -> None:
        self.result = bool(approved)
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


class QtEngineObserver(QObject, EngineObserver):
    connection = Signal(str)
    state = Signal(str)
    input_level = Signal(float)
    output_level = Signal(float)
    user_transcript = Signal(str, bool)
    assistant_transcript = Signal(str, bool)
    tool_call = Signal(list)
    tool_result = Signal(str, bool, str)
    bridge_message = Signal(str)
    confirm_requested = Signal(object)  # ConfirmRequest
    app_exit_requested = Signal()
    external_typing = Signal(bool)
    wake = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        self._confirm_timeout = 90.0

    def _emit(self, name: str, *args) -> None:  # noqa: ANN002
        """Kapanista Qt nesnesi silindikten sonra motor thread'i hala olay yollayabilir; yut."""
        try:
            getattr(self, name).emit(*args)
        except RuntimeError:
            pass

    # --- EngineObserver implementasyonu -----------------------------------
    def on_connection(self, status: str) -> None:
        self._emit("connection", status)
        BUS.push("connection", status)

    def on_state(self, state: str) -> None:
        self._emit("state", state)
        BUS.push("engine_state", state)

    def on_input_level(self, level: float) -> None:
        self._emit("input_level", float(level))

    def on_output_level(self, level: float) -> None:
        self._emit("output_level", float(level))

    def on_user_transcript(self, text: str, final: bool) -> None:
        self._emit("user_transcript", text, bool(final))
        if final and text.strip():
            BUS.push("transcript", {"who": "user", "text": text, "ts": 0})

    def on_assistant_transcript(self, text: str, final: bool) -> None:
        self._emit("assistant_transcript", text, bool(final))
        if final and text.strip():
            BUS.push("transcript", {"who": "jarvis", "text": text, "ts": 0})

    def on_tool_call(self, names: list[str]) -> None:
        self._emit("tool_call", list(names))

    def on_tool_result(self, name: str, ok: bool, detail: str) -> None:
        self._emit("tool_result", name, bool(ok), detail)

    def on_bridge_message(self, text: str) -> None:
        self._emit("bridge_message", text)

    def confirm(self, prompt: str) -> bool:
        request = ConfirmRequest(prompt)
        self._emit("confirm_requested", request)  # kuyruklu -> GUI thread'inde islenir
        if not request.wait(self._confirm_timeout):
            request.expired = True  # GUI diyalogu bunu gorup kendini kapatir
            return False  # zaman asimi => reddet
        return request.result

    def on_exit_request(self) -> None:
        self._emit("app_exit_requested")

    def on_external_typing(self, active: bool) -> None:
        self._emit("external_typing", bool(active))

    def on_wake(self, awake: bool) -> None:
        self._emit("wake", bool(awake))
        BUS.push("wake", bool(awake))
