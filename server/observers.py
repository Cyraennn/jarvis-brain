"""Sunucu gozlemcisi: mevcut `WebEngineObserver` (BUS + uzak onay) + istemcilere canli olaylar.

BUS'a zaten yazilan olaylar (baglanti, durum, final transkript, arac, onay...) `ClientHub.
pump_bus` ile istemcilere gider. Burada yalnizca BUS'ta OLMAYAN yuksek frekansli canli
olaylar (ses seviyesi - saniyede en fazla ~10 kez, kismi transkript, dis yazma) eklenir ve
`/command` icin `CommandBroker` beslenir.
"""

from __future__ import annotations

import time

from server.command import CommandBroker
from server.hub import ClientHub
from web.web_observer import WebEngineObserver

LEVEL_MIN_INTERVAL_S = 0.1


class ServerEngineObserver(WebEngineObserver):
    def __init__(self, hub: ClientHub, broker: CommandBroker, confirm_timeout: float = 120.0) -> None:
        super().__init__(confirm_timeout=confirm_timeout)
        self._hub = hub
        self._broker = broker
        self._last_level: dict[str, float] = {"in": 0.0, "out": 0.0}

    def _level(self, which: str, kind: str, level: float) -> None:
        now = time.monotonic()
        if level > 0.0 and now - self._last_level[which] < LEVEL_MIN_INTERVAL_S:
            return
        self._last_level[which] = now
        self._hub.publish_threadsafe(kind, round(float(level), 3))

    def on_input_level(self, level: float) -> None:
        self._level("in", "input_level", level)

    def on_output_level(self, level: float) -> None:
        self._level("out", "output_level", level)

    def on_user_transcript(self, text: str, final: bool) -> None:
        super().on_user_transcript(text, final)
        if not final:
            self._hub.publish_threadsafe("transcript_partial", {"who": "user", "text": text})

    def on_assistant_transcript(self, text: str, final: bool) -> None:
        super().on_assistant_transcript(text, final)
        self._broker.on_assistant_transcript(text, final)
        if not final:
            self._hub.publish_threadsafe("transcript_partial", {"who": "cyraen", "text": text})

    def on_tool_call(self, names: list[str]) -> None:
        super().on_tool_call(names)
        self._broker.on_tool_call(names)

    def on_tool_result(self, name: str, ok: bool, detail: str) -> None:
        super().on_tool_result(name, ok, detail)
        self._broker.on_tool_result(name)

    def on_external_typing(self, active: bool) -> None:
        self._hub.publish_threadsafe("external_typing", bool(active))
