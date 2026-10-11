"""`POST /command` ve WS `command` icin: yazili mesaji canli oturuma ver, cevabi topla.

Canli oturum (Gemini Live, sesli) tek beyindir; /command ayni hafiza ve araclari kullanir.
Cevap, modelin konusma transkriptidir. Model once "bakiyorum" deyip arac cagirabilir,
ardindan asil cevabi verir; bu yuzden:
  - en az bir KESIN (final) asistan transkripti gelmis,
  - bekleyen arac cagrisi kalmamis ve
  - `settle_s` boyunca yeni hareket olmamis olmalidir.
Ayni anda tek komut islenir (kilit). Sesli konusma ayni anda surerse cevaplar karisabilir.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class EngineLike(Protocol):
    session_active: bool

    async def send_user_text(self, text: str) -> bool: ...


@dataclass
class CommandResult:
    ok: bool
    text: str = ""
    model: str = ""
    fallback: bool = False
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0
    tools: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "text": self.text, "model": self.model, "fallback": self.fallback,
            "error": self.error or None, "warnings": self.warnings, "elapsed_ms": self.elapsed_ms,
            "tools": self.tools,
        }


class _Collector:
    def __init__(self) -> None:
        self.finals: list[str] = []
        self.partial = ""
        self.pending_tools = 0
        self.tools: list[str] = []
        self.last_activity = time.monotonic()

    def touch(self) -> None:
        self.last_activity = time.monotonic()


class CommandBroker:
    def __init__(self, model_name: str = "", settle_s: float = 1.5) -> None:
        self.engine: EngineLike | None = None
        self.model_name = model_name
        self.settle_s = settle_s
        self._lock = asyncio.Lock()
        self._active: _Collector | None = None

    # ------------------------------------------------ gozlemciden gelen olaylar
    def on_assistant_transcript(self, text: str, final: bool) -> None:
        c = self._active
        if c is None:
            return
        if final:
            if text.strip():
                c.finals.append(text.strip())
            c.partial = ""
        else:
            c.partial = text
        c.touch()

    def on_tool_call(self, names: list[str]) -> None:
        c = self._active
        if c is None:
            return
        c.pending_tools += len(names)
        c.tools.extend(names)
        c.touch()

    def on_tool_result(self, name: str) -> None:
        c = self._active
        if c is None:
            return
        c.pending_tools = max(0, c.pending_tools - 1)
        c.touch()

    # ------------------------------------------------------------------ komut
    @property
    def busy(self) -> bool:
        return self._lock.locked()

    async def run(self, text: str, timeout: float = 90.0) -> CommandResult:
        text = (text or "").strip()
        if not text:
            return CommandResult(ok=False, error="bos metin")
        engine = self.engine
        if engine is None or not engine.session_active:
            return CommandResult(ok=False, model=self.model_name,
                                 error="Canli oturum bagli degil (Gemini Live). /health'e bakin.")
        started = time.monotonic()
        async with self._lock:
            collector = _Collector()
            self._active = collector
            try:
                if not await engine.send_user_text(text):
                    return CommandResult(ok=False, model=self.model_name,
                                         error="Mesaj oturuma iletilemedi (oturum kapandi).")
                return await self._wait(collector, timeout, started)
            finally:
                self._active = None

    async def _wait(self, c: _Collector, timeout: float, started: float) -> CommandResult:
        deadline = started + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            quiet = time.monotonic() - c.last_activity
            if c.finals and c.pending_tools == 0 and quiet >= self.settle_s:
                return CommandResult(ok=True, text=" ".join(c.finals), model=self.model_name,
                                     elapsed_ms=_ms(started), tools=c.tools)
        text = " ".join([*c.finals, c.partial]).strip()
        if text:
            return CommandResult(ok=True, text=text, model=self.model_name, elapsed_ms=_ms(started),
                                 tools=c.tools,
                                 warnings=[f"{timeout:.0f} sn zaman asimi - cevap eksik olabilir"])
        return CommandResult(ok=False, model=self.model_name, elapsed_ms=_ms(started), tools=c.tools,
                             error=f"{timeout:.0f} sn icinde cevap gelmedi")


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
